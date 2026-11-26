"""One HTTP request to one already-checked address.

The fetcher decides where a request may go; this sends it there. The connection is made
to the address it is given, never to the host name, while TLS and the ``Host`` header use
the name. Redirects are not followed here: the fetcher checks each one first.
"""

from __future__ import annotations

import http.client
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from ai_briefing.sources.network import FetchError

CHUNK = 65536


class ResponseTooLarge(FetchError):  # noqa: N818 - reads as a statement of fact
    """The response was longer than the policy allows. Reading stopped at the limit."""


@dataclass(frozen=True)
class HopRequest:
    scheme: str
    host: str
    port: int
    address: str  # the checked address to connect to
    path: str
    headers: Mapping[str, str]
    timeout_seconds: float
    max_bytes: int


@dataclass(frozen=True)
class HopResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)  # names in lower case
    body: bytes = b""


class Transport(Protocol):
    def send(self, request: HopRequest) -> HopResponse:
        """Send one GET and return its response. Never follows a redirect."""


class HttpTransport:
    """The real transport, on the standard library."""

    def __init__(self, ssl_context: ssl.SSLContext | None = None) -> None:
        self._ssl_context = ssl_context or ssl.create_default_context()

    def send(self, request: HopRequest) -> HopResponse:
        try:
            raw = socket.create_connection(
                (request.address, request.port), timeout=request.timeout_seconds
            )
        except OSError as error:
            raise FetchError(
                f"could not connect to {request.host}: {type(error).__name__}"
            ) from error
        try:
            connection: http.client.HTTPConnection
            if request.scheme == "https":
                # The certificate is checked against the host name, not the address.
                sock: socket.socket = self._ssl_context.wrap_socket(
                    raw, server_hostname=request.host
                )
                connection = http.client.HTTPSConnection(
                    request.host, request.port, timeout=request.timeout_seconds
                )
            else:
                sock = raw
                connection = http.client.HTTPConnection(
                    request.host, request.port, timeout=request.timeout_seconds
                )
            connection.sock = sock  # already connected, to the checked address
            try:
                connection.request("GET", request.path, headers=dict(request.headers))
                response = connection.getresponse()
                body = _read_limited(response, request.max_bytes)
                headers = {name.lower(): value for name, value in response.getheaders()}
                return HopResponse(status=response.status, headers=headers, body=body)
            finally:
                connection.close()
        except ResponseTooLarge:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise FetchError(f"request to {request.host} failed: {type(error).__name__}") from error
        finally:
            raw.close()


def _read_limited(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    declared = response.getheader("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLarge(f"the response declares {declared} bytes; the limit is {max_bytes}")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(CHUNK, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLarge(f"the response is longer than the limit of {max_bytes} bytes")
        chunks.append(chunk)

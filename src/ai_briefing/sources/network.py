"""The network policy every fetch goes through (RFC §11, ADR-008).

The host this runs on also runs home automation, so a fetch must never be steerable to an
address inside the home network. The rules:

- HTTPS only, on the standard port, with no credentials in the URL.
- The host name is resolved, and *every* address it resolves to must be public. Private,
  loopback, link-local, multicast and reserved ranges are refused.
- The connection is then made to one of those checked addresses, not to the name, so a
  name cannot resolve to a public address for the check and a private one for the
  connection.
- All of this is repeated on every redirect, and redirects are counted.
- Responses are limited in size and requests in time.

This module holds the rules and decides; it performs no network I/O itself apart from the
system resolver, which is replaceable.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit


class FetchError(Exception):
    """A fetch did not produce a usable response."""


class Blocked(FetchError):  # noqa: N818 - reads as a statement of fact
    """The network policy refused the request before any connection was made."""


@dataclass(frozen=True)
class NetworkPolicy:
    allowed_schemes: tuple[str, ...] = ("https",)
    allowed_ports: tuple[int, ...] = (443,)
    max_redirects: int = 5
    timeout_seconds: float = 20.0
    max_response_bytes: int = 5_000_000
    # For tests of the real transport against a local server only. Never set in the
    # application: it switches off the protection this module exists for.
    allow_non_public_addresses: bool = False


@dataclass(frozen=True)
class Target:
    """A URL that has passed the policy's checks on its form."""

    url: str
    scheme: str
    host: str
    port: int
    path: str  # path and query, as sent on the request line


class Resolver(Protocol):
    def resolve(self, host: str, port: int) -> list[str]:
        """Every address the host resolves to, as text."""


class SystemResolver:
    """Resolves through the operating system."""

    def resolve(self, host: str, port: int) -> list[str]:
        try:
            found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise FetchError(f"could not resolve {host}: {type(error).__name__}") from error
        return list(dict.fromkeys(str(entry[4][0]) for entry in found))


def is_public_address(address: str) -> bool:
    """True only for an address on the public internet."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None:
            return is_public_address(str(embedded))
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_url(url: str, policy: NetworkPolicy) -> Target:
    """Check a URL's form against the policy. Raises :class:`Blocked`."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise Blocked(f"not a usable URL: {url!r}") from error
    scheme = parts.scheme.lower()
    if scheme not in policy.allowed_schemes:
        raise Blocked(f"scheme {scheme or '(none)'!r} is not allowed: {url!r}")
    if parts.username is not None or parts.password is not None:
        raise Blocked("a URL with credentials in it is not fetched")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise Blocked(f"no host in {url!r}")
    if port is None:
        port = 443 if scheme == "https" else 80
    if port not in policy.allowed_ports:
        raise Blocked(f"port {port} is not allowed: {url!r}")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return Target(url=url, scheme=scheme, host=host, port=port, path=path)


def checked_address(target: Target, resolver: Resolver, policy: NetworkPolicy) -> str:
    """Resolve the target and return the address to connect to.

    Every address the name resolves to must be public; one non-public address refuses the
    request, because the connection could otherwise be steered to it. A host that is
    itself an address literal is checked the same way.
    """
    try:
        ipaddress.ip_address(target.host.strip("[]"))
        addresses = [target.host.strip("[]")]
    except ValueError:
        addresses = resolver.resolve(target.host, target.port)
    if not addresses:
        raise FetchError(f"{target.host} did not resolve to any address")
    if not policy.allow_non_public_addresses:
        refused = [a for a in addresses if not is_public_address(a)]
        if refused:
            raise Blocked(
                f"{target.host} resolves to a non-public address ({refused[0]}); not fetched"
            )
    return addresses[0]


def host_allowed(host: str, allowed_hosts: frozenset[str] | None) -> bool:
    """True when ``host`` is one of the allowed hosts exactly. No subdomain matching."""
    return allowed_hosts is None or host.lower().rstrip(".") in allowed_hosts

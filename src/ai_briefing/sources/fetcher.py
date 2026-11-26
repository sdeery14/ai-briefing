"""Fetching a URL under the network policy, a rate limit and robots.txt.

Every hop of a request, the first and each redirect, is checked before it is sent: the
URL's form, the host against the caller's allowed hosts, robots.txt, and the addresses
the host resolves to. Nothing fetched is ever interpreted as an instruction; the fetcher
returns bytes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from ai_briefing.sources.network import (
    Blocked,
    FetchError,
    NetworkPolicy,
    Resolver,
    Target,
    check_url,
    checked_address,
    host_allowed,
)
from ai_briefing.sources.transport import HopRequest, HopResponse, ResponseTooLarge, Transport

REDIRECTS = frozenset({301, 302, 303, 307, 308})
ROBOTS_MAX_BYTES = 500_000


class TooManyRedirects(FetchError):  # noqa: N818 - reads as a statement of fact
    """The redirect limit was reached."""


class HttpStatusError(FetchError):
    """The server answered with a status that is not a success."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"{url} answered {status}")
        self.status = status


@dataclass(frozen=True)
class FetchResult:
    not_modified: bool
    final_url: str
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None


class Fetcher:
    """Fetches under one policy, remembering per-host timing and robots.txt for its life."""

    def __init__(
        self,
        *,
        transport: Transport,
        resolver: Resolver,
        policy: NetworkPolicy | None = None,
        user_agent: str = "ai-briefing",
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._resolver = resolver
        self._policy = policy or NetworkPolicy()
        # A generic client name with no personal details (ADR-010).
        self._user_agent = user_agent
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def fetch(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str] | None,
        min_seconds_between_requests: float,
        etag: str | None = None,
        last_modified: str | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult:
        """GET ``url``, following checked redirects. Raises :class:`FetchError`.

        ``allowed_hosts`` confines the request, and every redirect, to those hosts.
        ``etag`` and ``last_modified`` make the request conditional; a 304 comes back as
        ``not_modified``.
        """
        limit = min(max_bytes or self._policy.max_response_bytes, self._policy.max_response_bytes)
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        current = url
        for _ in range(self._policy.max_redirects + 1):
            target = self._checked(current, allowed_hosts)
            if not self._robots_allow(target, min_seconds_between_requests):
                raise Blocked(f"robots.txt for {target.host} disallows {target.path}")
            response = self._send(target, headers, limit, min_seconds_between_requests)
            if response.status in REDIRECTS:
                location = response.headers.get("location")
                if not location:
                    raise FetchError(f"{current} redirected without saying where")
                try:
                    current = urljoin(current, location)
                except ValueError as error:
                    raise FetchError(f"{current} redirected to an unusable address") from error
                continue
            if response.status == 304:
                return FetchResult(not_modified=True, final_url=current)
            if response.status != 200:
                raise HttpStatusError(response.status, current)
            if len(response.body) > limit:
                raise ResponseTooLarge(f"the response is longer than the limit of {limit} bytes")
            return FetchResult(
                not_modified=False,
                final_url=current,
                body=response.body,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                content_type=response.headers.get("content-type"),
            )
        raise TooManyRedirects(f"more than {self._policy.max_redirects} redirects from {url}")

    def _checked(self, url: str, allowed_hosts: frozenset[str] | None) -> Target:
        target = check_url(url, self._policy)
        if not host_allowed(target.host, allowed_hosts):
            raise Blocked(f"{target.host} is not a host this source may be fetched from")
        return target

    def _send(
        self, target: Target, headers: dict[str, str], max_bytes: int, min_interval: float
    ) -> HopResponse:
        # Resolved and checked immediately before each connection, and the connection is
        # made to the checked address.
        address = checked_address(target, self._resolver, self._policy)
        self._wait_for_turn(target.host, min_interval)
        try:
            return self._transport.send(
                HopRequest(
                    scheme=target.scheme,
                    host=target.host,
                    port=target.port,
                    address=address,
                    path=target.path,
                    headers={**headers, "Host": target.host},
                    timeout_seconds=self._policy.timeout_seconds,
                    max_bytes=max_bytes,
                )
            )
        finally:
            self._last_request[target.host] = self._clock()

    def _wait_for_turn(self, host: str, min_interval: float) -> None:
        last = self._last_request.get(host)
        if last is None:
            return
        remaining = min_interval - (self._clock() - last)
        if remaining > 0:
            self._sleep(remaining)

    def _robots_allow(self, target: Target, min_interval: float) -> bool:
        """Whether robots.txt lets this client fetch the target (ADR-010).

        robots.txt is fetched once per host, under the same policy. A missing file allows
        everything, which is the convention. A file that cannot be read for any other
        reason allows nothing: the site's wishes are unknown.
        """
        if target.path.split("?", 1)[0] == "/robots.txt":
            return True
        if target.host not in self._robots:
            self._robots[target.host] = self._load_robots(target, min_interval)
        rules = self._robots[target.host]
        return rules is not None and rules.can_fetch(self._user_agent, target.url)

    def _load_robots(self, target: Target, min_interval: float) -> RobotFileParser | None:
        robots_url = f"{target.scheme}://{target.host}/robots.txt"
        rules = RobotFileParser()
        try:
            response = self._send(
                check_url(robots_url, self._policy),
                {"User-Agent": self._user_agent, "Accept-Encoding": "identity"},
                ROBOTS_MAX_BYTES,
                min_interval,
            )
        except Blocked:
            raise  # the policy refused the host itself; that is the reason to report
        except FetchError:
            return None
        if response.status in (404, 410):
            rules.parse([])
            return rules
        if response.status != 200:
            return None  # includes a redirect: robots.txt is read from the host itself
        rules.parse(response.body.decode("utf-8", errors="replace").splitlines())
        return rules

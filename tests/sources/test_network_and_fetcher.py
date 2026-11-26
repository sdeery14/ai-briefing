"""The network policy: no fetch can be steered to a private address, by any route
(RFC §11, ADR-008). These are the policy's acceptance tests.
"""

from __future__ import annotations

import pytest

from ai_briefing.sources.fetcher import HttpStatusError, TooManyRedirects
from ai_briefing.sources.network import (
    Blocked,
    FetchError,
    NetworkPolicy,
    check_url,
    checked_address,
    is_public_address,
)
from ai_briefing.sources.transport import HopRequest, HopResponse, ResponseTooLarge

from .conftest import (
    OTHER_PUBLIC,
    PUBLIC,
    FakeClock,
    FakeResolver,
    FakeTransport,
    make_fetcher,
    ok,
    redirect,
)

FEED = "https://feeds.example.org/feed.xml"
ANY = None  # no host restriction, so the address checks are what is being tested
POLICY = NetworkPolicy()

NON_PUBLIC = [
    "127.0.0.1",
    "127.8.8.8",
    "10.0.0.5",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.10",
    "169.254.169.254",  # link-local; the cloud metadata address
    "100.64.0.1",  # carrier-grade NAT
    "0.0.0.0",  # noqa: S104 - an address under test, not a bind
    "224.0.0.1",
    "255.255.255.255",
    "192.0.2.1",  # documentation range
    "::1",
    "::",
    "fe80::1",
    "fe80::1%eth0",
    "fc00::1",
    "fd12:3456:789a::1",
    "ff02::1",
    "::ffff:192.168.1.10",  # IPv4-mapped private
    "::ffff:127.0.0.1",
    "2002:c0a8:0101::1",  # 6to4 of 192.168.1.1
    "not-an-address",
    "",
]


@pytest.mark.parametrize("address", NON_PUBLIC)
def test_a_non_public_address_is_never_public(address: str) -> None:
    assert is_public_address(address) is False


@pytest.mark.parametrize("address", [PUBLIC, "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_a_public_address_is_public(address: str) -> None:
    assert is_public_address(address) is True


# --- The form of a URL ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://feeds.example.org/feed.xml",
        "ftp://feeds.example.org/feed.xml",
        "file:///etc/passwd",
        "gopher://feeds.example.org/",
        "javascript:alert(1)",
        "//feeds.example.org/feed.xml",
        "feeds.example.org/feed.xml",
        "https://user:secret@feeds.example.org/feed.xml",
        "https://user@feeds.example.org/feed.xml",
        "https://feeds.example.org:8443/feed.xml",
        "https://feeds.example.org:22/",
        "https://feeds.example.org:99999/",
        "https:///feed.xml",
        "https://",
        "",
    ],
)
def test_a_url_that_is_not_plain_https_is_refused(url: str) -> None:
    with pytest.raises(Blocked):
        check_url(url, POLICY)


def test_a_plain_https_url_is_accepted() -> None:
    target = check_url("https://Feeds.Example.org./a/b?x=1#frag", POLICY)
    assert (target.scheme, target.host, target.port, target.path) == (
        "https",
        "feeds.example.org",
        443,
        "/a/b?x=1",
    )


# --- Addresses --------------------------------------------------------------------------------


@pytest.mark.parametrize("address", NON_PUBLIC[:21])
def test_a_host_that_resolves_to_a_non_public_address_is_refused(address: str) -> None:
    resolver = FakeResolver({"feeds.example.org": [address]})
    with pytest.raises(Blocked, match="non-public address"):
        checked_address(check_url(FEED, POLICY), resolver, POLICY)


def test_one_non_public_address_among_public_ones_refuses_the_host() -> None:
    # Otherwise the connection could be steered to the private one.
    for addresses in ([PUBLIC, "192.168.1.10"], ["10.0.0.5", PUBLIC], [PUBLIC, "::1"]):
        resolver = FakeResolver({"feeds.example.org": addresses})
        with pytest.raises(Blocked):
            checked_address(check_url(FEED, POLICY), resolver, POLICY)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/feed.xml",
        "https://192.168.1.10/",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/",
        "https://[fe80::1]/",
        "https://[::ffff:10.0.0.5]/",
        "https://0.0.0.0/",
        "https://2130706433/",  # 127.0.0.1 written as one number
        "https://0x7f000001/",
        "https://localhost/",
    ],
)
def test_an_address_literal_or_local_name_is_refused(url: str) -> None:
    transport = FakeTransport()
    resolver = FakeResolver({"localhost": ["127.0.0.1"], "2130706433": ["127.0.0.1"]})
    resolver.addresses["0x7f000001"] = ["127.0.0.1"]
    with pytest.raises(FetchError):
        make_fetcher(transport, resolver).fetch(
            url, allowed_hosts=ANY, min_seconds_between_requests=0
        )
    assert transport.requests == []


def test_a_host_that_does_not_resolve_is_an_error_not_a_request() -> None:
    transport = FakeTransport()
    with pytest.raises(FetchError):
        make_fetcher(transport).fetch(
            "https://nowhere.invalid/", allowed_hosts=ANY, min_seconds_between_requests=0
        )
    assert transport.requests == []


# --- Fetching ---------------------------------------------------------------------------------


def fetch(transport: FakeTransport, resolver: FakeResolver | None = None, **kwargs: object):  # type: ignore[no-untyped-def]
    options: dict[str, object] = {"allowed_hosts": ANY, "min_seconds_between_requests": 0}
    options.update(kwargs)
    return make_fetcher(transport, resolver).fetch(FEED, **options)  # type: ignore[arg-type]


def test_a_fetch_connects_to_the_address_that_was_checked() -> None:
    transport = FakeTransport(
        {FEED: ok("feed", etag='"v1"', last_modified="Thu", content_type="application/rss+xml")}
    )
    resolver = FakeResolver({"feeds.example.org": [OTHER_PUBLIC]})
    result = fetch(transport, resolver)
    assert result.body == b"feed"
    assert (result.etag, result.last_modified) == ('"v1"', "Thu")
    assert result.content_type == "application/rss+xml"
    request = transport.requests[-1]
    assert request.address == OTHER_PUBLIC  # the connection goes to the checked address
    assert request.host == "feeds.example.org"  # TLS and the Host header use the name
    assert request.headers["Host"] == "feeds.example.org"
    assert (request.scheme, request.port) == ("https", 443)


def test_a_private_address_is_refused_before_any_connection() -> None:
    transport = FakeTransport()
    resolver = FakeResolver({"feeds.example.org": ["192.168.1.10"]})
    with pytest.raises(Blocked, match="non-public"):
        fetch(transport, resolver)
    assert transport.requests == []


@pytest.mark.parametrize(
    "location",
    [
        "https://192.168.1.1/admin",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://internal.example.net/secret",  # a public-looking name on a private address
        "http://feeds.example.org/feed.xml",  # a downgrade
        "ftp://feeds.example.org/feed.xml",
        "https://user:pw@feeds.example.org/",
        "https://feeds.example.org:8443/",
        "file:///etc/passwd",
    ],
)
def test_a_redirect_to_a_refused_destination_is_not_followed(location: str) -> None:
    transport = FakeTransport({FEED: redirect(location)})
    resolver = FakeResolver({"internal.example.net": ["10.0.0.5"]})
    with pytest.raises(Blocked):
        fetch(transport, resolver)
    # Only the first hop (and its robots.txt) was ever requested.
    assert transport.content_urls == [FEED]


def test_every_hop_of_a_redirect_chain_is_resolved_and_checked() -> None:
    second = "https://cdn.example.com/feed.xml"
    third = "https://cdn.example.net/final.xml"
    transport = FakeTransport(
        {FEED: redirect(second, 301), second: redirect(third, 307), third: ok("x")}
    )
    resolver = FakeResolver()
    result = fetch(transport, resolver)
    assert result.final_url == third
    assert transport.content_urls == [FEED, second, third]
    for host in ("feeds.example.org", "cdn.example.com", "cdn.example.net"):
        assert host in resolver.lookups


def test_a_name_that_changes_address_between_hops_is_caught() -> None:
    # The first lookup is public; by the redirect the same name answers with a private
    # address. Each connection is checked on its own lookup, so the second is refused.
    answers = iter([[PUBLIC], [PUBLIC], ["192.168.1.10"]])

    class Rebinding(FakeResolver):
        def resolve(self, host: str, port: int) -> list[str]:
            self.lookups.append(host)
            return next(answers)

    transport = FakeTransport({FEED: redirect("/moved.xml")})
    with pytest.raises(Blocked, match="non-public"):
        fetch(transport, Rebinding())
    assert transport.content_urls == [FEED]


def test_a_relative_redirect_stays_on_the_host() -> None:
    moved = "https://feeds.example.org/v2/feed.xml"
    transport = FakeTransport({FEED: redirect("/v2/feed.xml"), moved: ok("x")})
    assert fetch(transport).final_url == moved


def test_the_redirect_limit_is_enforced() -> None:
    transport = FakeTransport({FEED: redirect(FEED)})
    with pytest.raises(TooManyRedirects):
        fetch(transport)
    assert transport.content_urls == [FEED] * (POLICY.max_redirects + 1)


def test_a_redirect_without_a_location_is_an_error() -> None:
    with pytest.raises(FetchError, match="without saying where"):
        fetch(FakeTransport({FEED: HopResponse(status=302)}))


@pytest.mark.parametrize("location", ["https://[broken/path", "https://[::1/x", "//["])
def test_a_redirect_to_an_unparseable_address_is_a_fetch_error(location: str) -> None:
    with pytest.raises(FetchError):
        fetch(FakeTransport({FEED: redirect(location)}))


def test_a_redirect_off_the_allowed_hosts_is_refused() -> None:
    elsewhere = "https://elsewhere.example.com/feed.xml"
    transport = FakeTransport({FEED: redirect(elsewhere)})
    with pytest.raises(Blocked, match="not a host this source may be fetched from"):
        fetch(transport, allowed_hosts=frozenset({"feeds.example.org"}))
    assert transport.content_urls == [FEED]


def test_a_host_outside_the_allowed_hosts_is_never_requested() -> None:
    transport = FakeTransport()
    for hosts in (frozenset({"other.example.org"}), frozenset({"example.org"}), frozenset()):
        with pytest.raises(Blocked):
            fetch(transport, allowed_hosts=hosts)
    assert transport.requests == []


def test_a_response_over_the_size_limit_is_refused() -> None:
    transport = FakeTransport({FEED: ok(b"x" * 101)})
    with pytest.raises(ResponseTooLarge):
        fetch(transport, max_bytes=100)
    assert transport.requests[-1].max_bytes == 100  # the transport is told to stop there
    assert fetch(FakeTransport({FEED: ok(b"x" * 100)}), max_bytes=100).body == b"x" * 100


def test_a_caller_cannot_raise_the_size_limit_above_the_policy() -> None:
    transport = FakeTransport({FEED: ok(b"x")})
    fetch(transport, max_bytes=POLICY.max_response_bytes * 10)
    assert transport.requests[-1].max_bytes == POLICY.max_response_bytes


def test_every_request_carries_the_timeout() -> None:
    transport = FakeTransport({FEED: ok(b"x")})
    fetch(transport)
    assert {r.timeout_seconds for r in transport.requests} == {POLICY.timeout_seconds}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 429, 500, 503])
def test_a_failure_status_is_an_error(status: int) -> None:
    with pytest.raises(HttpStatusError) as raised:
        fetch(FakeTransport({FEED: HopResponse(status=status)}))
    assert raised.value.status == status


def test_a_transport_failure_is_a_fetch_error() -> None:
    with pytest.raises(FetchError, match="timed out"):
        fetch(FakeTransport({FEED: FetchError("timed out")}))


def test_a_conditional_request_sends_the_validators_and_understands_304() -> None:
    transport = FakeTransport({FEED: HopResponse(status=304)})
    result = fetch(transport, etag='"v1"', last_modified="Thu, 19 Nov 2026 11:15:00 GMT")
    assert result.not_modified is True
    assert result.body == b""
    headers = transport.requests[-1].headers
    assert headers["If-None-Match"] == '"v1"'
    assert headers["If-Modified-Since"] == "Thu, 19 Nov 2026 11:15:00 GMT"
    plain = FakeTransport({FEED: ok(b"x")})
    fetch(plain)
    assert "If-None-Match" not in plain.requests[-1].headers


def test_the_client_identifies_itself_generically() -> None:
    transport = FakeTransport({FEED: ok(b"x")})
    fetch(transport)
    for request in transport.requests:
        agent = request.headers["User-Agent"]
        assert agent.startswith("ai-briefing")
        assert "@" not in agent
        assert "sdeery" not in agent.lower()
        assert request.headers.get("Accept-Encoding") == "identity"


# --- Rate limit -------------------------------------------------------------------------------


def test_requests_to_one_host_are_spaced_by_the_rate_limit() -> None:
    other = "https://feeds.example.org/other.xml"
    elsewhere = "https://cdn.example.com/x.xml"
    transport = FakeTransport({FEED: ok(b"x"), other: ok(b"y"), elsewhere: ok(b"z")})
    clock = FakeClock()
    fetcher = make_fetcher(transport, clock=clock)
    fetcher.fetch(FEED, allowed_hosts=ANY, min_seconds_between_requests=10)
    # robots.txt and the feed are two requests to the host, so one wait already happened.
    assert clock.sleeps == [10]
    fetcher.fetch(other, allowed_hosts=ANY, min_seconds_between_requests=10)
    assert clock.sleeps == [10, 10]
    clock.now += 4
    fetcher.fetch(other, allowed_hosts=ANY, min_seconds_between_requests=10)
    assert clock.sleeps == [10, 10, 6]  # only the remainder is waited
    clock.now += 60
    before = len(clock.sleeps)
    fetcher.fetch(other, allowed_hosts=ANY, min_seconds_between_requests=10)
    assert len(clock.sleeps) == before  # long enough has passed
    fetcher.fetch(elsewhere, allowed_hosts=ANY, min_seconds_between_requests=10)
    assert clock.sleeps[before:] == [10]  # a new host: only its own robots.txt spacing


# --- robots.txt -------------------------------------------------------------------------------

ROBOTS = "https://feeds.example.org/robots.txt"


def test_robots_txt_is_respected() -> None:
    rules = "User-agent: *\nDisallow: /private/\nDisallow: /*.atom$\n"
    private = "https://feeds.example.org/private/feed.xml"
    transport = FakeTransport({ROBOTS: ok(rules), FEED: ok(b"x"), private: ok(b"secret")})
    fetcher = make_fetcher(transport)
    assert fetcher.fetch(FEED, allowed_hosts=ANY, min_seconds_between_requests=0).body == b"x"
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetcher.fetch(private, allowed_hosts=ANY, min_seconds_between_requests=0)
    assert private not in transport.urls
    assert transport.urls.count(ROBOTS) == 1  # read once per host


def test_rules_addressed_to_this_client_are_respected() -> None:
    rules = "User-agent: ai-briefing\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    transport = FakeTransport({ROBOTS: ok(rules), FEED: ok(b"x")})
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert FEED not in transport.urls


def test_a_missing_robots_txt_allows_the_fetch() -> None:
    for status in (404, 410):
        transport = FakeTransport({ROBOTS: HopResponse(status=status), FEED: ok(b"x")})
        assert fetch(transport).body == b"x"


@pytest.mark.parametrize(
    "reply",
    [
        HopResponse(status=500),
        HopResponse(status=503),
        HopResponse(status=403),
        HopResponse(status=301, headers={"location": "https://elsewhere.example.com/robots.txt"}),
        FetchError("timed out"),
    ],
)
def test_a_robots_txt_that_cannot_be_read_allows_nothing(reply: HopResponse | Exception) -> None:
    transport = FakeTransport({ROBOTS: reply, FEED: ok(b"x")})
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert FEED not in transport.urls


def test_robots_txt_is_checked_for_a_redirect_target_too() -> None:
    moved = "https://cdn.example.com/blocked/feed.xml"
    transport = FakeTransport(
        {
            FEED: redirect(moved),
            "https://cdn.example.com/robots.txt": ok("User-agent: *\nDisallow: /blocked/\n"),
            moved: ok(b"x"),
        }
    )
    with pytest.raises(Blocked, match=r"robots\.txt"):
        fetch(transport)
    assert moved not in transport.urls


def test_the_policy_object_cannot_be_changed_after_it_is_made() -> None:
    with pytest.raises(AttributeError):
        POLICY.allow_non_public_addresses = True  # type: ignore[misc]
    assert NetworkPolicy().allow_non_public_addresses is False
    assert NetworkPolicy().allowed_schemes == ("https",)
    assert isinstance(HopRequest, type)

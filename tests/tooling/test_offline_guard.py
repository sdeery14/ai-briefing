"""The offline guard must be on, must block the network, and must leave loopback usable."""

from __future__ import annotations

import socket
import urllib.request

import pytest

import offline_guard
from offline_guard import NetworkAccessBlocked

# 192.0.2.0/24 and 2001:db8::/32 are reserved for documentation and never routed, so even
# if the guard were broken these tests could not reach a real host.
UNROUTABLE_V4 = ("192.0.2.1", 9)
UNROUTABLE_V6 = ("2001:db8::1", 9)


def test_guard_is_active() -> None:
    assert offline_guard.is_active()


def test_connect_to_external_ipv4_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(NetworkAccessBlocked, match="tests must not use the network"):
            sock.connect(UNROUTABLE_V4)


def test_connect_to_external_ipv6_is_blocked() -> None:
    if not socket.has_ipv6:
        pytest.skip("no IPv6 support on this machine")
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(NetworkAccessBlocked):
            sock.connect(UNROUTABLE_V6)


def test_connect_ex_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(NetworkAccessBlocked):
            sock.connect_ex(UNROUTABLE_V4)


def test_udp_sendto_is_blocked() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(NetworkAccessBlocked),
    ):
        sock.sendto(b"x", UNROUTABLE_V4)


def test_private_lan_address_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(NetworkAccessBlocked):
            sock.connect(("10.0.0.1", 80))


@pytest.mark.parametrize("name", ["example.com", "api.anthropic.com", "example.invalid"])
def test_name_lookup_is_blocked(name: str) -> None:
    with pytest.raises(NetworkAccessBlocked, match="name lookup"):
        socket.getaddrinfo(name, 443)
    with pytest.raises(NetworkAccessBlocked):
        socket.gethostbyname(name)


def test_create_connection_is_blocked() -> None:
    with pytest.raises(NetworkAccessBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


def test_urllib_request_is_blocked_and_not_wrapped() -> None:
    # urllib turns OSError into URLError. The guard's error must come through as itself.
    with pytest.raises(NetworkAccessBlocked):
        urllib.request.urlopen("https://example.com/", timeout=1)


def test_loopback_connection_still_works() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            accepted, _ = server.accept()
            with accepted:
                client.sendall(b"ping")
                assert accepted.recv(4) == b"ping"


def test_connecting_to_a_closed_local_port_fails_normally() -> None:
    # Needed later for "the job completes with the tracking server unreachable".
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=5)


def test_localhost_name_lookup_still_works() -> None:
    assert socket.getaddrinfo("localhost", 80)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        ("localhost", True),
        ("LOCALHOST.", True),
        (b"127.0.0.1", True),
        ("192.168.0.1", False),
        ("10.0.0.1", False),
        ("169.254.169.254", False),
        ("0.0.0.0", False),  # noqa: S104 - a value under test, not a bind address
        ("example.com", False),
        ("localhost.example.com", False),
        ("127.0.0.1.example.com", False),
        ("", False),
        (None, False),
    ],
)
def test_is_loopback_host(host: object, expected: bool) -> None:
    assert offline_guard.is_loopback_host(host) is expected


def test_uninstall_and_install_round_trip() -> None:
    guarded = socket.getaddrinfo
    offline_guard.uninstall()
    try:
        assert not offline_guard.is_active()
        assert socket.getaddrinfo is not guarded
    finally:
        offline_guard.install()
    assert offline_guard.is_active()
    with pytest.raises(NetworkAccessBlocked):
        socket.getaddrinfo("example.com", 443)


# --- Reverse DNS lookups ---------------------------------------------------------------------

EXTERNAL_ADDRESSES = ["192.0.2.1", "10.0.0.1", "169.254.169.254", "2001:db8::1", "example.com"]


@pytest.mark.parametrize("host", EXTERNAL_ADDRESSES)
def test_gethostbyaddr_of_an_external_address_is_blocked(host: str) -> None:
    with pytest.raises(NetworkAccessBlocked, match="reverse lookup"):
        socket.gethostbyaddr(host)


@pytest.mark.parametrize("address", ["192.0.2.1", "10.0.0.1", "169.254.169.254"])
@pytest.mark.parametrize("flags", [0, socket.NI_NAMEREQD, socket.NI_NUMERICSERV])
def test_getnameinfo_of_an_external_address_is_blocked(address: str, flags: int) -> None:
    with pytest.raises(NetworkAccessBlocked, match="reverse lookup"):
        socket.getnameinfo((address, 80), flags)


def test_getnameinfo_of_an_external_ipv6_address_is_blocked() -> None:
    with pytest.raises(NetworkAccessBlocked):
        socket.getnameinfo(("2001:db8::1", 80, 0, 0), 0)


@pytest.mark.parametrize("sockaddr", [(), None, "192.0.2.1", (None, 80)])
def test_getnameinfo_with_an_unusable_address_is_blocked_not_passed_through(
    sockaddr: object,
) -> None:
    with pytest.raises(NetworkAccessBlocked):
        socket.getnameinfo(sockaddr, 0)  # type: ignore[arg-type]


def test_gethostbyaddr_of_loopback_still_works() -> None:
    name, _aliases, addresses = socket.gethostbyaddr("127.0.0.1")
    assert name
    assert "127.0.0.1" in addresses


def test_getnameinfo_of_loopback_still_works() -> None:
    host, service = socket.getnameinfo(("127.0.0.1", 80), 0)
    assert host
    assert service


@pytest.mark.parametrize("address", ["192.0.2.1", "10.0.0.1", "127.0.0.1"])
def test_numeric_only_getnameinfo_is_allowed_because_it_asks_no_resolver(address: str) -> None:
    flags = socket.NI_NUMERICHOST | socket.NI_NUMERICSERV
    assert socket.getnameinfo((address, 8080), flags) == (address, "8080")


def test_install_and_uninstall_patch_and_restore_the_reverse_lookup_functions() -> None:
    import _socket

    guarded_addr = socket.gethostbyaddr
    guarded_info = socket.getnameinfo
    assert guarded_addr is not _socket.gethostbyaddr
    assert guarded_info is not _socket.getnameinfo
    offline_guard.uninstall()
    try:
        assert socket.gethostbyaddr is _socket.gethostbyaddr
        assert socket.getnameinfo is _socket.getnameinfo
        # Uninstalling twice is harmless.
        offline_guard.uninstall()
        assert socket.gethostbyaddr is _socket.gethostbyaddr
    finally:
        offline_guard.install()
    assert socket.gethostbyaddr is guarded_addr
    assert socket.getnameinfo is guarded_info
    # Installing twice must not capture the guards as the "originals".
    offline_guard.install()
    offline_guard.uninstall()
    try:
        assert socket.gethostbyaddr is _socket.gethostbyaddr
        assert socket.getnameinfo is _socket.getnameinfo
    finally:
        offline_guard.install()
    with pytest.raises(NetworkAccessBlocked):
        socket.gethostbyaddr("192.0.2.1")
    with pytest.raises(NetworkAccessBlocked):
        socket.getnameinfo(("192.0.2.1", 80), 0)

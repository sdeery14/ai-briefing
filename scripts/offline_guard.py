"""pytest plugin: tests may not reach the network.

RFC v0.3 and ADR-007 require the test suite to run offline, with no API key. This plugin
makes an accidental network call fail loudly instead of passing on a developer's machine
and failing (or worse, succeeding) in CI.

For the whole test session it replaces the socket entry points so that:

- connecting, or sending a datagram, to anything other than a loopback address raises
  ``NetworkAccessBlocked``;
- resolving any host name other than ``localhost`` raises ``NetworkAccessBlocked``;
- a reverse lookup (``gethostbyaddr``, ``getnameinfo``) of anything other than a loopback
  address raises ``NetworkAccessBlocked``. ``getnameinfo`` with ``NI_NUMERICHOST`` is
  allowed for any address, because it only formats the number and asks no resolver.

Loopback and Unix-domain sockets stay usable, because tests legitimately start local
servers and connect to closed local ports.

It is a guard against accidents in Python code, not a sandbox: a subprocess, or code that
deliberately restores the original functions, is not stopped.

Loaded by ``tests/conftest.py`` for local runs, and forced with ``-p offline_guard`` in CI.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


class NetworkAccessBlocked(RuntimeError):  # noqa: N818 - reads as a statement of fact
    """A test tried to reach the network.

    Deliberately not an ``OSError``: libraries catch and wrap those, which would hide the
    problem behind a retry or a generic connection error.
    """


_ORIGINALS: dict[str, Any] = {}


def is_loopback_host(host: object) -> bool:
    """True for loopback IP literals and the usual names for this machine."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    text = host.strip().lower().rstrip(".")
    if text in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _address_allowed(sock: socket.socket, address: object) -> bool:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return True  # Unix-domain and other local families
    if isinstance(address, tuple) and address:
        return is_loopback_host(address[0])
    return False


def _refuse(what: str, target: object) -> NetworkAccessBlocked:
    return NetworkAccessBlocked(
        f"{what} {target!r} was blocked: tests must not use the network. "
        "Inject a fake transport or replay a recorded response instead."
    )


def _guarded_connect(self: socket.socket, address: Any) -> Any:
    if not _address_allowed(self, address):
        raise _refuse("connect to", address)
    return _ORIGINALS["connect"](self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> Any:
    if not _address_allowed(self, address):
        raise _refuse("connect to", address)
    return _ORIGINALS["connect_ex"](self, address)


def _guarded_sendto(self: socket.socket, *args: Any) -> Any:
    address = args[-1] if args else None
    if not _address_allowed(self, address):
        raise _refuse("send to", address)
    return _ORIGINALS["sendto"](self, *args)


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if host is not None and not is_loopback_host(host):
        raise _refuse("name lookup for", host)
    return _ORIGINALS["getaddrinfo"](host, *args, **kwargs)


def _guarded_gethostbyname(host: Any) -> Any:
    if not is_loopback_host(host):
        raise _refuse("name lookup for", host)
    return _ORIGINALS["gethostbyname"](host)


def _guarded_gethostbyname_ex(host: Any) -> Any:
    if not is_loopback_host(host):
        raise _refuse("name lookup for", host)
    return _ORIGINALS["gethostbyname_ex"](host)


def _guarded_gethostbyaddr(host: Any) -> Any:
    if not is_loopback_host(host):
        raise _refuse("reverse lookup of", host)
    return _ORIGINALS["gethostbyaddr"](host)


def _guarded_getnameinfo(sockaddr: Any, flags: Any) -> Any:
    host = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else None
    numeric_only = isinstance(flags, int) and bool(flags & socket.NI_NUMERICHOST)
    if not numeric_only and not is_loopback_host(host):
        raise _refuse("reverse lookup of", host)
    return _ORIGINALS["getnameinfo"](sockaddr, flags)


def is_active() -> bool:
    return bool(_ORIGINALS)


def install() -> None:
    if is_active():
        return
    _ORIGINALS.update(
        connect=socket.socket.connect,
        connect_ex=socket.socket.connect_ex,
        sendto=socket.socket.sendto,
        getaddrinfo=socket.getaddrinfo,
        gethostbyname=socket.gethostbyname,
        gethostbyname_ex=socket.gethostbyname_ex,
        gethostbyaddr=socket.gethostbyaddr,
        getnameinfo=socket.getnameinfo,
    )
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
    socket.socket.sendto = _guarded_sendto  # type: ignore[method-assign,assignment]
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.gethostbyname = _guarded_gethostbyname
    socket.gethostbyname_ex = _guarded_gethostbyname_ex
    socket.gethostbyaddr = _guarded_gethostbyaddr
    socket.getnameinfo = _guarded_getnameinfo


def uninstall() -> None:
    if not is_active():
        return
    socket.socket.connect = _ORIGINALS["connect"]  # type: ignore[method-assign]
    socket.socket.connect_ex = _ORIGINALS["connect_ex"]  # type: ignore[method-assign]
    socket.socket.sendto = _ORIGINALS["sendto"]  # type: ignore[method-assign]
    socket.getaddrinfo = _ORIGINALS["getaddrinfo"]
    socket.gethostbyname = _ORIGINALS["gethostbyname"]
    socket.gethostbyname_ex = _ORIGINALS["gethostbyname_ex"]
    socket.gethostbyaddr = _ORIGINALS["gethostbyaddr"]
    socket.getnameinfo = _ORIGINALS["getnameinfo"]
    _ORIGINALS.clear()


def pytest_configure(config: object) -> None:
    install()


def pytest_unconfigure(config: object) -> None:
    uninstall()


def pytest_report_header(config: object) -> str:
    return "offline guard: active (non-loopback network access raises NetworkAccessBlocked)"

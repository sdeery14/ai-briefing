"""One form for a web address, so that two documents pointing at one page can be seen to
(RFC §4 step 2, ADR-003).

The canonical form is used only to compare addresses. A document keeps the address its
source gave, and that is the address a reader is shown.

The rules are deliberately few, and each one removes a difference that never changes
which page is meant:

- the scheme and the host are lower-cased, and a trailing dot on the host is dropped;
- a port that is the scheme's default is dropped;
- the fragment is dropped;
- query parameters that only track where a visitor came from are dropped;
- trailing slashes on the path are dropped.

Nothing else is touched. ``http`` and ``https`` stay different, ``www.`` is kept, the
path's case is kept, and the remaining query parameters keep their order: any of those
can name a different page on some site.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMETERS = frozenset(
    {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid"}
)


def is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAMETERS or lowered.startswith(TRACKING_PREFIXES)


def canonical_url(url: str) -> str | None:
    """The canonical form of a web address, or ``None`` if it is not one."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if scheme not in DEFAULT_PORTS or not host:
        return None
    if ":" in host:  # an IPv6 literal
        host = f"[{host}]"
    if port is not None and port != DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    query = urlencode(
        [
            (name, value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if not is_tracking(name)
        ]
    )
    return urlunsplit((scheme, host, parts.path.rstrip("/"), query, ""))

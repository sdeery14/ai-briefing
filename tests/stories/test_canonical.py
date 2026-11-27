"""One form for a web address (M1 issue 1.9; RFC §4 step 2)."""

from __future__ import annotations

import pytest

from ai_briefing.stories.canonical import canonical_url

PLAIN = "https://example.org/post/one"


@pytest.mark.parametrize(
    "url",
    [
        PLAIN,
        "HTTPS://example.org/post/one",  # scheme case
        "https://EXAMPLE.Org/post/one",  # host case
        "https://example.org./post/one",  # a trailing dot on the host
        "https://example.org:443/post/one",  # the default port
        "https://example.org/post/one/",  # a trailing slash
        "https://example.org/post/one///",
        "https://example.org/post/one#comments",  # a fragment
        "https://example.org/post/one/#top",
        "https://example.org/post/one?utm_source=hn",  # tracking parameters
        "https://example.org/post/one?utm_source=a&utm_medium=b&UTM_Campaign=c",
        "https://example.org/post/one?fbclid=abc&gclid=def&mc_cid=1&mc_eid=2",
        "  https://example.org/post/one  ",
        "HTTPS://Example.ORG:443/post/one/?utm_source=x&fbclid=y#z",  # all at once
    ],
)
def test_differences_that_never_change_the_page_are_removed(url: str) -> None:
    assert canonical_url(url) == PLAIN


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # A parameter that is not tracking is kept, in its place.
        (
            "https://example.org/list?page=2&utm_source=x&sort=new",
            "https://example.org/list?page=2&sort=new",
        ),
        ("https://example.org/search?q=a+b&q=c", "https://example.org/search?q=a+b&q=c"),
        ("https://example.org/?id=7", "https://example.org?id=7"),
        ("https://example.org/", "https://example.org"),
        ("https://example.org", "https://example.org"),
        ("http://example.org:80/a", "http://example.org/a"),
        ("https://example.org:8443/a", "https://example.org:8443/a"),
        ("https://example.org/a?b=", "https://example.org/a?b="),
    ],
)
def test_what_names_the_page_is_kept(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://example.org/a", "http://example.org/a"),  # the scheme
        ("https://example.org/a", "https://www.example.org/a"),  # a www prefix
        ("https://example.org/a", "https://example.org/A"),  # the path's case
        ("https://example.org/a?x=1&y=2", "https://example.org/a?y=2&x=1"),  # parameter order
        ("https://example.org/a?id=1", "https://example.org/a?id=2"),
        ("https://example.org/a", "https://example.org/a/b"),
        ("https://example.org/abs/1234.5678", "https://example.org/abs/1234.5678v2"),
    ],
)
def test_differences_that_may_name_another_page_are_kept(first: str, second: str) -> None:
    assert canonical_url(first) != canonical_url(second)
    assert canonical_url(first) is not None
    assert canonical_url(second) is not None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "/relative/path",
        "//example.org/a",
        "ftp://example.org/a",
        "javascript:alert(1)",
        "mailto:someone@example.org",
        "https://",
        "https:///path",
        "https://example.org:notaport/a",
        "https://[::1",
    ],
)
def test_what_is_not_a_web_address_has_no_canonical_form(url: str) -> None:
    assert canonical_url(url) is None


def test_canonicalising_twice_changes_nothing() -> None:
    once = canonical_url("HTTPS://Example.ORG:443/post/one/?utm_source=x&page=2#z")
    assert once is not None
    assert canonical_url(once) == once

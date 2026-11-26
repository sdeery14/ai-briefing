"""Turning fetched HTML into plain text.

Stored text is what the model reads and what quotations are checked against, so it must
be text: no markup, no scripts, no hidden content. The result is data. Whatever it says,
nothing here or later treats it as an instruction.

For a whole page, the text of the ``<article>`` element is used when there is one, then
``<main>``, then the body. That is a simple rule, not a readability engine; a page with
no such element keeps its navigation text.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

# Content that is never text a reader sees.
SKIPPED = frozenset(
    {"script", "style", "noscript", "template", "svg", "math", "iframe", "object", "embed"}
)
SKIPPED |= {"head", "title", "select", "textarea", "button"}
# Page furniture, dropped when extracting an article from a whole page.
FURNITURE = frozenset({"nav", "header", "footer", "aside", "form"})
BLOCKS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "main", "pre"}
    | {"blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "figure", "figcaption", "hr", "dd", "dt"}
)
VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "base"})
CONTAINERS = ("article", "main", "body")
NO_BREAK_SPACE = chr(0xA0)


class _TextExtractor(HTMLParser):
    def __init__(self, *, drop_furniture: bool) -> None:
        super().__init__(convert_charrefs=True)
        self._drop = SKIPPED | FURNITURE if drop_furniture else SKIPPED
        self._skipping: list[str] = []
        self._open: list[str] = []
        self.parts: dict[str, list[str]] = {"": []}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCKS:
            self._emit("\n")
        if tag in VOID:
            return
        if self._skipping or tag in self._drop:
            self._skipping.append(tag)
            return
        if tag in CONTAINERS and tag not in self._open:
            self.parts.setdefault(tag, [])
        self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._skipping:
            if tag in self._skipping:
                while self._skipping.pop() != tag:
                    pass
            return
        if tag in self._open:
            while self._open.pop() != tag:
                pass
        if tag in BLOCKS:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self._emit(data)

    def _emit(self, text: str) -> None:
        self.parts[""].append(text)
        for container in CONTAINERS:
            if container in self._open:
                self.parts[container].append(text)


def _tidy(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace(NO_BREAK_SPACE, " ")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    """The text of an HTML fragment, such as a feed entry's summary or content."""
    extractor = _TextExtractor(drop_furniture=False)
    extractor.feed(html)
    extractor.close()
    return _tidy("".join(extractor.parts[""]))


def page_to_text(html: str) -> str:
    """The article text of a whole page: ``<article>``, else ``<main>``, else the body."""
    extractor = _TextExtractor(drop_furniture=True)
    extractor.feed(html)
    extractor.close()
    for container in CONTAINERS:
        text = _tidy("".join(extractor.parts.get(container, [])))
        if text:
            return text
    return _tidy("".join(extractor.parts[""]))

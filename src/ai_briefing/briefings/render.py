"""Rendering a stored briefing as Markdown, for reading on its own (ADR-006).

The Markdown is made from the same stored content as the JSON, and from nothing else.
Every piece of text in a briefing came from a source or a model, so all of it is escaped:
it can show markup, but it cannot be markup. A link is written only for a plain ``http``
or ``https`` address, which the briefing took from a stored document.
"""

from __future__ import annotations

import re
from typing import Any

WEB_URL = re.compile(r'^https?://[^\s<>"]+$')
# Characters that Markdown or HTML would act on. Each is written as itself, escaped.
_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~])")


def escape(text: object) -> str:
    """Text that will display as written, in Markdown and in HTML rendered from it."""
    flat = " ".join(str(text).split())
    flat = flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _SPECIAL.sub(r"\\\1", flat)


def link(label: object, url: object) -> str:
    """A Markdown link, or just the escaped label when the address is not a plain web URL."""
    address = str(url)
    if not WEB_URL.fullmatch(address):
        return escape(label)
    safe = address.replace("(", "%28").replace(")", "%29")
    return f"[{escape(label)}](<{safe}>)"


def to_markdown(content: dict[str, Any]) -> str:
    """The briefing as Markdown."""
    lines = [f"# AI Briefing: {escape(content['local_date'])}", ""]
    status = content["status"]
    if status == "empty":
        lines += ["Nothing to report today.", ""]
    for reason in content.get("degraded_reasons", []):
        lines += [f"> Note: {escape(reason)}", ""]
    for story in content.get("stories", []):
        lines += [
            f"## {escape(story['headline'])}",
            "",
            f"*{escape(story['class'])}, {escape(story['confidence'])} confidence, "
            f"{int(story['independent_source_count'])} independent source(s)*",
            "",
            escape(story["summary"]),
            "",
            f"**Why it matters:** {escape(story['why_it_matters'])}",
            "",
            "Sources:",
            "",
        ]
        for evidence in story["evidence"]:
            lines.append(
                f"- {link(evidence['title'], evidence['url'])} "
                f"({escape(evidence['source_name'])}, {escape(evidence['source_role'])})"
            )
        lines.append("")
    if content.get("watchlist"):
        lines += [
            "## Worth watching",
            "",
            "Not yet well supported. Listed, not assessed as news.",
            "",
        ]
        for item in content["watchlist"]:
            lines.append(f"- {link(item['headline'], item['url'])}")
        lines.append("")
    note = content.get("concept_note")
    if note:
        related = next(
            (
                s["headline"]
                for s in content.get("stories", [])
                if s["item_id"] == note["related_item_id"]
            ),
            None,
        )
        lines += [
            f"## Background: {escape(note['title'])}",
            "",
            "*Background written by the model. It is not taken from a source and is not "
            "evidence for anything above.*",
            "",
            escape(note["body"]),
            "",
        ]
        if related:
            lines += [f"Related to: {escape(related)}", ""]
    lines += [
        "---",
        "",
        "A linked source shows where a statement came from. It does not show that the "
        "statement is true.",
        "",
    ]
    return "\n".join(lines)

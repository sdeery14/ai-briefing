"""Versioned prompt files (RFC §3.4). A protected path: a change here changes the product.

A prompt is a file, identified by the hash of its content. There is no table of prompts;
each model call records the identifier and the hash it used, so any assessment can be
traced to the exact wording that produced it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

DIRECTORY = Path(__file__).parent
RUBRIC_VERSION = "v0"
"""The scoring rubric inside ``assessment.md``. Changing an anchor means a new version."""


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    sha256: str


def load(prompt_id: str) -> Prompt:
    """The prompt with this identifier, as committed."""
    if not prompt_id.replace("_", "").isalnum():
        raise ValueError(f"not a prompt identifier: {prompt_id!r}")
    raw = (DIRECTORY / f"{prompt_id}.md").read_text(encoding="utf-8")
    # Line endings are normalised so the hash is the same on every platform.
    text = "\n".join(raw.splitlines()) + "\n"
    return Prompt(prompt_id, text, hashlib.sha256(text.encode("utf-8")).hexdigest())

"""Writing a briefing where a consumer can pick it up (RFC §4 step 12, §8.2; ADR-006).

The export directory holds one current file, ``latest.json``, and an ``archive`` of every
briefing version exported, each under its own briefing id. A consumer reads the current
file and never sees a half-written one: the content goes to a temporary file in the same
directory, which is then renamed over the target in one step.

Nothing is written unless the briefing satisfies the ``daily_briefing.v1`` contract. A
briefing that does not is refused, and the previous current file stays as it was.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_briefing.briefings.contract import contract_validator, load_schema
from ai_briefing.runtime import tracing

LATEST = "latest.json"
ARCHIVE = "archive"
EXPORT_ENV = "AI_BRIEFING_EXPORT_DIR"
DEFAULT_DIRECTORY = "export"
_FILE_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


class ExportError(RuntimeError):
    """The briefing was not exported. Nothing was written."""


@dataclass(frozen=True)
class Exported:
    latest: Path
    archived: Path


def export_directory(explicit: str | os.PathLike[str] | None, database: Path) -> Path:
    """Where exports go: the argument, else ``AI_BRIEFING_EXPORT_DIR``, else an ``export``
    directory beside the database."""
    chosen = explicit or os.environ.get(EXPORT_ENV)
    return Path(chosen) if chosen else database.parent / DEFAULT_DIRECTORY


def export(content: dict[str, Any], directory: Path) -> Exported:
    """Validate a briefing and write it as the current file and as its archive copy.

    Exporting the same briefing again rewrites both files with the same bytes, so there
    is still one current file and one archive file for it.
    """
    schema_version = content.get("schema_version")
    if not isinstance(schema_version, str):
        raise ExportError("the briefing does not say which contract it follows")
    try:
        schema = load_schema(schema_version)
    except (OSError, ValueError) as error:
        raise ExportError(f"there is no contract named {schema_version!r}") from error
    errors = sorted(
        f"{'/'.join(str(p) for p in error.absolute_path) or '(document)'}: {error.message}"
        for error in contract_validator(schema).iter_errors(content)
    )
    if errors:
        raise ExportError("the briefing is not valid: " + "; ".join(errors[:5]))
    briefing_id = str(content["briefing_id"])
    if not _FILE_SAFE.fullmatch(briefing_id):
        raise ExportError("the briefing's id cannot be used as a file name")
    data = (json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    archive = directory / ARCHIVE
    archive.mkdir(parents=True, exist_ok=True)
    archived = archive / f"{briefing_id}.json"
    latest = directory / LATEST
    # The archive first: if the second write fails, the current file is still the
    # previous briefing, whole.
    with tracing.span("export", briefing_id=briefing_id):
        _write_atomically(archived, data)
        _write_atomically(latest, data)
    return Exported(latest=latest, archived=archived)


def _write_atomically(path: Path, data: bytes) -> None:
    """Write beside the target, then rename over it. A reader sees the old file or the
    new one, never part of either."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

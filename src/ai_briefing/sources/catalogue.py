"""Loading the source catalogue, ``config/sources.yaml`` (ADR-003, ADR-010).

Every entry is validated as a :class:`~ai_briefing.domain.records.Source`, which refuses
an unknown mode, kind or model-submission value and any combination of permissions that
does not agree with the mode. A catalogue that does not validate is not partly used: the
load fails.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from ai_briefing.domain.records import Source

SCHEMA = "sources.v1"
CONFIG_ENV = "AI_BRIEFING_CONFIG"


class CatalogueError(ValueError):
    """The catalogue file is missing, malformed, or holds an entry that is not allowed."""


def config_directory() -> Path:
    """``AI_BRIEFING_CONFIG``, else ``config/`` in the source checkout (RFC §3.4)."""
    override = os.environ.get(CONFIG_ENV)
    return Path(override) if override else Path(__file__).resolve().parents[3] / "config"


def load_catalogue(path: str | os.PathLike[str] | None = None) -> tuple[Source, ...]:
    """Every source in the catalogue, enabled or not, in file order."""
    target = Path(path) if path is not None else config_directory() / "sources.yaml"
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise CatalogueError(f"cannot read the source catalogue {target}: {error}") from error
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise CatalogueError(f"{target.name}: expected schema {SCHEMA!r}")
    entries = data.get("sources")
    if not isinstance(entries, list) or not entries:
        raise CatalogueError(f"{target.name}: 'sources' must be a non-empty list")
    sources: list[Source] = []
    for position, entry in enumerate(entries, start=1):
        name = entry.get("id") if isinstance(entry, dict) else None
        try:
            sources.append(Source.model_validate(entry))
        except ValidationError as error:
            raise CatalogueError(
                f"{target.name}: source {name or f'number {position}'} is not valid: {error}"
            ) from error
    ids = [source.id for source in sources]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise CatalogueError(f"{target.name}: duplicate source ids: {', '.join(duplicates)}")
    return tuple(sources)

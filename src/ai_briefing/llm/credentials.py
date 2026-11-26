"""Finding the provider API key without ever showing it (RFC §11).

The key comes from the environment variable named in ``models.yaml``, or else from an env
file kept outside the repository: the path in ``AI_BRIEFING_ENV_FILE``, or
``.config/ai-briefing/.env`` under the user's home directory.

The key is wrapped so that printing it, logging it, or including it in an error shows
nothing. It is unwrapped in exactly one place, where the provider client is built.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ENV_FILE_ENV = "AI_BRIEFING_ENV_FILE"
DEFAULT_ENV_FILE = Path(".config") / "ai-briefing" / ".env"


class MissingApiKey(RuntimeError):  # noqa: N818 - reads as a statement of fact
    """No API key was found. The message names where it was looked for, never a value."""


class ApiKey:
    """A key that does not reveal itself."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """The key itself. Only for handing to the provider client."""
        return self._value

    def __repr__(self) -> str:
        return "ApiKey(***)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ApiKey) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


def env_file_path(environ: Mapping[str, str], home: Path) -> Path:
    override = environ.get(ENV_FILE_ENV)
    return Path(override) if override else home / DEFAULT_ENV_FILE


def read_env_file(path: Path) -> dict[str, str]:
    """``NAME=value`` lines. Blank lines and ``#`` comments are skipped; quotes are removed."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def load_api_key(
    variable: str,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> ApiKey:
    """The key for ``variable``: from the environment if set there, else from the env file."""
    environ = os.environ if environ is None else environ
    value = environ.get(variable, "").strip()
    if value:
        return ApiKey(value)
    path = env_file_path(environ, home or Path.home())
    try:
        value = read_env_file(path).get(variable, "").strip()
    except OSError:
        value = ""
    if not value:
        raise MissingApiKey(f"no API key: set {variable} in the environment, or put it in {path}")
    return ApiKey(value)

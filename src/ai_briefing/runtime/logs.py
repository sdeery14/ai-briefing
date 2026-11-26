"""Structured logs: one JSON object per line (RFC §9.3).

A log line says what happened and how much: a stage, a status, counts, an error's kind.
It never carries source text, model text or a secret. That is enforced here by shape, not
left to each caller: a value may only be a number, a boolean, ``None``, or a short string,
and a string is cut to a fixed length. Nothing longer than a headline can pass through.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TextIO

MAX_STRING = 200
Scalar = str | int | float | bool | None


def _safe(value: object) -> Scalar | dict[str, Scalar]:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Mapping):
        # One level of counts, such as a stage's results. Nothing nested further.
        return {str(key)[:MAX_STRING]: _scalar(item) for key, item in value.items()}
    return _scalar(value)


def _scalar(value: object) -> Scalar:
    if value is None or isinstance(value, bool | int | float):
        return value
    text = " ".join(str(value).split())
    return text if len(text) <= MAX_STRING else text[: MAX_STRING - 1] + "…"


class JsonLog:
    """Writes events as JSON lines. Standard error by default, so standard output stays
    free for a command's own result."""

    def __init__(
        self,
        stream: TextIO | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._stream = stream
        self._clock = clock

    def event(self, event: str, **fields: object) -> None:
        record: dict[str, object] = {
            "ts": self._clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": event,
        }
        for name, value in fields.items():
            record[name] = _safe(value)
        stream = self._stream or sys.stderr
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()

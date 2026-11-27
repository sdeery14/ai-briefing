"""The tracer protocol and its no-op default (ADR-009 point 4, RFC §10.1).

Tracing is optional. Job roots, model calls and the export are wrapped in :func:`span`,
which hands them to whichever tracer is installed. The default does nothing, so every job
runs the same with no tracing at all. A real tracer (MLflow, in a later milestone) is
installed once at start-up with :func:`install`; no job code changes.

Two rules hold for any tracer:

- **A tracer can never fail a job.** Whatever it raises on the way in or out of a span is
  dropped. What the traced work raises is passed on untouched.
- **A span carries identifiers and counts, not content.** Attribute values are short
  scalars: a job's name, a task, a record id. No source text, model text or address.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from typing import Protocol

Attribute = str | int | float | bool
MAX_ATTRIBUTE_CHARS = 100


class Tracer(Protocol):
    """Something that can record a span of work."""

    def span(
        self, name: str, attributes: Mapping[str, Attribute]
    ) -> AbstractContextManager[object]:
        """A context manager entered when the work starts and left when it ends. An error
        in the work reaches its ``__exit__`` in the usual way."""
        ...


class NoopTracer:
    """Records nothing."""

    def span(
        self, name: str, attributes: Mapping[str, Attribute]
    ) -> AbstractContextManager[object]:
        return nullcontext()


_installed: Tracer = NoopTracer()


def install(tracer: Tracer | None) -> None:
    """Use ``tracer`` from now on. ``None`` goes back to the no-op default."""
    global _installed  # one process-wide tracer, set once at start-up
    _installed = tracer if tracer is not None else NoopTracer()


def installed() -> Tracer:
    return _installed


def _bounded(value: Attribute) -> Attribute:
    return value[:MAX_ATTRIBUTE_CHARS] if isinstance(value, str) else value


@contextmanager
def span(name: str, **attributes: Attribute) -> Iterator[None]:
    """Trace the enclosed work with the installed tracer. Never raises on its own account."""
    manager: AbstractContextManager[object] | None
    try:
        manager = _installed.span(name, {k: _bounded(v) for k, v in attributes.items()})
        manager.__enter__()
    except Exception:
        manager = None
    try:
        yield
    except BaseException as error:
        if manager is not None:
            # A tracer's failure is never the job's.
            with suppress(Exception):
                manager.__exit__(type(error), error, error.__traceback__)
        raise
    else:
        if manager is not None:
            with suppress(Exception):
                manager.__exit__(None, None, None)

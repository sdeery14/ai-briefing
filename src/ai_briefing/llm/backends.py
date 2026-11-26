"""The two ways a model request is answered: by the provider, or from a recording.

A backend takes one request and returns one response. It knows nothing about budgets,
schemas or the database; :mod:`ai_briefing.llm.client` does that around it, the same way
for both backends, so tests replaying recordings exercise the real client.

The request has no tools and no sampling parameters. The model is given text and asked
for text in a fixed shape, and that is all it can do (ADR-009).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from ai_briefing.domain.enums import Effort
from ai_briefing.llm.credentials import ApiKey
from ai_briefing.llm.pricing import Usage

REFUSAL = "refusal"
MAX_TOKENS = "max_tokens"


class BackendError(Exception):
    """The provider could not be reached or answered with an error.

    ``error_class`` is a short name for the record. The message never contains request
    text or a credential.
    """

    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    user: str
    output_schema: dict[str, Any]
    max_tokens: int
    effort: Effort

    def canonical(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "system": self.system,
            "user": self.user,
            "output_schema": self.output_schema,
            "max_tokens": self.max_tokens,
            "effort": self.effort.value,
        }

    def digest(self) -> str:
        """A hash of everything that determines the answer. Recordings are found by it."""
        text = json.dumps(self.canonical(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelResponse:
    text: str
    stop_reason: str
    usage: Usage
    refusal_explanation: str | None = None


class Backend(Protocol):
    def create(self, request: ModelRequest) -> ModelResponse:
        """Answer one request. Raises :class:`BackendError`."""


class AnthropicBackend:
    """Calls the Claude API through the official SDK."""

    def __init__(
        self,
        api_key: ApiKey,
        *,
        api_version: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic(
                api_key=api_key.reveal(),
                timeout=timeout_seconds,
                max_retries=max_retries,
                default_headers={"anthropic-version": api_version},
            )
        self._client = client

    def create(self, request: ModelRequest) -> ModelResponse:
        import anthropic

        try:
            message = self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                output_config={
                    "effort": request.effort.value,
                    "format": {"type": "json_schema", "schema": request.output_schema},
                },
            )
        except anthropic.AnthropicError as error:
            # Only the kind of error is kept. The SDK's message can echo the request.
            raise BackendError(type(error).__name__, "the provider call failed") from error
        text = "".join(
            str(getattr(block, "text", ""))
            for block in message.content
            if getattr(block, "type", None) == "text"
        )
        usage = message.usage
        details = getattr(message, "stop_details", None)
        return ModelResponse(
            text=text,
            stop_reason=str(message.stop_reason),
            usage=Usage(
                input_tokens=int(usage.input_tokens or 0),
                output_tokens=int(usage.output_tokens or 0),
                cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                cache_creation_input_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
            ),
            refusal_explanation=getattr(details, "explanation", None) if details else None,
        )


class NoRecording(BackendError):  # noqa: N818 - reads as a statement of fact
    """No recorded response matches the request."""

    def __init__(self, digest: str) -> None:
        super().__init__("NoRecording", f"no recorded response for request {digest[:12]}")


class ReplayBackend:
    """Answers from recorded responses in a directory. Uses no network and no key.

    Each ``*.json`` file holds a ``request`` and the ``response`` to give for it. A
    request is matched by its digest, so a recording answers exactly the request it was
    made for and nothing else. A file may give an ``error_class`` in place of a response,
    to replay a provider failure.
    """

    def __init__(self, directory: Path) -> None:
        self._by_digest: dict[str, dict[str, Any]] = {}
        for path in sorted(directory.glob("*.json")):
            entry = json.loads(path.read_text(encoding="utf-8"))
            request = ModelRequest(
                **{**entry["request"], "effort": Effort(entry["request"]["effort"])}
            )
            digest = request.digest()
            if digest in self._by_digest:
                raise ValueError(f"{path.name} records a request that is already recorded")
            self._by_digest[digest] = entry

    def __len__(self) -> int:
        return len(self._by_digest)

    def create(self, request: ModelRequest) -> ModelResponse:
        entry = self._by_digest.get(request.digest())
        if entry is None:
            raise NoRecording(request.digest())
        if "error_class" in entry:
            raise BackendError(str(entry["error_class"]), "the recorded provider call failed")
        response = entry["response"]
        return ModelResponse(
            text=response["text"],
            stop_reason=response["stop_reason"],
            usage=Usage(**response["usage"]),
            refusal_explanation=response.get("refusal_explanation"),
        )


def recording(request: ModelRequest, response: ModelResponse) -> dict[str, Any]:
    """The JSON form of a recording, for writing a fixture by hand or by a recording run."""
    return {"request": request.canonical(), "response": asdict(response)}

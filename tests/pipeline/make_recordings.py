"""Regenerate the recorded model responses in ``recorded/`` for the synthetic day.

    uv run python tests/pipeline/make_recordings.py

Run this after a deliberate change to a prompt, an output shape or the synthetic day. A
recording answers exactly one request, so such a change makes the old recordings stop
matching, and the replay test fails until they are regenerated and reviewed.

No model is called. The answers come from the same script the other tests use
(``conftest.scripted``); this only writes them down beside the requests they answer.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_briefing.llm.backends import ModelRequest, ModelResponse, recording
from ai_briefing.llm.client import ModelClient
from ai_briefing.llm.config import load_models_config
from ai_briefing.runtime.daily import compose_job
from ai_briefing.storage import database
from pipeline.conftest import (
    CATALOGUE,
    DAY,
    HASH,
    NOW,
    RECORDED,
    FakeTransport,
    run_day,
    scripted,
)

NOTE = "Synthetic. Produced by tests/pipeline/conftest.py scripted(); no model was called."


class Recorder:
    def __init__(self) -> None:
        self.seen: list[tuple[ModelRequest, ModelResponse]] = []

    def create(self, request: ModelRequest) -> ModelResponse:
        response = scripted(request)
        self.seen.append((request, response))
        return response


def main() -> int:
    recorder = Recorder()
    with tempfile.TemporaryDirectory() as folder:
        engine = database.create_database_engine(Path(folder) / "record.sqlite3")
        try:
            database.upgrade(engine)
            config = load_models_config()
            run_day(engine, config, recorder, FakeTransport())
            # Composing asks once whether a story needs a concept explained.
            compose_job(
                engine,
                CATALOGUE,
                local_date=date.fromisoformat(DAY),
                timezone="UTC",
                application_version="0.0.0",
                configuration_hash=HASH,
                client=ModelClient(
                    engine=engine, config=config, backend=recorder, clock=lambda: NOW
                ),
                clock=lambda: NOW,
            )
        finally:
            engine.dispose()
    RECORDED.mkdir(exist_ok=True)
    for old in RECORDED.glob("*.json"):
        old.unlink()
    for number, (request, response) in enumerate(recorder.seen, start=1):
        kind = "screening" if '"items"' in request.user else "assessment"
        if '"recently_explained"' in request.user:
            kind = "concept_note"
        entry = {"_note": NOTE, **recording(request, response)}
        path = RECORDED / f"{number:02d}_{kind}.json"
        path.write_text(
            json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
    sys.stdout.write(f"wrote {len(recorder.seen)} recordings to {RECORDED}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

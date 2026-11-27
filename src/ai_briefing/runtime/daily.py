"""The day's work as one run: collect, screen, fetch, assess, compose (RFC §9.3).

Each stage is a recorded job with the day in its key, so running the day twice adds
nothing. A stage that fails is recorded and logged, and the stages after it still run on
whatever is already in the database: a feed outage should not cost the day's briefing.
The run's result says whether every stage succeeded.

A stage that runs after a failure has not seen the day's full input, so it must not count
as the day's run of that stage. It is recorded under a separate key. When the day is run
again and the failed stage succeeds, the stages after it run properly, under the day's
own key.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from ai_briefing.briefings import concept
from ai_briefing.briefings.compose import Composed, compose, preview_stories
from ai_briefing.domain.enums import BriefingVariant
from ai_briefing.domain.records import Source
from ai_briefing.editorial.process import Settings, assess, fetch_bodies, screen
from ai_briefing.llm.client import ModelClient
from ai_briefing.runtime.logs import JsonLog
from ai_briefing.sources.collect import collect
from ai_briefing.sources.fetcher import Fetcher
from ai_briefing.storage import queries
from ai_briefing.storage.jobs import run_job, utc_now

STAGES = ("collect", "screen", "fetch-bodies", "assess", "briefing")
AFTER_FAILURE = "after-failure"


def briefing_counts(composed: Composed) -> dict[str, int]:
    content = composed.briefing.document()
    stories, watch = content.get("stories"), content.get("watchlist")
    return {
        "stories": len(stories) if isinstance(stories, list) else 0,
        "watchlist": len(watch) if isinstance(watch, list) else 0,
        "version": composed.briefing.version,
    }


def compose_job(
    engine: Engine,
    catalogue: Sequence[Source],
    *,
    local_date: date,
    timezone: str,
    application_version: str,
    configuration_hash: str,
    client: ModelClient | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> Composed:
    """Compose the day's briefing as a recorded job.

    With a model ``client``, the model is asked at most once for the day whether one of
    the selected stories needs a concept explained (RFC §6.4). Without one, no call is
    made; a note already stored for the day is kept either way.

    The job has one record per day and runs every time it is asked: composing stores a
    new version only when the content differs, so a repeat is harmless, and the record
    always shows the latest attempt, its counts, and its failure if it failed.
    """
    made: list[Composed] = []
    notes: list[concept.ConceptNote] = []

    def prepare(job_run_id: int) -> None:
        # Outside the job's transaction: a model call is never made with one open.
        with engine.connect() as connection:
            note = concept.standing(connection, local_date)
            answered, answer = queries.concept_answer(connection, job_run_id)
            ask = note is None and client is not None and not answered
            stories = (
                preview_stories(
                    connection, catalogue, local_date=local_date, timezone=timezone, now=clock()
                )
                if note is None and (ask or answered)
                else []
            )
            recent = queries.recent_concept_keys(
                connection, local_date, concept.REPEAT_DAYS, BriefingVariant.PIPELINE
            )
        if note is None and answered:
            # Answered on an earlier attempt, with no note stored for the day: the answer
            # on record is used as it would have been then. Nothing is asked again.
            note = concept.recover(answer, stories, recent)
        if ask and client is not None:
            try:
                note = concept.propose(client, job_run_id, stories, recent)
            except Exception:
                # The note is optional. Whatever goes wrong in asking for it, the day's
                # briefing is still composed, without one.
                note = None
        if note is not None:
            notes.append(note)

    def work(connection: Connection, _job_run_id: int) -> Mapping[str, int]:
        made.append(
            compose(
                connection,
                catalogue,
                local_date=local_date,
                timezone=timezone,
                configuration_hash=configuration_hash,
                now=clock(),
                concept=notes[0] if notes else None,
            )
        )
        return briefing_counts(made[0])

    run_job(
        engine,
        job="briefing",
        idempotency_key=f"briefing:{local_date.isoformat()}",
        application_version=application_version,
        configuration_hash=configuration_hash,
        prepare=prepare,
        work=work,
        run_again=True,
        clock=clock,
    )
    return made[0]


@dataclass
class DayResult:
    day: str
    stages: dict[str, Mapping[str, int]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)  # stage -> the kind of error
    skipped: list[str] = field(default_factory=list)  # stages that had already run today
    briefing_id: str | None = None
    briefing_status: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failed


def run_day(
    engine: Engine,
    catalogue: Sequence[Source],
    client: ModelClient,
    fetcher: Fetcher,
    *,
    model_id: str,
    local_date: date,
    timezone: str,
    application_version: str,
    configuration_hash: str,
    log: JsonLog,
    clock: Callable[[], datetime] = utc_now,
) -> DayResult:
    """Run every stage for ``local_date``. Never raises for a stage's failure."""
    day = local_date.isoformat()
    result = DayResult(day=day)

    def settings() -> Settings:
        # After a failure, later stages are recorded as partial runs of the day.
        key = f"{day}:{AFTER_FAILURE}" if result.failed else day
        return Settings(
            application_version=application_version,
            configuration_hash=configuration_hash,
            day=key,
        )

    log.event("day.start", day=day, timezone=timezone, version=application_version)

    def stage(name: str, run: Callable[[], tuple[Mapping[str, int], bool]]) -> None:
        log.event("stage.start", day=day, stage=name)
        try:
            counts, ran = run()
        except Exception as error:
            # Recorded and reported; the later stages still run. The message is not
            # logged in full: it can quote what a source or a model sent.
            result.failed[name] = type(error).__name__
            log.event("stage.failed", day=day, stage=name, error_class=type(error).__name__)
            return
        result.stages[name] = dict(counts)
        if not ran:
            result.skipped.append(name)
        log.event("stage.done", day=day, stage=name, ran=ran, counts=counts)

    def collecting() -> tuple[Mapping[str, int], bool]:
        outcome = collect(
            engine,
            catalogue,
            fetcher,
            application_version=application_version,
            configuration_hash=configuration_hash,
            idempotency_key=f"collect:{day}",
            on_failure=lambda source_id, why: log.event(
                "source.failed", day=day, source=source_id, error=why
            ),
            clock=clock,
        )
        return outcome.counts, outcome.ran

    def screening() -> tuple[Mapping[str, int], bool]:
        outcome = screen(engine, catalogue, client, settings(), clock=clock)
        return outcome.counts, outcome.ran

    def fetching() -> tuple[Mapping[str, int], bool]:
        outcome = fetch_bodies(engine, catalogue, fetcher, settings(), clock=clock)
        return outcome.counts, outcome.ran

    def assessing() -> tuple[Mapping[str, int], bool]:
        outcome = assess(engine, catalogue, client, model_id, settings(), clock=clock)
        return outcome.counts, outcome.ran

    def composing() -> tuple[Mapping[str, int], bool]:
        composed = compose_job(
            engine,
            catalogue,
            local_date=local_date,
            timezone=timezone,
            application_version=application_version,
            configuration_hash=configuration_hash,
            client=client,
            clock=clock,
        )
        content = composed.briefing.document()
        result.briefing_id = str(content["briefing_id"])
        result.briefing_status = composed.briefing.status.value
        return briefing_counts(composed), composed.created

    for name, run in zip(
        STAGES, (collecting, screening, fetching, assessing, composing), strict=True
    ):
        stage(name, run)
    log.event(
        "day.done",
        day=day,
        ok=result.ok,
        failed=", ".join(sorted(result.failed)) or None,
        briefing_id=result.briefing_id,
        briefing_status=result.briefing_status,
    )
    return result

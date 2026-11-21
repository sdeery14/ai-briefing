# AI Briefing

An open-source system that follows developments in AI, machine learning, data science and software engineering, works out which ones matter and how well they are supported, and prepares a short, evidence-backed morning briefing.

The guiding idea: **signal over hype, evidence over virality, cumulative learning over random tips.**

## Status

**Pre-development. No application functionality has been implemented, and there is nothing to install or run yet.**

- The architecture was approved on 2026-11-21: [RFC v0.3](docs/rfc/AI-Briefing-RFC-v0.3.md) and eleven accepted [architecture decision records](docs/adr/README.md).
- Work is at milestone M0: licence, contributor and agent instructions, CI and repository safeguards. See the [milestone plan](docs/planning/milestones.md).
- The first working briefing is the goal of milestone M1.

This README will gain installation and usage instructions when there is something that works.

## What it is meant to do

For a data scientist or AI engineer who wants to stay current without reading everything:

- Collect items from a small, curated set of sources through the day.
- Group coverage of the same development into one story.
- Assess each story on its evidence, not its popularity, and say plainly how certain the assessment is.
- Produce a briefing of up to five developments that can be read in about five minutes, with links to the original sources.
- Explain a relevant technical concept alongside the news when that is useful.
- Later, build this into a structured, persistent learning curriculum.

A quiet day should produce a shorter briefing, not invented urgency.

## Planned capabilities

| Milestone | Capability |
|---|---|
| M1 | A daily briefing from real sources on a development machine, compared blind against a simple single-prompt digest |
| M2 | Deployment to a Raspberry Pi, delivery through an existing Home Assistant morning email, a feedback path, backup and restore |
| M3 | Story grouping across sources, independent corroboration, a fuller editorial policy |
| M4 | Evaluation from real use: weekly owner labelling, coverage analysis, measured variability |
| M5 | Wider discovery and targeted research, where measurement shows gaps |
| M6 | A persistent curriculum with prerequisites and progress |

These are plans, not features. Details and exit criteria are in the [milestone plan](docs/planning/milestones.md).

## Architecture in brief

The accepted design, described fully in the [RFC](docs/rfc/AI-Briefing-RFC-v0.3.md):

- **One Python package run as short scheduled jobs.** No long-running service, queue or agent framework.
- **SQLite as the system of record**, with append-only history so every briefing item can be traced to what was read and what was decided.
- **A language model assesses; code decides.** The model extracts claims and quotes its evidence. Code checks that the quotes exist in the stored source and applies the editorial policy. A verified quote shows what a source said, not that the claim is true.
- **One model provider**, with a hard monthly budget enforced before each call.
- **The model has no tools** and never chooses what to fetch.
- **Optional integrations.** Home Assistant can read the briefing from a file and remains responsible for sending email. MLflow tracing is optional and never required for correct operation.
- **Conservative handling of source content.** A source is enabled only after its usage terms are reviewed. See [ADR-010](docs/adr/010-content-rights-and-retention.md) and the [source catalogue](docs/planning/source-catalogue-draft.md).

## Documentation

| Document | Contents |
|---|---|
| [RFC v0.3](docs/rfc/AI-Briefing-RFC-v0.3.md) | Product, architecture, data model, operations, evaluation, security |
| [Architecture decision records](docs/adr/README.md) | The eleven accepted decisions and their reasoning |
| [Milestone plan](docs/planning/milestones.md) | Sequence, issue breakdown and acceptance criteria |
| [Source catalogue](docs/planning/source-catalogue-draft.md) | The approved initial sources and their terms-review status |
| [Reviews](docs/reviews/) | The independent architecture review and how its findings were resolved |

## Contributing

The project is not ready for outside contributions yet. Contributor instructions and the review workflow are being set up in M0. Development follows [ADR-011](docs/adr/011-development-workflow-and-merge-authority.md): changes arrive by pull request and the maintainer merges them.

## Security

Please report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md). Do not open a public issue.

## Licence

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for the copyright notice.

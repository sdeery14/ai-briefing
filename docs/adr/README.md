# AI Briefing architecture decision records

All records are **Proposed**. None is accepted until the owner says so explicitly. A change to an accepted ADR is made by a new ADR that supersedes it.

These records accompany [RFC v0.3](../rfc/AI-Briefing-RFC-v0.3.md). They were revised after the independent review of packet v0.2; see [`docs/reviews/v0.3-reconciliation.md`](../reviews/v0.3-reconciliation.md).

| ADR | Decision | Status | Change in v0.3 |
|---|---|---|---|
| [001](001-modular-monolith.md) | Python modular monolith, independent of Home Assistant | Proposed | Alternatives and acceptance checks added |
| [002](002-persistence.md) | SQLite as the system of record, append-only history | Proposed | New entities; input snapshots; file lock; storage and backup rules |
| [003](003-source-discovery.md) | Curated discovery first; search and research deferred | Proposed | Narrowed; screening tier; grouping mechanism |
| [004](004-editorial-evidence.md) | Evidence records and a deterministic editorial policy | Proposed | Assessment, policy and selection separated; integrity checks |
| [005](005-learning-curriculum.md) | Concept note in V1; persistent curriculum in M6 | Proposed | Curriculum deferred, not dropped |
| [006](006-briefing-consumer.md) | Versioned briefing; file exchange with Home Assistant | Proposed | Full briefing in email; authenticated feedback path |
| [007](007-evaluation-strategy.md) | Deterministic gates and prospective evaluation | Proposed | Rewritten; benchmark reclassified |
| [008](008-pi-operations-and-security.md) | Scheduled container jobs with bounded privileges | Proposed | Host facts; deployment preconditions; backup |
| [009](009-orchestration-and-observability.md) | Plain Python, one provider, narrow observability | Proposed | Tracing narrowed; budget; evaluation moved to 007 |
| [010](010-content-rights-and-retention.md) | Content rights and retention | Proposed | New |
| [011](011-development-workflow-and-merge-authority.md) | Development workflow and merge authority | Proposed | New |

Each record has the same sections: context, decision, alternatives considered, consequences, acceptance checks, revisit when.

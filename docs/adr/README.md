# AI Briefing architecture decision records

Records 001 to 011 were **accepted by the owner on 2026-11-21**. Record 012 was accepted by the owner on 2026-11-23 and record 013 on 2026-11-25. A change to an accepted ADR is made by a new ADR that supersedes or amends it.

These records accompany [RFC v0.3](../rfc/AI-Briefing-RFC-v0.3.md). They were revised after the independent review of packet v0.2; see [`docs/reviews/v0.3-reconciliation.md`](../reviews/v0.3-reconciliation.md).

| ADR | Decision | Status | Change in v0.3 |
|---|---|---|---|
| [001](001-modular-monolith.md) | Python modular monolith, independent of Home Assistant | Accepted | Alternatives and acceptance checks added |
| [002](002-persistence.md) | SQLite as the system of record, append-only history | Accepted | New entities; input snapshots; file lock; storage and backup rules |
| [003](003-source-discovery.md) | Curated discovery first; search and research deferred | Accepted | Narrowed; screening tier; grouping mechanism |
| [004](004-editorial-evidence.md) | Evidence records and a deterministic editorial policy | Accepted | Assessment, policy and selection separated; integrity checks |
| [005](005-learning-curriculum.md) | Concept note in V1; persistent curriculum in M6 | Accepted | Curriculum deferred, not dropped |
| [006](006-briefing-consumer.md) | Versioned briefing; file exchange with Home Assistant | Accepted | Full briefing in email; authenticated feedback path |
| [007](007-evaluation-strategy.md) | Deterministic gates and prospective evaluation | Accepted | Rewritten; benchmark reclassified |
| [008](008-pi-operations-and-security.md) | Scheduled container jobs with bounded privileges | Accepted | Host facts; deployment preconditions; backup |
| [009](009-orchestration-and-observability.md) | Plain Python, one provider, narrow observability | Accepted | Tracing narrowed; budget; evaluation moved to 007 |
| [010](010-content-rights-and-retention.md) | Content rights and retention | Accepted | New |
| [011](011-development-workflow-and-merge-authority.md) | Development workflow and merge authority | Accepted; merge rule amended by 013 | New |
| [013](013-agent-merge-of-eligible-changes.md) | The development round merges eligible changes; amends ADR-011's merge rule | Accepted | Added 2026-11-25, after v0.3 |
| [012](012-private-full-text-reading.md) | Private full-text reading where terms are silent; amends one sentence of ADR-010 | Accepted | Added 2026-11-23, after v0.3 |

Each record has the same sections: context, decision, alternatives considered, consequences, acceptance checks, revisit when.

# ADR 006 — Briefing as a versioned data product; file exchange with Home Assistant

**Status:** Accepted (owner, 2026-11-21)
**Date:** 2026-11-19 (revised for RFC v0.3)

## Context

The Home System already sends a morning email at 07:00 from a custom Home Assistant integration. That integration gathers personal context, makes one model call that writes a short personal note, renders HTML and sends through a transactional email service (verified in the Home System repository, 2026-11-19). Replacing it would couple unrelated domains and risk the existing email.

The owner wants the full intelligence briefing readable in the email, and a way to give feedback from it. The review found that v0.1 had no feedback channel. Email clients and security scanners fetch links automatically, so a link that records feedback on `GET` would record noise.

## Decision

### Outbound

1. The briefing is a versioned JSON document, `daily_briefing.v1`, defined by a JSON Schema in `schemas/` with maximum lengths and counts. Markdown is rendered from the same stored content for standalone use.
2. `status` is `ready`, `degraded` or `empty`. `concept_note` is optional.
3. Export validates, writes a temporary file, and renames it atomically into an export directory. Dated versions are kept.
4. Home Assistant mounts the export directory read-only.

### Consumer rules (implemented in the Home System repository by the owner)

1. Use the file only if it validates, its `local_date` is today, and its status is not `empty`. Otherwise send the existing email unchanged and log a diagnostic.
2. Render the full briefing as its own section after the existing personal content, with links to sources.
3. Render from structured fields with the integration's own escaping; allow only `http` and `https` links.
4. Never include briefing content in the integration's model prompt. The content derives from untrusted web pages and that prompt has personal context.
5. Never read AI Briefing's database or call it.

Home Assistant remains the owner of recipients, personal context, the email and sending, including delivery idempotency. AI Briefing never sends email.

### Inbound feedback

1. The email links to a page served by Home Assistant that requires an authenticated Home Assistant session.
2. A `GET` displays the day's items and changes nothing.
3. Feedback is recorded only when the reader presses a control, which issues an authenticated `POST`.
4. Home Assistant writes one `feedback_event.v1` JSON file per action, atomically, into a feedback directory.
5. AI Briefing mounts that directory read-only and ingests new files on its next run: strict schema validation, size limits, unknown IDs rejected, idempotent on event ID.

There is no unauthenticated state-changing endpoint and no state change on `GET`.

### Contract support

This repository publishes the schemas and valid and invalid fixture files for both contracts, so the consumer can test against them.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Authenticated localhost HTTP API | Needs a long-running service; no benefit on one host |
| A pre-rendered HTML fragment inserted by Home Assistant | Moves the trust boundary; the consumer should escape content itself |
| A short teaser with a link to a full report | The owner wants the briefing in the email; there is nowhere safe to host the full report |
| One-click feedback links (`GET`) | Triggered by scanners and prefetching; unauthenticated |
| Signed-token page with a `POST` confirmation, no login | Viable fallback if login is too awkward; weaker, since anyone holding the email can submit |
| AI Briefing serving its own feedback page | A long-running, exposed service, which V1 excludes |
| Passing the briefing through the email's model call to match its voice | Prompt-injection path into a prompt with personal data; loses citations |

## Consequences

Two small changes are needed in the Home System: reading and rendering the file, and the feedback page. Both are owned and deployed there. The email becomes longer than its original 150-word design; placement is an open question (Q4).

## Acceptance checks

- With the export file missing, invalid, dated yesterday or `empty`, the existing email is sent unchanged.
- Exporting the same briefing twice leaves one current file and no duplicate records.
- A `GET` to the feedback page by an unauthenticated client records nothing; so does a `GET` by an authenticated one.
- An authenticated button press produces one event file and, after ingestion, one `Feedback` row. Re-ingesting the file adds nothing.
- A malformed or oversized event file is rejected and counted, and ingestion continues.
- Briefing text containing HTML is displayed as text in the email.

## Revisit when

A consumer on another host appears, or the feedback page proves unused.

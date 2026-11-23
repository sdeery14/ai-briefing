# Repository safeguards

What the repository's checks do, what the owner still has to configure in GitHub, and how to confirm it works. This implements ADR-011 Phase A, in which the owner merges every pull request.

Nothing in this document is applied automatically. The settings in section 3 are changed by the owner in the GitHub web interface.

## 1. What exists after M0 PR C

| Piece | File | What it does | Status |
|---|---|---|---|
| CI workflow | `.github/workflows/ci.yml` | Three jobs on every pull request and on pushes to `main` | Working |
| Offline guard | `scripts/offline_guard.py` | pytest plugin that makes any non-loopback network access in a test raise an error | Working |
| Merge-eligibility report | `.github/workflows/merge-eligibility.yml`, `scripts/merge_eligibility.py` | Reports whether a pull request touches an ADR-011 protected path | Working once this is on `main` (see section 5) |
| Code owners | `.github/CODEOWNERS` | Names the owner for every protected path | Present; not enforced until a ruleset requires it |
| Ruleset on `main` | GitHub settings | Requires pull requests and passing checks | Configured and tested by the owner |
| Codex review | GitHub and Codex settings | Automatic review of pull requests | Enabled |
| `/round` skill | `.claude/skills/round/`, `scripts/round_*.py`, `scripts/pr_wait.py`, `scripts/review_threads.py` | Works a milestone's owner-authorised issues into labelled pull requests. Has no merge step. | Working; never yet run on a real milestone |

### What the checks cover today

The lint, type and test jobs cover the package in `src/` and the repository's own tooling in `scripts/` and `tests/`. The package is a skeleton (M1 issue 1.1), so the jobs say little about application behaviour yet. The job summaries still describe the earlier, tooling-only scope and are due an update.

| Job (exact check name) | Covers | Does not cover yet |
|---|---|---|
| `Lint and types` | Ruff lint, Ruff format, strict mypy over `scripts/` and `tests/` | Application code |
| `Tests (offline)` | The offline guard's own tests and the merge-eligibility tests, with the guard forced on | Application tests, recorded-response replay |
| `Secret scan` | gitleaks over the full Git history | Secrets outside Git; push-time prevention (see section 3.4) |
| `Merge eligibility (report only)` | Changed files against the protected paths | Enforcement. It is informational in Phase A. |

## 2. How the pieces are kept safe

- **No secrets.** No workflow reads a repository secret. CI needs no API key.
- **Least privilege.** `ci.yml` has `contents: read` only. The eligibility workflow starts from no permissions and grants its one job `contents: read` and `pull-requests: read`.
- **Forks.** `ci.yml` runs on `pull_request`, which gives a fork a read-only token and no secrets.
- **`pull_request_target`.** Only the eligibility workflow uses it, so that the workflow and script come from the base branch and a pull request cannot rewrite the logic that judges it. It checks out one file from the base commit, runs nothing from the pull request, and reads the changed-file list through the API.
- **Pinned inputs.** The one third-party action, `actions/checkout`, is pinned to a commit. `uv` and `gitleaks` are downloaded at fixed versions and verified against SHA-256 checksums. Python dependencies come from `uv.lock`, and CI fails if the lock is out of date.
- **Offline tests.** Dependencies are installed before the tests start. The tests then run with the offline guard forced on from the workflow, so editing `tests/conftest.py` does not switch it off in CI.
- **One list of protected paths.** They are defined in `scripts/merge_eligibility.py`. `CODEOWNERS` is generated from that list, and a test fails if the file, the script or the table in `AGENTS.md` drift apart.
- **Fail closed.** If the changed-file list cannot be read, is empty, or cannot be confirmed complete, the result is "not eligible".

### Known limits

- The offline guard stops accidental network use from Python. It is not a sandbox: a subprocess, or code that deliberately restores the original socket functions, is not stopped. Reviewers should treat any such code in a test as a finding.
- `tests/conftest.py` and the tests of the tooling are not protected paths under ADR-011. A change that weakens them is caught by review, not by the eligibility report.
- Golden files and recorded responses are recognised by directory name: `golden/` and `recorded/` anywhere under `tests/`. A golden file placed elsewhere would not be recognised.
- `CODEOWNERS` assigns ownership only. Nothing requires code-owner review until a ruleset says so, and in Phase A it should not (section 3.2).
- The eligibility report always finishes green in Phase A, whatever it finds. Read its summary, not its colour.

## 3. Settings for the owner to configure

Do these after M0 PR C is merged, so that the check names exist.

### 3.1 Ruleset on `main`

Settings → Rules → Rulesets → New ruleset → New branch ruleset.

| Setting | Value |
|---|---|
| Ruleset name | `main` |
| Enforcement status | Active |
| Bypass list | Empty |
| Target branches | Include default branch |
| Restrict deletions | On |
| Block force pushes | On |
| Require linear history | On |
| Require a pull request before merging | On |
| — Required approvals | 0 |
| — Require review from Code Owners | Off in Phase A (see 3.2) |
| — Require conversation resolution before merging | On |
| — Allowed merge methods | Squash (and Rebase if wanted); not Merge commit |
| Require status checks to pass | On |
| — Require branches to be up to date before merging | On |
| — Status checks | The three names below, source GitHub Actions |

Required status checks, exactly as written:

```text
Lint and types
Tests (offline)
Secret scan
```

Do **not** add `Merge eligibility (report only)` as a required check in Phase A. It is informational, and making it required would let it block your own merges.

### 3.2 Why approvals and code-owner review stay off for now

In Phase A the coding agent works under your GitHub account, so you are the author of its pull requests. GitHub does not let an author approve their own pull request, and you are the only code owner. Requiring an approval or a code-owner review would block every pull request with no one able to unblock it.

The control in Phase A is that you read the pull request and you press merge. Turn on "Require review from Code Owners" as part of Phase B, when a separate agent identity authors the pull requests (ADR-011).

### 3.3 Repository options

| Where | Setting | Value |
|---|---|---|
| Settings → General → Pull Requests | Allow auto-merge | Off |
| Settings → General → Pull Requests | Allow squash merging | On |
| Settings → General → Pull Requests | Allow merge commits | Off |
| Settings → General → Pull Requests | Automatically delete head branches | On (optional) |
| Settings → Actions → General → Workflow permissions | Default permissions | Read repository contents and packages permissions |
| Settings → Actions → General → Workflow permissions | Allow GitHub Actions to create and approve pull requests | Off |
| Settings → Actions → General → Fork pull request workflows | Approval for running workflows | Require approval for all external contributors |

### 3.4 Secret protection

Settings → Advanced Security (or Code security). Turn on **Secret Protection** and **Push protection**. These are GitHub's own scanners and stop many secrets before they reach the repository; the `Secret scan` job is a second check after the fact. Private vulnerability reporting is already on.

### 3.5 Codex review

The steps below are what ProjectBudget's workflow relies on. Menu names in Codex change, so confirm them against the current interface.

1. In Codex settings, connect GitHub if it is not already connected, and give the Codex GitHub app access to `sdeery14/ai-briefing`.
2. In the Codex code-review settings, turn on automatic reviews for this repository.
3. If Codex comments that the repository needs an environment, create one for it in Codex.
4. Codex reads `AGENTS.md`, including its "Code review guidelines" section, from the repository.
5. A review can be requested by hand with a pull request comment: `@codex review`.

Codex's review is not a required status check. Unresolved review threads block merging through "Require conversation resolution".

## 4. Confirm it works

Use throwaway pull requests and close them without merging. An agent can prepare them at your request; you observe the result.

| # | Test | Expected |
|---|---|---|
| 1 | A pull request that adds a failing test | `Tests (offline)` fails; the merge button is blocked |
| 2 | A pull request that only edits a file under `docs/planning/` | All three checks pass; the eligibility summary says "Eligible" |
| 3 | A pull request that changes one line in `AGENTS.md` | Checks pass; the eligibility summary says "Not eligible for automatic merge" and names the file; you can still merge it |
| 4 | A pull request that adds `tests/x/golden/sample.json` | Eligibility summary lists it under `evaluation` |
| 5 | A direct push to `main`, and a force push | Both rejected |
| 6 | A pull request with an unresolved review comment | Merge blocked until resolved |
| 7 | A pull request whose branch is behind `main` | Merge blocked until updated |
| 8 | Any pull request, after Codex is enabled | Codex posts a review; `@codex review` triggers another |
| 9 | A test that calls an external URL, on a pull request | `Tests (offline)` fails with `NetworkAccessBlocked` |

Also check Settings → Code owners (or the `CODEOWNERS` file view) for syntax errors reported by GitHub.

## 5. Things to know

- **The eligibility report does not run on the pull request that introduces it.** A `pull_request_target` workflow is taken from the base branch, and it is not on `main` until M0 PR C merges. Tests 2 to 4 above are its first real runs.
- **Changing the eligibility logic takes two steps to observe**, for the same reason: a pull request that edits the script is judged by the version already on `main`.
- **`uv` version.** CI pins `uv` 0.9.9. Use the same version locally when changing `uv.lock`.
- **Updating a pinned tool** (the checkout action, `uv`, `gitleaks`) means changing a version and its checksum or commit together in `.github/workflows/`. That is a protected-path change.

## 6. Later: Phase B

Not part of this work. Before automatic merging is enabled, ADR-011 requires a separate agent identity, an environment without the owner's credentials, code-owner review turned on, the eligibility check made required and failing when a pull request is not eligible, an author allowlist, and a demonstration with test pull requests. The eligibility script would then need an enforcing mode; today it only reports.

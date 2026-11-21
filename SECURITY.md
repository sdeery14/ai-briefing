# Security policy

AI Briefing reads content from the public internet, sends some of it to a model provider, and is designed to run on a home server next to other services. Security reports are welcome now, while the project is still pre-release.

## Reporting a vulnerability

Please report privately. Do not open a public issue or pull request for a suspected vulnerability.

Use GitHub's private vulnerability reporting: [open a private security advisory](https://github.com/sdeery14/ai-briefing/security/advisories/new). This is the only reporting channel.

Include what you found, how to reproduce it, and what you think the impact is. If the report involves a credential or private data, describe it without pasting it.

## What to expect

- An acknowledgement within 7 days.
- A fix or a decision within 90 days.
- Please allow that time before disclosing publicly. If you need to disclose sooner, say so in the report and we will work out timing with you.
- Credit in the advisory or release notes unless you ask otherwise.
- Good-faith research that avoids privacy violations, data destruction and service disruption will not be met with legal action from this project.

This is a single-maintainer project. The timings are commitments made in good faith, not a service-level agreement.

## Supported versions

There is no release yet, and no application functionality has been implemented.

| Version | Supported |
|---|---|
| `main` branch | Yes. Fixes land here. |
| Released versions | None exist. |

Once the project publishes releases, the latest released minor version will receive security fixes and this table will be updated.

## Scope

In scope:

- Code, configuration, workflows and documentation in this repository.
- Anything that lets fetched content, a feed, a redirect or model output cause an unintended network request, file write, code execution or disclosure of a secret.
- Anything that lets untrusted content reach a reader's email or browser unescaped.
- Weaknesses in the repository's own controls, such as CI workflows or protected paths.

Out of scope:

- The security of third-party services the project talks to (model provider, source websites, GitHub).
- A deployment's own host, network or Home Assistant configuration.

## Security considerations for users and contributors

The design is described in [RFC v0.3](docs/rfc/AI-Briefing-RFC-v0.3.md) §11 and in ADRs [008](docs/adr/008-pi-operations-and-security.md), [010](docs/adr/010-content-rights-and-retention.md) and [011](docs/adr/011-development-workflow-and-merge-authority.md). These are accepted design commitments. They are not yet implemented, because the application does not exist yet.

### API keys and other secrets

- Never commit an API key, token, password or local configuration file. Keys are supplied through the environment at run time.
- Use a provider API key created for AI Briefing alone, with a spending limit set at the provider.
- Secrets must not appear in logs, traces, model prompts, issues, pull requests or test fixtures.
- If you commit a secret by accident, revoke it at the provider first, then report it. Removing it from Git history does not make it safe.

### Source content

- Everything fetched from the internet is treated as untrusted data, never as instructions.
- The model has no tools and never chooses a URL to fetch. Fetching is done by code, only for catalogued sources, under a network policy that refuses private, loopback and link-local addresses, including after redirects.
- Links shown to a reader come only from stored source records, and all source and model text is escaped when rendered.
- Third-party article text is not committed to this repository. Test fixtures are synthetic or carry a licence that permits redistribution.
- A source is enabled only after its usage terms have been reviewed and recorded.

### Private data

- No personal data, private repository contents or private evaluation labels belong in this repository, its issues, its pull requests or its CI.

## Changes to this policy

Changes are made by pull request and reviewed by the maintainer.

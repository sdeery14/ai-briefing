# ADR 008 — Raspberry Pi operations: scheduled container jobs with bounded privileges

**Status:** Accepted (owner, 2026-11-21)
**Date:** 2026-11-19 (revised for RFC v0.3)

## Context

The first host is the Home System Pi, which also runs home automation. Facts below were read from the Home System repository on 2026-11-19. Nothing was changed on the host and nothing was measured on it.

| Fact | Status |
|---|---|
| Raspberry Pi 4B, 8 GB, wired Ethernet | Documented |
| Raspberry Pi OS Lite (Debian Trixie), 64-bit; Docker; systemd | Documented |
| Home Assistant runs as a container with host networking, in a Compose stack with an MQTT broker | Documented |
| MLflow server, PostgreSQL 16 and MinIO run in the same stack | Documented |
| The MLflow server image tag is not pinned | Documented; running version unknown |
| Boot media is microSD; a USB SSD is planned | Not confirmed as installed |
| A camera recorder is planned on this host | Not yet deployed |
| Off-device backup | None found |

Because Home Assistant runs as a container on a general Linux host, a separate container and host timers are available. The review's concern about Home Assistant OS does not apply.

## Decision

### Preconditions for deployment (gate for M2)

Before anything is deployed, the owner records on the host:

1. Operating system, kernel architecture and Docker version as installed.
2. Storage medium, free space and health for the intended data directory.
3. Free memory and CPU load over a normal day with current services.
4. Running MLflow server version, and whether the tracing client in the image can log to it.
5. The off-device backup destination, and a completed restore from it.

Deployment does not proceed if the data directory would be on the boot microSD or if no restore has succeeded.

### Runtime

1. A separate container and Compose project. It is not added to the Home System stack and does not share its database or object store.
2. Host systemd timers start short-lived commands. Timers are persistent, so a run missed during downtime happens at next boot. Times are set in the local time zone.
3. Schedule: collection about every three hours; processing after collection; composition near 06:15; export by 06:30; retries until 06:45. Home Assistant sends at 07:00.
4. Memory and CPU limits on the container. Bounded fetch and model concurrency.
5. One writer, by OS file lock.
6. The image is built for ARM64 in CI. The owner pulls a pinned version by hand. No CI runner on the Pi for this repository and no automatic deployment.

### Storage, backup and recovery

1. SQLite and stored payloads live on reliable persistent storage.
2. A nightly consistent snapshot is copied to a different device. The Pi's own disk and its MinIO instance do not count.
3. A restore is tested before first real use and after any change to the backup method.
4. One failing source does not fail a run. A failed run is repeated safely by the next timer.
5. Degraded briefings follow RFC §7.

### Network and privilege

1. The fetcher refuses private, loopback and link-local destinations after DNS resolution and on each redirect, limits redirects, sizes and time, and rate-limits per host.
2. The container has no Docker socket, no host networking and no Home Assistant credentials.
3. Mounts: its data directory; the export directory (writable; Home Assistant reads it); the feedback directory (read-only; Home Assistant writes it).
4. The only LAN destination the container may reach is the MLflow server, and only when tracing is configured.
5. The model has no tools and cannot cause a network request (ADR-009).

## Alternatives considered

| Alternative | Why not |
|---|---|
| A `uv` virtual environment on the host | Weaker isolation beside Home Assistant; kept as the documented portable install for other users |
| Adding services to the Home System Compose stack | Couples lifecycles and blurs ownership |
| A long-running scheduler process in the container | Idle memory and a second scheduler to supervise |
| Running elsewhere and copying the export over the network | Removes Pi constraints but breaks the same-host file exchange |
| A self-hosted CI runner on the Pi | A public repository must not have a runner with host privileges |

## Consequences

M2 cannot start until the owner has done the host checks and arranged storage and backup. If the camera recorder arrives later, its load is the main threat to headroom; this workload is small and network-bound.

## Acceptance checks

- A request to a private address, directly or by redirect, is refused in tests.
- With the provider or the MLflow server unreachable, the morning job completes and exports a file with the right status.
- A run killed part-way is completed by the next timer with no duplicate rows.
- A restore from the off-device snapshot produces a database that passes `doctor`.
- The container runs within its memory limit over a normal day.

## Revisit when

Host measurements show insufficient headroom, the camera recorder is deployed, or a second host becomes available.

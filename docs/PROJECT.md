# FreshLink project definition

Approved: 2026-11-16. Owner: solo developer. Deadline: <DEADLINE> (November 30 is provisional; exact LMS deadline unverified).

## Problem and users

Live telemetry dashboards can appear connected and active while showing an outdated view. FreshLink helps networking students and telemetry developers understand and investigate information freshness under controlled conditions.

## MVP

An offline local lab sends timestamped simulated rover telemetry over real TCP and UDP sockets, applies clearly labeled seeded impairments, and visualizes ground truth, receiver state, freshness and event traces through a standard-library HTTP/SSE dashboard.

- Use a deterministic moving trajectory and a stationary control, bounded queues, framed TCP, validated sequenced UDP, and loopback defaults.
- Preserve TCP stream bytes in the TCP relay; UDP faults can include loss, delay, duplication, reordering and corruption. A stream relay's delay or discarded bytes are not native TCP packet loss.
- Measure age of information, delivered-update latency, position error, useful update rate, stale-time fraction, and observable queue and fault events; record reproducible conditions and raw data.
- Provide tests, protocol and teach-mode documentation, a reproducible experiment, a concise offline failure-injection demo, and an honest AI usage log.

## Success criteria

- From a clean Windows checkout, the documented demo works offline in at most five minutes, displays real socket activity and a live impairment, and shuts down cleanly.
- TCP framing and UDP validation handle partial or malformed inputs; bounded resources and fault behavior are covered by repeatable standard-library tests, with network tests repeated at least 20 times.
- Repeatable experiments report measured conditions, seeds, N, median, p95, p99 and variance, with limitations and raw data. No result or transport advantage is presumed.
- The owner can explain protocol-critical code and the distinction between application-relay delay and actual TCP segment loss.

## Ordered stretch goals

Only after the MVP is built and tested, and after scope approval:

1. Compare FIFO with latest-unsent-state coalescing under equal budgets.
2. Replay recorded runs with an event inspector.
3. Add a durable annotation channel with acknowledgments and idempotent event IDs.

## Non-goals

Custom reliable UDP is an alternative project and is out of scope unless the owner explicitly changes scope. No real rover control, campus probing, public deployment, full multiplayer game, video conferencing, cloud dependency, runtime LLM, QUIC implementation, or unsupported claims about native TCP packet loss.

## Assignment mapping

| Professor's requirement | FreshLink feature |
| --- | --- |
| Use TCP and/or UDP in the backend | Python standard-library TCP and UDP telemetry paths. |
| Demonstrate protocol behavior in a real application | Interactive telemetry dashboard with ground truth, observed state, impairments, and measured freshness. |
| Use agentic AI during development | Documented agent-assisted design, implementation, review, tests, mistakes, and owner review in AI_LOG.md. |

## Schedule

- Transport core by November 20, 2026.
- MVP by November 23; experiments by November 26.
- Documentation, clean-checkout verification, and rehearsal before <DEADLINE>. November 30 is a provisional planning date, not a verified submission timestamp.

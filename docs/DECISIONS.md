# Decisions

## 2026-11-16: FreshLink scope

- Decision: build the telemetry freshness lab defined in PROJECT.md as a solo MVP.
- Alternatives: reliable transport over UDP and a resilient collaborative whiteboard.
- Reason: a controlled and visual investigation of stale information balances networking depth, practical teaching value, and a two-week solo schedule. Owner approved this scope and excluded custom reliable UDP unless explicitly reconsidered.

## 2026-11-16: Honest impairment boundaries

- Decision: preserve TCP stream bytes in the user-space relay, label stream delay and queueing as application-level effects, and separately inject UDP datagram faults.
- Alternative: discard bytes read by a TCP relay and call it TCP packet loss.
- Reason: the latter does not emulate loss below TCP or establish native retransmission behavior. Packet-level native TCP loss experiments are not prerequisites for the MVP.

## 2026-11-16: Local, reproducible demo

- Decision: use Python standard-library sockets and HTTP/SSE, a vanilla JavaScript dashboard, loopback defaults, seeded conditions, bounded queues, and measured results.
- Alternatives: cloud services, third-party networking frameworks, or live external networks.
- Reason: the demo should run offline on Windows and Linux, remain inspectable, and avoid probing networks not controlled by the owner.

## 2026-11-16: Deadline assumption

- Decision: plan around November 30, with transport core by November 20, MVP by November 23 and experiments by November 26.
- Alternative: treat November 30 as the confirmed due date.
- Reason: the email says 14 days from November 16 but gives no explicit submission time; <DEADLINE> remains unverified.

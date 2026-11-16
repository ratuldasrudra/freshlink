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

## 2026-11-16 · Shared telemetry packet and bounded I/O

- Decision — encode the same versioned snapshot on both transports and add a bounded length prefix on TCP. Keep the ACK field reserved and zero.
- Alternatives — newline-delimited text on TCP or separate message formats for each path.
- Reason — shared packet bytes support fair comparison, and fixed network-order fields simplify validation and byte accounting.

## 2026-11-16 · UDP freshness policy

- Decision — track one sender and one latest snapshot per run; use modulo sequence comparison and reject decreasing generation times.
- Alternatives — restore order with a jitter buffer or retry missing positions.
- Reason — a new complete snapshot can replace an old one immediately. The policy preserves receiver freshness with constant memory and keeps retransmission outside the approved scope.

## 2026-11-16 · Bounded relay scheduling

- Decision — schedule releases by eligibility time and pace them by application bytes. TCP clamps eligibility to preserve FIFO and pauses frame intake when the queue is full. UDP lets eligible datagrams pass delayed ones and drops new copies when capacity is exhausted.
- Alternatives — sleep for each incoming frame before reading the next one, or use privileged packet interception.
- Reason — separating intake from release lets delay and bandwidth be configured independently. The relay works on loopback with standard-library sockets and ordinary user privileges.

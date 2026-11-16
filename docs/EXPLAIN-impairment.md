# Understanding the impairment relay

The sender and receiver use real loopback sockets. The relay owns a bounded queue of application frames or UDP datagrams. For each input, a per-run random generator chooses jitter and applicable UDP faults. A min-heap releases eligible items, and the byte rate sets the earliest next release based on the preceding item's size. The first eligible item can leave immediately. TCP accounting includes its length prefix. UDP accounting counts datagram payload bytes.

TCP clamps each frame's eligibility to the preceding frame's time and uses an insertion counter to break ties. A full queue pauses intake and may eventually apply backpressure through the socket buffers. EOF or idle between frames stops intake and drains the queue. The relay uses two TCP connections with application-level emulated delays. It does not drop TCP segments or trigger a native TCP retransmission.

UDP first draws for loss, then jitter, extra reordering delay, corruption, and duplication. A lost input ends processing for that datagram. A duplicate copies the post-corruption bytes. Later eligible datagrams can pass a delayed one. Queue overflow discards incoming copies, and UDP idle stops intake while released packets finish draining. Timing and overflow can vary with operating system scheduling even when random decisions repeat for the same input sequence. The relay rate is an application-byte pacing limit and excludes IP and transport headers.

The invariants are bounded queue occupancy, byte-for-byte FIFO forwarding of complete TCP frames on normal completion, and a separate timed release for each admitted UDP copy. TCP frame or send failures end the run. The relay makes no end-to-end delivery guarantee.

In one Windows loopback CLI run, the sender emitted 12 UDP samples at 50 samples per second. The relay used seed 17, 5 ms of jitter, loss 0.25, duplication 0.3, corruption 0.3, and extra delay of 120 ms with probability 0.5. This excerpt shows the relay's one-based input numbers:

```text
udp corruption input=1
udp duplicate input=1
released input=1 depth=1
released input=1 depth=0
udp loss input=2
udp reorder delay input=3
released input=6 depth=4
released input=7 depth=4
released input=3 depth=3
```

Input 2 had no release event. Inputs 6 and 7 passed delayed input 3, so arriving later did not make input 3 useful to the freshness receiver. That run accepted three snapshots. This is a trace of one run, with no timing or delivery-rate guarantee.

| Viva question | Answer |
| --- | --- |
| What does the seed control? | It controls random draws for a given input order. It does not control kernel arrival times, timer precision, or queue occupancy. |
| How can UDP reorder? | An earlier datagram can receive extra delay. A later one with earlier eligibility can then leave first. |
| Why clamp TCP eligibility? | Independent jitter could otherwise put a following frame ahead of an earlier one. Preserving order keeps the original stream intact. |
| Why can the relay not show how TCP recovers from segment loss? | The sender's TCP connection already delivered bytes to the relay. The relay sends them over a separate TCP connection. |
| What does the rate option count? | Bytes released by the application, including the TCP frame prefix or the UDP payload. Wire overhead and OS buffering are outside this budget. |

| What if | Expected behavior |
| --- | --- |
| The TCP queue fills? | Intake pauses until there is room. The relay retains every already-admitted frame in order. |
| A UDP datagram is both corrupted and duplicated? | Both copies carry the same flipped bit and fail receiver validation. |
| The input goes idle with a delayed UDP datagram still queued? | The relay stops accepting input and finishes releasing admitted datagrams. |

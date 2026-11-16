# Understanding the wire format and receiver

`protocol.py` turns a sample into bytes. The header says how to interpret them and where the body ends. The receiver checks packet bounds, header, body length, and CRC before using coordinates or decoding the label. `transport.py` supplies the packet boundaries on TCP and checks whether UDP snapshots advance the display.

On TCP, the prefix and body have one shared deadline. A slow peer cannot prolong receipt of an individual frame indefinitely by sending occasional bytes. After a partial failure, the next byte has no known meaning, so the caller closes the connection. UDP already has a datagram boundary. The extra receive byte lets Linux distinguish an oversized datagram with a valid prefix, while Windows may report an oversized datagram as `WSAEMSGSIZE`.

The protocol maintains three invariants. Each decoded packet is complete and validated. The UDP receiver keeps only one accepted snapshot from one peer. Its sequence advances under modular comparison and its generation time cannot go backwards.

The following is an excerpt from the Windows loopback test `test_seeded_loss_duplication_reordering_and_corruption` with seed 17. The test skipped the loss case before sending, held a sample back, and injected duplicate and corrupt datagrams through a real socket.

```text
UDP accepted seq=2
fixture seed=17 dropped seq=3 before send
UDP gap before seq=4 skipped=1
UDP accepted seq=4
fixture held seq=5 until after seq=7
UDP gap before seq=6 skipped=1
UDP accepted seq=6
UDP accepted seq=7
UDP duplicate seq=7
UDP stale or ambiguous seq=5
fixture injected corrupt seq=8
UDP rejected: checksum mismatch
```

| Viva question | Answer |
| --- | --- |
| Why prefix the TCP packet length? | TCP can split or combine sends. The length tells the receiver where each application packet ends. |
| Why does a UTF-8 character split across reads work? | Reads collect bytes and decoding starts only after the entire validated body is available. |
| How does sequence zero follow the largest sequence? | Subtract the old sequence and reduce modulo 2³². The forward distance is one. |
| Why can a gap coexist with a later arrival? | The gap describes the sequences skipped when a newer snapshot was accepted. A delayed packet can arrive afterwards. |
| What does CRC-32 protect? | It detects many accidental changes to the header and body. A sender capable of forging the packet can also compute its CRC. |

| What if | Expected behavior |
| --- | --- |
| The TCP peer closes in the middle of a prefix or body? | The receiver raises a protocol error and closes the stream. |
| The latest UDP sample is lost and the source stops? | The receiver keeps the last accepted state. Its information age continues increasing. |
| A second UDP sender sends an otherwise valid sample? | Once a peer is selected, packets from other addresses are rejected for that run. |

# FreshLink demonstration

From the repository root, run `python -m src.freshlink.server --open`. The dashboard opens at `http://127.0.0.1:8000/`. Use `--port 8001` if port 8000 is occupied. Stop the server with Ctrl+C.

## Three-to-five-minute script

1. **Healthy (45 seconds).** Show the ground-truth rover and both receiver positions. Explain that information age measures time since the latest accepted snapshot was generated. Expand the metrics and point out the 500 ms stale threshold.
2. **Queue overload (60 seconds).** Choose Queue overload. Watch the TCP age, source queue counters, and the rover positions. The relay applies a user-space byte-rate cap and delay. Compare both paths without promising a predetermined result.
3. **UDP loss (45 seconds).** Choose UDP loss. The emulated UDP loss counter rises and the UDP receiver may skip sequences. Each preset starts a fresh counter window.
4. **Outage and recovery (60 seconds).** Select Outage and observe both paths become stale. Select Healthy and watch the receivers recover. Reset counters manually and explain that the current position and age are retained.
5. **Discussion (30 seconds).** TCP is an ordered byte stream. The relay pauses its application traffic, so this demo does not show loss of TCP segments or kernel retransmissions. UDP loss is emulated by dropping datagrams in the relay. Loopback, operating-system scheduling, and timer granularity limit the conclusions.

The age chart caps values at 1,000 ms and keeps the 500 ms threshold visible. The last 20 seconds remain on the chart across counter resets. Latency percentiles use up to 4,096 delivered updates since the latest reset. Time stale starts when the receiver has a known sample.

If the browser does not open, visit the printed URL manually. If the chosen port is occupied, restart with `--port 8001`. If telemetry stops, restart the command and use the standalone TCP and UDP relay commands in the README as a fallback.

## Optional Wireshark filters

Capture only loopback traffic and only when it is your own. The dashboard chooses ephemeral transport ports, which are not displayed yet. For the standalone examples with relay port 8766 and receiver port 8765, capture filter: `tcp port 8766 or tcp port 8765 or udp port 8766 or udp port 8765`. Display filter: `tcp.port == 8766 || tcp.port == 8765 || udp.port == 8766 || udp.port == 8765`. The relay uses separate TCP connections, and captures must not be committed.

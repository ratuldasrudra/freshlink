# FreshLink

FreshLink is an offline telemetry freshness lab for exploring TCP, UDP, and stale information. See [the project scope](docs/PROJECT.md) and [the wire protocol](docs/PROTOCOL.md).

The transport demo requires Python 3.11 or later. From the repository root, start the receiver in one PowerShell or Linux terminal, then start the sender in another:

```text
python -m src.freshlink receive tcp --timeout 30 --debug
python -m src.freshlink send tcp --debug
```

Use `udp` in both commands to try datagrams. The TCP receiver exits at EOF and the UDP receiver exits after idle timeout or Ctrl+C. For a shorter UDP demo, start the receiver with `--timeout 5` and send within five seconds.

Both commands default to IPv4 loopback `127.0.0.1`, port `8765`, and a three-second socket timeout. The sender defaults to 20 samples at 10 samples per second and accepts a maximum rate of 100 per second. Change these with `--host`, `--port`, `--timeout`, `--count`, and `--rate`. The receiver can bind port zero and prints the selected port.

Run the tests with `python -m unittest discover -s tests -v`.

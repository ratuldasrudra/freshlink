"""Exercise the live source, socket relays, metrics, and SSE together."""

import asyncio
import http.client
import json
import threading
import time
import unittest

from src.freshlink.live import LiveTelemetry
from src.freshlink.server import DashboardServer

HEALTHY = {"delay_ms": 0, "jitter_ms": 0, "bytes_per_second": 0, "loss": 0,
           "duplicate": 0, "reorder": 0, "reorder_ms": 0, "corrupt": 0, "outage": False}


class LiveTests(unittest.TestCase):
    def test_blocked_tcp_sender_preserves_udp_cadence(self) -> None:
        from unittest.mock import patch
        from src.freshlink.live import RATE, SENDER_QUEUE_SIZE
        from src.freshlink.metrics import ReceiverMetrics

        delivered = []
        blocked = threading.Event()
        completed = threading.Event()
        original = ReceiverMetrics.accept

        async def stall(*args) -> None:
            blocked.set()
            await asyncio.Future()

        def record(metrics, sample, now_ns) -> None:
            original(metrics, sample, now_ns)
            delivered.append((sample.sequence, now_ns))
            if len(delivered) == SENDER_QUEUE_SIZE * 2:
                completed.set()

        live = LiveTelemetry()
        with patch.object(live, "_send_tcp", side_effect=stall), patch.object(ReceiverMetrics, "accept", record):
            try:
                live.start()
                self.assertTrue(blocked.wait(2))
                self.assertTrue(completed.wait(6), live.snapshot())
                snapshot = live.snapshot()
            finally:
                live.stop()
        expected = 1 / RATE
        times = [received for _, received in delivered[:SENDER_QUEUE_SIZE * 2]]
        self.assertAlmostEqual((times[-1] - times[0]) / (len(times) - 1) / 1e9, expected, delta=0.035)
        self.assertEqual([sequence for sequence, _ in delivered], list(range(len(delivered))))
        self.assertGreater(snapshot["tcp"]["source_queue_dropped"], 0)
        self.assertGreater(snapshot["tcp"]["source_queue_delayed"], 0)
        self.assertEqual(snapshot["udp"]["source_queue_dropped"], 0)

    def test_real_paths_feed_http_events_and_shutdown(self) -> None:
        live = LiveTelemetry()
        server = None
        thread = None
        try:
            live.start()
            server = DashboardServer(0, live.snapshot)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/events")
            response = connection.getresponse()
            deadline = time.monotonic() + 3
            while True:
                line = response.readline()
                if line.startswith(b"data: "):
                    state = json.loads(line[6:])
                    if state["tcp"]["accepted"] and state["udp"]["accepted"]:
                        break
                if time.monotonic() >= deadline:
                    self.fail(f"both socket paths did not produce snapshots: {state}")
            self.assertIsNone(state["error"])
            self.assertGreaterEqual(state["tcp"]["age_ms"], 0)
            self.assertGreaterEqual(state["udp"]["age_ms"], 0)
            connection.close()
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(3)
            live.stop()
        self.assertFalse(live.thread.is_alive())

    def test_control_endpoint_validates_and_changes_live_relay(self) -> None:
        live = LiveTelemetry()
        server = None
        thread = None
        try:
            live.start()
            server = DashboardServer(0, live.snapshot, live.control)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

            def post(settings: dict, origin: str | None = None) -> int:
                headers = {"Content-Type": "application/json"}
                if origin:
                    headers["Origin"] = origin
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    connection.request("POST", "/control", json.dumps(settings), headers)
                    response = connection.getresponse()
                    response.read()
                    return response.status
                finally:
                    connection.close()

            self.assertEqual(post({**HEALTHY, "loss": 2}), 400)
            self.assertEqual(post({**HEALTHY, "loss": True}), 400)
            self.assertEqual(post(HEALTHY, "http://example.com"), 403)
            self.assertEqual(post({**HEALTHY, "outage": True}), 204)
            # Packets already sent before the control request may still be in flight.
            threading.Event().wait(0.3)
            first = live.snapshot()
            threading.Event().wait(0.4)
            second = live.snapshot()
            self.assertEqual(first["tcp"]["accepted"], second["tcp"]["accepted"])
            self.assertEqual(first["udp"]["accepted"], second["udp"]["accepted"])
            self.assertEqual(post(HEALTHY), 204)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                result = live.snapshot()
                if (result["tcp"]["accepted"] > second["tcp"]["accepted"]
                        and result["udp"]["accepted"] > second["udp"]["accepted"]):
                    break
                threading.Event().wait(0.02)
            else:
                self.fail(f"telemetry did not recover after outage: {result}")
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(3)
            live.stop()

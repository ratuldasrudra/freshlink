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
        from unittest.mock import patch

        gate = None
        receive = live._tcp_receive

        async def gated_receive(sock) -> None:
            nonlocal gate
            gate = asyncio.Event()
            await gate.wait()
            await receive(sock)

        def wait_for(predicate, label: str) -> dict:
            deadline = time.monotonic() + 3
            while True:
                state = live.snapshot()
                if predicate(state):
                    return state
                if state["error"] or time.monotonic() >= deadline:
                    self.fail(f"{label}: {state!r}")
                threading.Event().wait(0.01)

        server = None
        thread = None
        receiver_patch = patch.object(live, "_tcp_receive", side_effect=gated_receive)
        receiver_patch.start()
        self.addCleanup(receiver_patch.stop)
        try:
            live.start()
            server = DashboardServer(0, live.snapshot, live.control, live.reset)
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
            wait_for(lambda state: state["tcp"]["relay_released"] > 0 and gate is not None,
                     "TCP must have released data before outage")
            self.assertEqual(post({**HEALTHY, "outage": True}), 204)
            paused = live.snapshot()
            self.assertEqual(paused["tcp"]["accepted"], 0, paused)
            live.loop.call_soon_threadsafe(gate.set)
            second = wait_for(lambda state: state["tcp"]["accepted"] > 0
                              and state["udp"]["relay_loss"] >= paused["udp"]["relay_loss"] + 2,
                              "in-flight TCP should arrive and newly admitted UDP should drop")
            self.assertEqual(second["tcp"]["relay_released"], paused["tcp"]["relay_released"], second)
            self.assertEqual(post(HEALTHY), 204)
            wait_for(lambda state: state["tcp"]["accepted"] > second["tcp"]["accepted"]
                     and state["udp"]["accepted"] > second["udp"]["accepted"],
                     "telemetry did not recover")
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request("POST", "/reset", "{}", {"Content-Type": "application/json"})
                self.assertEqual(connection.getresponse().status, 204)
            finally:
                connection.close()
            reset = live.snapshot()
            self.assertLess(reset["counter_window_seconds"], 1)
            self.assertLess(reset["udp"]["relay_loss"], 2)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(3)
            live.stop()

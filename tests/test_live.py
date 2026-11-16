"""Exercise the live source, socket relays, metrics, and SSE together."""

import http.client
import json
import threading
import time
import unittest

from src.freshlink.live import LiveTelemetry
from src.freshlink.server import DashboardServer


class LiveTests(unittest.TestCase):
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

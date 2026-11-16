"""Exercise HTTP routing and the live SSE response on loopback."""

import http.client
import json
import threading
import unittest

from src.freshlink.server import DashboardServer


class ServerTests(unittest.TestCase):
    def test_sse_snapshot_and_missing_route(self) -> None:
        server = DashboardServer(0, lambda: {"sequence": 7})
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request("GET", "/events")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
            self.assertEqual(json.loads(response.readline().decode().removeprefix("data: ")), {"sequence": 7})
            connection.close()
            other = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            other.request("GET", "/missing")
            self.assertEqual(other.getresponse().status, 404)
            other.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

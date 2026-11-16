"""Loopback HTTP and Server-Sent Events server for dashboard snapshots."""

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
EVENT_INTERVAL_SECONDS = 0.25
SOCKET_TIMEOUT_SECONDS = 3
MAX_CLIENTS = 16
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8")}


class DashboardServer(ThreadingHTTPServer):
    """Serve static dashboard files and current snapshots on loopback."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port: int, snapshot: Callable[[], dict]) -> None:
        self.snapshot = snapshot
        self.clients = threading.BoundedSemaphore(MAX_CLIENTS)
        super().__init__(("127.0.0.1", port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    """Handle static content and a bounded stream of current snapshots."""

    server: DashboardServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)

    def do_GET(self) -> None:
        """Serve the allowlisted dashboard assets or an SSE connection."""
        if self.path == "/events":
            self._events()
            return
        asset = STATIC_FILES.get(self.path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content = (WEB_ROOT / asset[0]).read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", asset[1])
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _events(self) -> None:
        if not self.server.clients.acquire(blocking=False):
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                data = json.dumps(self.server.snapshot(), allow_nan=False, separators=(",", ":"))
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
                threading.Event().wait(EVENT_INTERVAL_SECONDS)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            self.server.clients.release()

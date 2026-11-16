"""Guard telemetry shutdown with a killable subprocess and thread diagnostics."""

import subprocess
import sys
import unittest

PROBE = """
import faulthandler
import logging
import time
from src.freshlink.live import LiveTelemetry

logging.basicConfig(level=logging.INFO)
faulthandler.dump_traceback_later(8, repeat=True)
for attempt in range(3):
    live = LiveTelemetry()
    live.start()
    try:
        deadline = time.monotonic() + 2
        while True:
            state = live.snapshot()
            if all(state[path]['accepted'] for path in ('tcp', 'udp')):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(state)
            time.sleep(0.01)
    finally:
        logging.info('Stopping active telemetry, cycle %d', attempt + 1)
        live.stop()
        assert not live.thread.is_alive()
faulthandler.cancel_dump_traceback_later()
"""


class ShutdownTests(unittest.TestCase):
    def test_active_telemetry_shuts_down_before_hard_timeout(self) -> None:
        try:
            result = subprocess.run(
                [sys.executable, "-u", "-c", PROBE],
                capture_output=True, text=True, timeout=12,
            )
        except subprocess.TimeoutExpired as error:
            self.fail(f"Telemetry subprocess exceeded 12 seconds: {error.stderr!r}")
        self.assertEqual(result.returncode, 0, result.stderr)

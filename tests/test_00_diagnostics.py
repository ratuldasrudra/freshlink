"""Emit thread stacks when a CI test run hangs."""

import faulthandler
import os

if os.environ.get("CI"):
    faulthandler.enable()
    faulthandler.dump_traceback_later(20, repeat=True)

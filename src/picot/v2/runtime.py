"""PicoT v2 live bootstrap runtime.

Runs the canonical pipeline once at startup, publishes the nine passive validation
cards, then remains idle. No planner polling, optimisation or control is present
in v2.0.0-dev.1.
"""

from __future__ import annotations

import json
import os
import time
from time import perf_counter

from picot.v2.diagnostics_placeholder import unused  # type: ignore[import-not-found]

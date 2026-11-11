"""Runs the headless jsdom smoke test for the dashboard's app.js (see
tests/frontend/render_smoke.test.js) as part of the normal test suite.

That test drives the real boot() sequence against synthetic API responses
and fails on any uncaught exception or ".render-error" card -- the signal
that would have caught the renderEfficiencyTrendChart null-innerHTML bug
before it shipped.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).parent / "frontend"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
@pytest.mark.skipif(
    not (FRONTEND_DIR / "node_modules" / "jsdom").exists(),
    reason="jsdom not installed -- run `npm install` in tests/frontend first",
)
def test_dashboard_render_smoke():
    result = subprocess.run(
        ["node", "render_smoke.test.js"],
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

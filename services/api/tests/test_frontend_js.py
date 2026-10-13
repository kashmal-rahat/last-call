"""Pytest wrapper executing node --test for frontend ES modules (Step 11)."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_frontend_node_tests():
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    test_dir = Path(__file__).parent / "js"
    test_files = sorted(test_dir.glob("*.test.mjs"))
    assert len(test_files) >= 2, f"Expected at least 2 JS test files in {test_dir}"

    cmd = ["node", "--test", *[str(p) for p in test_files]]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Frontend node tests failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


"""Shared fixture builders for the treescope test suite.

Every fixture uses a fixed top-level directory name (``demo``) so that
golden output snapshots can be written as exact string literals regardless of
where the temp directory actually lives.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FIXTURE = "demo"

# contents: path (relative to the fixture root) -> byte count
DEMO_CONTENTS = {
    "aaa_dir/note.txt": 200,
    "bbb_dir/sub/deep.txt": 300,
    "aaa.txt": 100,
    "bbb.txt": 50,
    "zzz.log": 10,
}


class TempDir:
    """Context manager owning a scratch directory."""

    def __init__(self) -> None:
        self.base: Path

    def __enter__(self) -> Path:
        self.base = Path(tempfile.mkdtemp(prefix="treescope-test-"))
        return self.base

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


def make_demo(base: Path) -> Path:
    """Create the canonical 'demo' tree used by the golden snapshots."""
    root = base / FIXTURE
    for rel, size in DEMO_CONTENTS.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return root


def make_ignore(base: Path) -> Path:
    root = base / FIXTURE
    contents = {
        "src/main.py": 120,
        "src/mod.py": 80,
        "build/out.o": 500,
        "build/deep/nested.o": 100,
        "data/raw.bin": 40,
        "data.txt": 30,
        "README.md": 60,
        "notes.log": 20,
        "keep.log": 25,
        "a1.txt": 5,
        "ab.txt": 6,
        "a.txt": 4,
        "cache.tmp": 7,
        ".git/config": 8,
        ".git/HEAD": 9,
        "sub/filtered.txt": 10,
        "sub/stay.txt": 11,
    }
    for rel, size in contents.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return root


def make_mtime(base: Path) -> Path:
    root = base / FIXTURE
    contents = {"b.txt": 10, "a.txt": 20, "c/deep.txt": 15, "crunch.txt": 9999}
    for rel, size in contents.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    # mtimes, newest first: a.txt (20) > b.txt (10) > c/ (5) > crunch.txt (1)
    mtimes = {
        "b.txt": 10.0,
        "a.txt": 20.0,
        "c": 5.0,
        "c/deep.txt": 2.0,
        "crunch.txt": 1.0,
        "": 15.0,  # the fixture root itself
    }
    for rel, mtime in mtimes.items():
        target = root if rel == "" else root / rel
        os.utime(target, times=(mtime, mtime))
    return root


def run_cli(*args: str, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess:
    """Run the CLI in a subprocess, the way `python -m treescope` would."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "treescope", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
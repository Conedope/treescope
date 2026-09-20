"""End-to-end tests for treescope.cli, run through real subprocesses.

The CLI is invoked the same way a user would before installing:
``python -m treescope``.  Exit codes and stdout/stderr are asserted exactly.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from helpers import (
    PROJECT_ROOT,
    make_demo,
    make_ignore,
    run_cli,
)

DEMO_TREE_ASCII = "\n".join([
    "demo",
    "|-- aaa_dir",
    "|   `-- note.txt",
    "|-- bbb_dir",
    "|   `-- sub",
    "|       `-- deep.txt",
    "|-- aaa.txt",
    "|-- bbb.txt",
    "`-- zzz.log",
])

DEMO_TREE_SIZES = "\n".join([
    "demo [DIR]           (660 B)",
    "|-- aaa_dir [DIR]    (200 B)",
    "|   `-- note.txt     (200 B)",
    "|-- bbb_dir [DIR]    (300 B)",
    "|   `-- sub [DIR]    (300 B)",
    "|       `-- deep.txt (300 B)",
    "|-- aaa.txt          (100 B)",
    "|-- bbb.txt           (50 B)",
    "`-- zzz.log           (10 B)",
])


class CliSubprocessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="treescope-cli-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.demo = make_demo(self.base)

    def test_help_exits_zero(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: treescope", result.stdout)
        self.assertIn("--sizes", result.stdout)

    def test_version_exits_zero(self) -> None:
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "treescope 1.0.0")

    def test_missing_directory_exits_two(self) -> None:
        missing = self.base / "does-not-exist"
        result = run_cli(str(missing))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("no such file or directory", result.stderr)

    def test_file_argument_exits_two(self) -> None:
        some_file = self.demo / "aaa.txt"
        result = run_cli(str(some_file))
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a directory", result.stderr)

    def test_negative_depth_is_usage_error(self) -> None:
        result = run_cli("--depth", "-1", str(self.demo))
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be >= 0", result.stderr)

    def test_basic_tree_and_summary(self) -> None:
        result = run_cli(str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, DEMO_TREE_ASCII + "\n3 directories, 5 files\n")
        self.assertEqual(result.stderr, "")

    def test_default_directory_is_dot(self) -> None:
        result = run_cli(cwd=self.demo)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], ".")
        self.assertEqual(lines[-1], "3 directories, 5 files")

    def test_sizes_output(self) -> None:
        result = run_cli("--sizes", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, DEMO_TREE_SIZES + "\n3 directories, 5 files\n")

    def test_unicode_output(self) -> None:
        result = run_cli("--unicode", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = DEMO_TREE_ASCII.replace("|--", "\u251c\u2500\u2500") \
                                 .replace("`--", "\u2514\u2500\u2500") \
                                 .replace("|   ", "\u2502   ")
        self.assertEqual(result.stdout, expected + "\n3 directories, 5 files\n")

    def test_ascii_flag_is_default(self) -> None:
        plain = run_cli(str(self.demo))
        ascii_result = run_cli("--ascii", str(self.demo))
        self.assertEqual(plain.stdout, ascii_result.stdout)

    def test_dirs_only(self) -> None:
        result = run_cli("--dirs-only", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = "\n".join([
            "demo",
            "|-- aaa_dir",
            "`-- bbb_dir",
            "    `-- sub",
        ])
        self.assertEqual(result.stdout, expected + "\n3 directories, 0 files\n")

    def test_level_limit(self) -> None:
        for flag in ("--depth", "-L", "--level"):
            result = run_cli(flag, "1", str(self.demo))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "\n".join([
                    "demo",
                    "|-- aaa_dir",
                    "|-- bbb_dir",
                    "|-- aaa.txt",
                    "|-- bbb.txt",
                    "`-- zzz.log",
                ]) + "\n2 directories, 3 files\n",
                f"with {flag}",
            )

    def test_json_output_is_valid_and_shaped(self) -> None:
        result = run_cli("--json", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["name"], "demo")
        self.assertEqual(payload["type"], "dir")
        self.assertEqual(payload["size"], 660)
        children = {c["name"]: c for c in payload["children"]}
        self.assertEqual(children["aaa_dir"]["size"], 200)
        self.assertEqual(children["zzz.log"]["type"], "file")
        self.assertNotIn("directories", result.stdout)

    def test_json_respects_dirs_only(self) -> None:
        result = run_cli("--json", "--dirs-only", str(self.demo))
        payload = json.loads(result.stdout)
        children = {c["name"]: c for c in payload["children"]}
        self.assertEqual(set(children), {"aaa_dir", "bbb_dir"})

    def test_ignore_comma_list(self) -> None:
        result = run_cli("--ignore", "*.log,aaa.txt", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("aaa.txt", result.stdout)
        self.assertNotIn("zzz.log", result.stdout)
        self.assertEqual(
            result.stdout,
            "\n".join([
                "demo",
                "|-- aaa_dir",
                "|   `-- note.txt",
                "|-- bbb_dir",
                "|   `-- sub",
                "|       `-- deep.txt",
                "`-- bbb.txt",
            ]) + "\n3 directories, 3 files\n",
        )

    def test_ignore_repeatable(self) -> None:
        result = run_cli("--ignore", "*.txt", "--ignore", "*.log", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "\n".join([
                "demo",
                "|-- aaa_dir",
                "`-- bbb_dir",
                "    `-- sub",
            ]) + "\n3 directories, 0 files\n",
        )

    def test_ignore_file_resolved_relative_to_dir(self) -> None:
        (self.demo / ".gitignore").write_text("aaa.txt\nzzz.log\n")
        result = run_cli("--ignore-file", ".gitignore", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("aaa.txt", result.stdout)
        self.assertNotIn("zzz.log", result.stdout)
        self.assertIn("bbb.txt", result.stdout)

    def test_ignore_file_falls_back_to_current_directory(self) -> None:
        # DIR has no such file, so the relative path must resolve to cwd
        scratch = self.base / "cwd"
        scratch.mkdir()
        (scratch / "ignores.txt").write_text("zzz.log\n")
        result = run_cli("--ignore-file", "ignores.txt", str(self.demo), cwd=scratch)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("zzz.log", result.stdout)
        self.assertIn("aaa.txt", result.stdout)

    def test_missing_ignore_file_warns_but_succeeds(self) -> None:
        result = run_cli("--ignore-file", "nope.gitignore", str(self.demo))
        self.assertEqual(result.returncode, 0)
        self.assertIn("ignore file 'nope.gitignore' not found", result.stderr)
        self.assertIn("3 directories, 5 files", result.stdout)

    def test_sort_size(self) -> None:
        result = run_cli("--sort", "size", "--sizes", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = "\n".join([
            "demo [DIR]           (660 B)",
            "|-- bbb_dir [DIR]    (300 B)",
            "|   `-- sub [DIR]    (300 B)",
            "|       `-- deep.txt (300 B)",
            "|-- aaa_dir [DIR]    (200 B)",
            "|   `-- note.txt     (200 B)",
            "|-- aaa.txt          (100 B)",
            "|-- bbb.txt           (50 B)",
            "`-- zzz.log           (10 B)",
        ])
        self.assertEqual(result.stdout, expected + "\n3 directories, 5 files\n")

    def test_sort_mtime(self) -> None:
        result = run_cli("--sort", "mtime", str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_sort_is_usage_error(self) -> None:
        result = run_cli("--sort", "bogus", str(self.demo))
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_git_dir_always_hidden(self) -> None:
        (self.demo / ".git").mkdir()
        (self.demo / ".git" / "config").write_text("x")
        result = run_cli(str(self.demo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(".git", result.stdout)


class CliWarningTest(unittest.TestCase):
    """CLI-level handling can't be done as root via chmod, so we patch
    ``os.scandir`` and confirm warnings reach stderr without failing."""

    def test_unreadable_subdir_warns_and_continues(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="treescope-warn-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        demo = make_demo(base)
        blocked = demo / "aaa_dir"

        import treescope.cli as cli

        real_scandir = os.scandir

        def fake_scandir(path):
            if os.fspath(path) == os.fspath(blocked):
                raise PermissionError(13, "Permission denied", os.fspath(path))
            return real_scandir(path)

        stderr = StringIO()
        stdout = StringIO()
        with mock.patch("treescope.core.os.scandir", new=fake_scandir), \
             mock.patch("sys.stderr", stderr), mock.patch("sys.stdout", stdout):
            code = cli.main(["--sizes", str(demo)])
        self.assertEqual(code, 0)
        self.assertIn("cannot read directory", stderr.getvalue())
        self.assertIn("|-- aaa_dir [DIR]", stdout.getvalue())
        self.assertTrue(stderr.getvalue())

    def test_returns_zero_when_warn_called(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="treescope-warn2-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        demo = make_demo(base)

        import treescope.cli as cli

        with mock.patch("sys.stdout", new=StringIO()), \
             mock.patch("sys.stderr", new=StringIO()):
            code = cli.main([str(demo)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
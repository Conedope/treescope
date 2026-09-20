"""Unit tests for treescope.core: collection, sizes, ignore patterns,
sorting, rendering (exact golden snapshots), JSON shape, and summary counts.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import treescope.core as core
from treescope.core import (
    Node,
    Options,
    apply_ignore,
    collect_tree,
    counts,
    dir_size,
    filter_dirs,
    format_size,
    render,
    sort_node,
    sort_tree,
    tree_to_dict,
)

from helpers import make_demo, make_ignore, make_mtime


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="treescope-test-"))


def _full(tree_root: Path) -> Node:
    tree = collect_tree(tree_root, Options())
    dir_size(tree)
    return tree


class CollectTreeTest(unittest.TestCase):
    def test_dirs_first_then_files_each_sorted(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            self.assertEqual(
                [c.name for c in tree.children],
                ["aaa_dir", "bbb_dir", "aaa.txt", "bbb.txt", "zzz.log"],
            )
            self.assertEqual(
                [c.name for c in tree.children[1].children],
                ["sub"],
            )
            self.assertEqual(
                [c.name for c in tree.children[1].children[0].children],
                ["deep.txt"],
            )
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_file_sizes_read_at_collect_dirs_aggregate(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            by_name = {c.name: c for c in tree.children}
            self.assertEqual(by_name["aaa.txt"].size, 100)
            self.assertEqual(by_name["zzz.log"].size, 10)
            self.assertEqual(by_name["aaa_dir"].size, 200)
            self.assertEqual(by_name["bbb_dir"].size, 300)
            self.assertEqual(tree.size, 660)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_root_display_name_defaults_to_dot(self) -> None:
        root = make_demo(_tmp())
        cwd = Path.cwd()
        try:
            os.chdir(root)
            try:
                self.assertEqual(_full(Path(".")).name, ".")
            finally:
                os.chdir(cwd)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class DepthLimitTest(unittest.TestCase):
    def test_depth_one_does_not_expand_children(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = collect_tree(root, Options(depth=1))
            self.assertEqual(tree.children[0].children, [])
            self.assertEqual(tree.size, 0)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_depth_zero_lists_root_only(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = collect_tree(root, Options(depth=0))
            self.assertEqual(tree.children, [])
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class UnreadableDirectoryTest(unittest.TestCase):
    def test_unreadable_subdir_warns_and_is_listed_empty(self) -> None:
        root = make_demo(_tmp())
        try:
            blocked = root / "aaa_dir"
            warnings: list = []
            real_scandir = os.scandir

            def fake_scandir(path):
                if os.fspath(path) == os.fspath(blocked):
                    raise PermissionError(13, "Permission denied", os.fspath(path))
                return real_scandir(path)

            with mock.patch("treescope.core.os.scandir", new=fake_scandir):
                tree = collect_tree(root, Options(warn=warnings.append))
            dir_size(tree)
            children = {c.name: c for c in tree.children}
            self.assertTrue(children["aaa_dir"].is_dir)
            self.assertEqual(children["aaa_dir"].children, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("cannot read directory", warnings[0])
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class DirSizeTest(unittest.TestCase):
    def test_aggregation_math_and_caching(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = collect_tree(root, Options())
            by_name = {c.name: c for c in tree.children}
            self.assertEqual(by_name["aaa_dir"].size, 0)
            self.assertEqual(dir_size(tree), 660)
            self.assertEqual(tree.size, 660)
            self.assertEqual(by_name["aaa_dir"].size, 200)
            self.assertEqual(by_name["aaa_dir"].children[0].size, 200)
            self.assertEqual(by_name["bbb_dir"].children[0].size, 300)
            self.assertEqual(dir_size(tree), 660)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_size_survives_dirs_only_pruning(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            filter_dirs(tree)
            fresh = _full(root)
            self.assertEqual(tree.size, 660)
            self.assertEqual(tree.size, fresh.size)
            self.assertEqual(
                {c.name: c.size for c in tree.children},
                {c.name: c.size for c in fresh.children if c.is_dir},
            )
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class FormatSizeTest(unittest.TestCase):
    def test_values(self) -> None:
        cases = {
            0: "0 B",
            1: "1 B",
            1023: "1023 B",
            1024: "1.0 KB",
            1536: "1.5 KB",
            15360: "15.0 KB",
            1048576: "1.0 MB",
            1073741824: "1.0 GB",
            1099511627776: "1.0 TB",
        }
        for amount, expected in cases.items():
            self.assertEqual(format_size(amount), expected, f"for {amount}")


class SortNodeTest(unittest.TestCase):
    def test_name_mode_dirs_first(self) -> None:
        children = [
            Node("file.txt", Path("file.txt"), False),
            Node("dir", Path("dir"), True),
            Node("apple.txt", Path("apple.txt"), False),
        ]
        self.assertEqual([c.name for c in sort_node(children, "name")],
                         ["dir", "apple.txt", "file.txt"])

    def test_size_mode_descending(self) -> None:
        children = [
            Node("small.txt", Path("small.txt"), False, size=3),
            Node("big", Path("big"), True, size=900),
            Node("mid.txt", Path("mid.txt"), False, size=50),
        ]
        self.assertEqual([c.name for c in sort_node(children, "size")],
                         ["big", "mid.txt", "small.txt"])

    def test_mtime_mode_descending_via_os_stat(self) -> None:
        root = _tmp()
        try:
            children = []
            for name, is_dir, content in (("b.txt", False, b"x"),
                                          ("a.txt", False, b"y"),
                                          ("c", True, None)):
                parent = root / name
                if is_dir:
                    parent.mkdir()
                else:
                    parent.write_bytes(content or b"")
                children.append(Node(name, parent, is_dir))
            os.utime(root / "a.txt", times=(20, 20))
            os.utime(root / "b.txt", times=(10, 10))
            os.utime(root / "c", times=(5, 5))
            self.assertEqual([c.name for c in sort_node(children, "mtime")],
                             ["a.txt", "b.txt", "c"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class GoldenPlainRenderTest(unittest.TestCase):
    def test_demo_ascii(self) -> None:
        root = make_demo(_tmp())
        try:
            expected = "\n".join([
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
            self.assertEqual(render(_full(root), Options(ascii=True)), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_demo_unicode(self) -> None:
        root = make_demo(_tmp())
        try:
            expected = "\n".join([
                "demo",
                "\u251c\u2500\u2500 aaa_dir",
                "\u2502   \u2514\u2500\u2500 note.txt",
                "\u251c\u2500\u2500 bbb_dir",
                "\u2502   \u2514\u2500\u2500 sub",
                "\u2502       \u2514\u2500\u2500 deep.txt",
                "\u251c\u2500\u2500 aaa.txt",
                "\u251c\u2500\u2500 bbb.txt",
                "\u2514\u2500\u2500 zzz.log",
            ])
            self.assertEqual(render(_full(root), Options(ascii=False)), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_depth_limit_ascii(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = collect_tree(root, Options(depth=1))
            expected = "\n".join([
                "demo",
                "|-- aaa_dir",
                "|-- bbb_dir",
                "|-- aaa.txt",
                "|-- bbb.txt",
                "`-- zzz.log",
            ])
            self.assertEqual(render(tree, Options()), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class GoldenSizesRenderTest(unittest.TestCase):
    def test_demo_sizes(self) -> None:
        root = make_demo(_tmp())
        try:
            expected = "\n".join([
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
            self.assertEqual(render(_full(root), Options(sizes=True)), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_demo_sizes_unicode(self) -> None:
        root = make_demo(_tmp())
        try:
            expected = "\n".join([
                "demo [DIR]           (660 B)",
                "\u251c\u2500\u2500 aaa_dir [DIR]    (200 B)",
                "\u2502   \u2514\u2500\u2500 note.txt     (200 B)",
                "\u251c\u2500\u2500 bbb_dir [DIR]    (300 B)",
                "\u2502   \u2514\u2500\u2500 sub [DIR]    (300 B)",
                "\u2502       \u2514\u2500\u2500 deep.txt (300 B)",
                "\u251c\u2500\u2500 aaa.txt          (100 B)",
                "\u251c\u2500\u2500 bbb.txt           (50 B)",
                "\u2514\u2500\u2500 zzz.log           (10 B)",
            ])
            self.assertEqual(
                render(_full(root), Options(sizes=True, ascii=False)), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class DirsOnlyTest(unittest.TestCase):
    def test_dirs_only_plain(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            filter_dirs(tree)
            expected = "\n".join([
                "demo",
                "|-- aaa_dir",
                "`-- bbb_dir",
                "    `-- sub",
            ])
            self.assertEqual(render(tree, Options()), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_dirs_only_with_sizes_keeps_aggregates(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            filter_dirs(tree)
            expected = "\n".join([
                "demo [DIR]        (660 B)",
                "|-- aaa_dir [DIR] (200 B)",
                "`-- bbb_dir [DIR] (300 B)",
                "    `-- sub [DIR] (300 B)",
            ])
            self.assertEqual(render(tree, Options(sizes=True)), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class SortTreeRenderTest(unittest.TestCase):
    def test_size_sort_renders_descending(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            sort_tree(tree, Options(sort="size"))
            expected = "\n".join([
                "demo",
                "|-- bbb_dir",
                "|   `-- sub",
                "|       `-- deep.txt",
                "|-- aaa_dir",
                "|   `-- note.txt",
                "|-- aaa.txt",
                "|-- bbb.txt",
                "`-- zzz.log",
            ])
            self.assertEqual(render(tree, Options()), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_mtime_sort_renders_descending(self) -> None:
        root = make_mtime(_tmp())
        try:
            tree = _full(root)
            sort_tree(tree, Options(sort="mtime"))
            expected = "\n".join([
                "demo",
                "|-- a.txt",
                "|-- b.txt",
                "|-- c",
                "|   `-- deep.txt",
                "`-- crunch.txt",
            ])
            self.assertEqual(render(tree, Options()), expected)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class IgnoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = _tmp()
        self.root = make_ignore(self.base)

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def _tree(self, patterns) -> Node:
        tree = collect_tree(self.root, Options())
        dir_size(tree)
        apply_ignore(tree, patterns, Options())
        return tree

    def _names(self, tree: Node) -> list:
        return sorted(c.name for c in tree.children)

    def _dirs(self, tree: Node) -> list:
        return sorted(c.name for c in tree.children if c.is_dir)

    def _files(self, tree: Node) -> list:
        return sorted(c.name for c in tree.children if not c.is_dir)

    def test_basename_glob_removes_matches(self) -> None:
        names = self._names(self._tree(["*.log"]))
        self.assertNotIn("notes.log", names)
        self.assertNotIn("keep.log", names)
        self.assertIn("README.md", names)

    def test_negation_reincludes(self) -> None:
        names = self._names(self._tree(["*.log", "!keep.log"]))
        self.assertNotIn("notes.log", names)
        self.assertIn("keep.log", names)

    def test_trailing_slash_matches_dirs_only(self) -> None:
        # pattern "data/" must NOT touch the file data.txt, only the directory
        tree = self._tree(["data/"])
        self.assertNotIn("data", self._dirs(tree))
        self.assertIn("data.txt", self._files(tree))
        # a non-dir-only pattern removes both the dir and the data.txt file
        tree2 = self._tree(["data*"])
        self.assertNotIn("data", self._dirs(tree2))
        self.assertNotIn("data.txt", self._files(tree2))

    def test_ignored_dir_not_descended(self) -> None:
        tree = self._tree(["build"])
        self.assertNotIn("build", self._dirs(tree))
        self.assertIn("src", self._dirs(tree))
        # src keeps its own children intact
        src = {c.name: c for c in tree.children}["src"]
        self.assertEqual(sorted(c.name for c in src.children), ["main.py", "mod.py"])

    def test_dir_only_slash_removes_directory(self) -> None:
        tree = self._tree(["src/"])
        self.assertNotIn("src", self._dirs(tree))
        self.assertIn("build", self._dirs(tree))

    def test_pattern_with_slash_matches_relative_path(self) -> None:
        tree = self._tree(["build/deep/nested.o"])
        build = {c.name: c for c in tree.children}["build"]
        deep = {c.name: c for c in build.children}["deep"]
        self.assertEqual([c.name for c in deep.children], [])

    def test_pattern_without_slash_matches_basename_any_depth(self) -> None:
        tree = self._tree(["out.o"])
        build = {c.name: c for c in tree.children}["build"]
        self.assertEqual(sorted(c.name for c in build.children), ["deep"])

    def test_question_mark_single_char(self) -> None:
        names = self._names(self._tree(["a?.txt"]))
        self.assertNotIn("a1.txt", names)
        self.assertNotIn("ab.txt", names)
        self.assertIn("a.txt", names)

    def test_character_class_matches(self) -> None:
        names = self._names(self._tree(["a[0-9].txt"]))
        self.assertNotIn("a1.txt", names)
        self.assertIn("ab.txt", names)
        self.assertIn("a.txt", names)

    def test_comment_and_blank_lines_ignored(self) -> None:
        names = self._names(self._tree(["# a comment", "", "*.tmp"]))
        self.assertNotIn("cache.tmp", names)
        self.assertIn("notes.log", names)

    def test_git_always_ignored_and_not_reincludable(self) -> None:
        self.assertNotIn(".git", self._names(self._tree([])))
        self.assertNotIn(".git", self._names(self._tree(["!.git"])))

    def test_multiple_patterns_compose(self) -> None:
        names = self._names(self._tree(["*.log", "*.tmp", "README.md"]))
        self.assertEqual(names, [
            "a.txt", "a1.txt", "ab.txt", "build", "data", "data.txt", "src", "sub",
        ])


class FilterDirsTest(unittest.TestCase):
    def test_filter_removes_files_recursively(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            filter_dirs(tree)
            stack = [tree]
            while stack:
                node = stack.pop()
                for child in node.children:
                    self.assertTrue(child.is_dir)
                    stack.append(child)
            self.assertEqual([c.name for c in tree.children], ["aaa_dir", "bbb_dir"])
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class JsonTreeTest(unittest.TestCase):
    def test_tree_to_dict_shape(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            payload = tree_to_dict(tree)
            self.assertEqual(payload["name"], "demo")
            self.assertEqual(payload["type"], "dir")
            self.assertEqual(payload["size"], 660)
            children = {c["name"]: c for c in payload["children"]}
            self.assertEqual(children["aaa_dir"]["type"], "dir")
            self.assertEqual(children["aaa_dir"]["size"], 200)
            note = children["aaa_dir"]["children"]
            self.assertEqual([n["name"] for n in note], ["note.txt"])
            self.assertEqual(note[0]["type"], "file")
            self.assertEqual(note[0]["size"], 200)
            self.assertEqual(children["zzz.log"]["children"], [])
            json.dumps(payload)
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


class CountsTest(unittest.TestCase):
    def test_counts_excluding_root(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = _full(root)
            self.assertEqual(counts(tree), (3, 5))
            filter_dirs(tree)
            self.assertEqual(counts(tree), (3, 0))
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_counts_respect_depth_limit(self) -> None:
        root = make_demo(_tmp())
        try:
            tree = collect_tree(root, Options(depth=1))
            self.assertEqual(counts(tree), (2, 3))
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
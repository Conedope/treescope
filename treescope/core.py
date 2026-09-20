"""treescope.core -- build, filter, sort, and render directory trees.

Pure standard library (``pathlib``, ``os``, ``fnmatch``). Everything is
deterministic: no network, no locale-sensitive sorting, no ambient state.

Pipeline used by the CLI::

    collect_tree(root, opts)   # walk the filesystem, build a Node tree
    dir_size(root)             # compute & cache per-directory aggregate sizes
    apply_ignore(root, pats)   # prune .gitignore-style matches
    filter_dirs(root)          # --dirs-only: drop file nodes (sizes kept)
    sort_tree(root, opts)      # re-sort each level (size/mtime/name)
    render(root, opts)         # stringify

Design decisions (documented in README.md):

* ``collect_tree`` walks depth-first and lists each directory's entries as
  **directories first, then files**, each group sorted by ``name``.  Sorting by
  size or mtime is a later, separate step (``sort_node`` / ``sort_tree``).
* Symlinks are never followed: a symlink is listed as a plain (leaf) entry and
  its size is the link itself (``stat`` with ``follow_symlinks=False``).  This
  keeps the walk loop-safe and deterministic.
* An unreadable subdirectory is kept as a directory node with no children and a
  warning is emitted through ``Options.warn`` (the CLI prints it to stderr).
* Width-limited directories (``--depth``) are listed as empty: sizes beyond the
  depth limit are not attempted, so a depth-limited directory reports size 0
  until it is expanded.
* ``dir_size`` must run before ``apply_ignore`` / ``filter_dirs`` prune file
  nodes; once sizes are cached on every directory node they survive pruning.
* ``.git`` directories are always ignored (cannot be re-included).
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

__all__ = [
    "Node",
    "Options",
    "apply_ignore",
    "collect_tree",
    "compile_patterns",
    "counts",
    "dir_size",
    "filter_dirs",
    "format_size",
    "render",
    "sort_node",
    "sort_tree",
    "tree_to_dict",
]

_SIZE_UNITS: Tuple[str, ...] = ("B", "KB", "MB", "GB", "TB")

_ASCII_GLYPHS: Dict[str, str] = {
    "mid": "|-- ",
    "last": "`-- ",
    "cont_mid": "|   ",
    "cont_last": "    ",
}

_UNICODE_GLYPHS: Dict[str, str] = {
    "mid": "\u251c\u2500\u2500 ",
    "last": "\u2514\u2500\u2500 ",
    "cont_mid": "\u2502   ",
    "cont_last": "    ",
}


@dataclass
class Node:
    """One entry in a directory tree."""

    name: str
    path: Path
    is_dir: bool
    size: int = 0
    children: List["Node"] = field(default_factory=list)


@dataclass
class Options:
    """Tuning knobs shared between ``collect_tree`` and friends."""

    depth: Optional[int] = None  # None = unlimited; 0 lists only the root
    sizes: bool = False
    dirs_only: bool = False
    sort: str = "name"  # one of: name, size, mtime
    ascii: bool = True
    warn: Optional[Callable[[str], None]] = None  # receives stderr-style warnings


@dataclass
class _Pat:
    """A compiled .gitignore-style pattern."""

    pattern: str
    negated: bool
    dir_only: bool
    anchored: bool  # pattern contained a "/", so it matches relative paths


def compile_patterns(patterns) -> List[_Pat]:
    """Turn raw pattern strings into ``_Pat`` matchers.

    Subset of .gitignore semantics:

    * blank lines and ``#`` comments are skipped
    * a leading ``!`` negates (re-includes) the pattern
    * a trailing ``/`` restricts the pattern to directories
    * ``*``, ``?`` and ``[...]`` are handed to :func:`fnmatch.fnmatchcase`
    * a pattern containing ``/`` matches against the path relative to the tree
      root; a single leading ``/`` anchors it to the root
    * any other pattern matches the bare entry name at any depth
    """

    out: List[_Pat] = []
    for raw in patterns:
        if not isinstance(raw, str):
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pat = stripped
        negated = False
        if pat.startswith("!"):
            negated = True
            pat = pat[1:]
        pat = pat.strip()
        if not pat:
            continue
        dir_only = pat.endswith("/")
        if dir_only:
            pat = pat[:-1]
        if not pat:
            continue
        anchored = "/" in pat
        if anchored and pat.startswith("/"):
            pat = pat[1:]
        if not pat:
            continue
        out.append(_Pat(pattern=pat, negated=negated, dir_only=dir_only,
                        anchored=anchored))
    return out


def _warn(opts: Options, message: str) -> None:
    if opts.warn is not None:
        opts.warn(message)


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir(follow_symlinks=False)
    except OSError:
        return False


def _file_size(path: Path, opts: Options) -> int:
    try:
        return path.stat(follow_symlinks=False).st_size
    except OSError as exc:
        _warn(opts, f"treescope: warning: cannot stat '{path}': {exc.strerror or exc}")
        return 0


def _sorted_entries(path: Path, opts: Options) -> List[Path]:
    try:
        scandir = os.scandir(path)
    except OSError as exc:
        _warn(opts, f"treescope: warning: cannot read directory '{path}': {exc.strerror or exc}")
        return []
    try:
        names = sorted(e.name for e in scandir)
    finally:
        scandir.close()
    names.sort(key=lambda n: (0 if _is_dir(path / n) else 1, n))
    return [path / n for n in names]


def _display_name(path: Path) -> str:
    if path == Path("."):
        return "."
    name = path.name
    return name if name else str(path)


def _collect_children(node: Node, opts: Options, depth: int) -> None:
    if opts.depth is not None and depth >= opts.depth:
        return
    for entry in _sorted_entries(node.path, opts):
        if _is_dir(entry):
            child = Node(name=entry.name, path=entry, is_dir=True)
            _collect_children(child, opts, depth + 1)
        else:
            child = Node(name=entry.name, path=entry, is_dir=False,
                         size=_file_size(entry, opts))
        node.children.append(child)


def collect_tree(root: Path, opts: Optional[Options] = None) -> Node:
    """Walk ``root`` depth-first and return the resulting :class:`Node`.

    Entries are listed directories-first then files, each sorted by name.
    File leaf sizes are read from the filesystem; directory sizes are left at
    ``0`` until :func:`dir_size` aggregates them.
    """
    if opts is None:
        opts = Options()
    node = Node(name=_display_name(root), path=root, is_dir=True)
    _collect_children(node, opts, 0)
    return node


def dir_size(node: Node) -> int:
    """Recursively sum file sizes and cache the result in ``node.size``.

    Runs bottom-up (post-order) so every directory's aggregate is cached,
    including after ``filter_dirs`` has pruned file nodes.
    """
    order: List[Node] = []
    stack: List[Node] = [node]
    while stack:
        current = stack.pop()
        order.append(current)
        if current.is_dir:
            stack.extend(current.children)
    for current in reversed(order):
        if current.is_dir:
            current.size = sum(child.size for child in current.children)
    return node.size


def _pat_matches(pat: _Pat, rel: str, name: str, is_dir: bool) -> bool:
    if pat.anchored:
        target = rel
    else:
        target = name
    if not fnmatch.fnmatchcase(target, pat.pattern):
        return False
    return not (pat.dir_only and not is_dir)


def _ignored(rel: str, name: str, is_dir: bool, pats: List[_Pat]) -> bool:
    ignored = False
    for pat in pats:
        if _pat_matches(pat, rel, name, is_dir):
            ignored = not pat.negated
    return ignored


def apply_ignore(root_node: Node, patterns, opts: Optional[Options] = None) -> Node:
    """Prune nodes matched by ``.gitignore``-style ``patterns``.

    * Patterns are evaluated in order; the last match wins (negations with
      ``!`` re-include).
    * A matched directory is pruned wholesale -- its contents are never
      descended into or shown.
    * ``.git`` directories are always ignored and cannot be re-included.
    """
    pats = compile_patterns(patterns)
    pats.append(_Pat(pattern=".git", negated=False, dir_only=True, anchored=False))

    root = root_node.path if root_node.is_dir else root_node.path.parent
    order: List[Node] = []
    stack: List[Node] = [root_node]
    while stack:
        current = stack.pop()
        order.append(current)
        if current.is_dir:
            stack.extend(current.children)

    ignored_ids = set()
    for current in reversed(order):
        if current is root_node:
            continue
        try:
            rel = current.path.relative_to(root).as_posix()
        except ValueError:
            rel = str(current.path)
        if _ignored(rel, current.name, current.is_dir, pats):
            ignored_ids.add(id(current))
        elif current.is_dir:
            current.children = [c for c in current.children if id(c) not in ignored_ids]
    root_node.children = [c for c in root_node.children if id(c) not in ignored_ids]
    return root_node


def filter_dirs(node: Node) -> Node:
    """Drop file nodes recursively for ``--dirs-only`` mode.

    Directory sizes were already cached by :func:`dir_size`, so the printed
    aggregates stay correct even though the files are no longer listed.
    """
    stack: List[Node] = [node]
    while stack:
        current = stack.pop()
        if not current.is_dir:
            continue
        current.children = [c for c in current.children if c.is_dir]
        stack.extend(current.children)
    return node


def _mtime(node: Node) -> float:
    try:
        return os.stat(node.path, follow_symlinks=False).st_mtime
    except OSError:
        return 0.0


def sort_node(children: List[Node], mode: str) -> List[Node]:
    """Return ``children`` sorted by ``mode``.

    * ``name`` (default): directories first, then files, each by name.
    * ``size``: descending size (directories and files interleaved); ties
      broken by name.
    * ``mtime``: descending modification time (via ``os.stat``); ties broken
      by name.
    """
    if mode == "name":
        return sorted(children, key=lambda c: (0 if c.is_dir else 1, c.name))
    if mode == "size":
        return sorted(children, key=lambda c: (-c.size, c.name))
    if mode == "mtime":
        return sorted(children, key=lambda c: (-_mtime(c), c.name))
    raise ValueError(f"unknown sort mode: {mode!r}")


def sort_tree(node: Node, opts: Optional[Options] = None) -> Node:
    """Apply :func:`sort_node` to every directory level of the tree."""
    mode = opts.sort if opts is not None else "name"
    stack: List[Node] = [node]
    while stack:
        current = stack.pop()
        current.children = sort_node(current.children, mode)
        if current.is_dir:
            stack.extend(current.children)
    return node


def format_size(num: int) -> str:
    """Format a byte count as e.g. ``123 B``, ``1.5 KB``, ``2.0 MB``."""
    if not isinstance(num, int):
        num = int(num)
    if num < 1024:
        return f"{num} B"
    size = float(num)
    unit: str = _SIZE_UNITS[0]
    for unit in _SIZE_UNITS[1:]:
        size /= 1024.0
        if size < 1024.0:
            break
    return f"{size:.1f} {unit}"


def _plain_lines(node: Node, glyphs: Dict[str, str]) -> List[str]:
    lines = [node.name]
    _plain_rows(node, "", lines, glyphs)
    return lines


def _plain_rows(node: Node, prefix: str, lines: List[str],
                glyphs: Dict[str, str]) -> None:
    count = len(node.children)
    for index, child in enumerate(node.children):
        last = index == count - 1
        connector = glyphs["last"] if last else glyphs["mid"]
        lines.append(prefix + connector + child.name)
        if child.is_dir and child.children:
            continuation = prefix + (glyphs["cont_last"] if last else glyphs["cont_mid"])
            _plain_rows(child, continuation, lines, glyphs)


def _size_rows(node: Node, prefix: str, entries: List[Tuple[str, Node]],
               glyphs: Dict[str, str]) -> None:
    count = len(node.children)
    for index, child in enumerate(node.children):
        last = index == count - 1
        connector = glyphs["last"] if last else glyphs["mid"]
        label = prefix + connector + child.name
        if child.is_dir:
            label += " [DIR]"
        entries.append((label, child))
        if child.is_dir:
            continuation = prefix + (glyphs["cont_last"] if last else glyphs["cont_mid"])
            _size_rows(child, continuation, entries, glyphs)


def _join_with_sizes(root: Node, glyphs: Dict[str, str]) -> str:
    entries: List[Tuple[str, Node]] = []
    _size_rows(root, "", entries, glyphs)

    root_label = f"{root.name} [DIR]"
    labels = [root_label] + [label for label, _ in entries]
    size_texts = [f"({format_size(root.size)})"] + \
                 [f"({format_size(node.size)})" for _, node in entries]

    label_width = max(len(label) for label in labels)
    column_width = max(len(text) for text in size_texts)

    lines = [labels[0].ljust(label_width) + " " + size_texts[0].rjust(column_width)]
    for index, (label, node) in enumerate(entries):
        lines.append(label.ljust(label_width) + " " + size_texts[index + 1].rjust(column_width))
    return "\n".join(lines)


def render(root_node: Node, opts: Optional[Options] = None) -> str:
    """Render ``root_node`` as a connector-glyph tree (no summary line).

    ``--sizes`` mode right-aligns a ``(123 B)`` size column and marks
    directories with `` [DIR]`` (aggregate sizes for directories).  The
    summary line is the CLI's job, not ``render``'s.
    """
    if opts is None:
        opts = Options()
    glyphs = _UNICODE_GLYPHS if not opts.ascii else _ASCII_GLYPHS
    if opts.sizes:
        return _join_with_sizes(root_node, glyphs)
    return "\n".join(_plain_lines(root_node, glyphs))


def tree_to_dict(node: Node) -> dict:
    """Convert a :class:`Node` into a JSON-serialisable dict."""
    payload: dict = {
        "name": node.name,
        "type": "dir" if node.is_dir else "file",
        "size": node.size,
    }
    payload["children"] = [tree_to_dict(child) for child in node.children]
    return payload


def counts(node: Node) -> Tuple[int, int]:
    """Count directories and files in the tree, excluding the root itself."""
    num_dirs = 0
    num_files = 0
    for child in node.children:
        stack = [child]
        while stack:
            current = stack.pop()
            if current.is_dir:
                num_dirs += 1
                stack.extend(current.children)
            else:
                num_files += 1
    return num_dirs, num_files
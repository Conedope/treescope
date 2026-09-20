"""treescope.cli -- command-line interface for :mod:`treescope.core`.

Exit codes:

* ``0`` -- success (the tree was printed / dumped as JSON, or ``--help`` /
  ``--version``)
* ``2`` -- usage error: missing/invalid DIRECTORY, bad ``--depth``, or an
  argparse error (argparse's standard exit)

Warnings (unreadable subdirectories, missing ignore files) go to stderr and
do not change the exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .core import (
    Options,
    apply_ignore,
    collect_tree,
    counts,
    dir_size,
    filter_dirs,
    render,
    sort_tree,
    tree_to_dict,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="treescope",
        description=(
            "Print a directory tree with connector glyphs, optional size "
            "summaries, .gitignore-style ignore patterns, and sort modes. "
            "Deterministic and fully offline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        metavar="DIR",
        help="directory to display (default: current directory)",
    )
    parser.add_argument(
        "-d",
        "--depth",
        dest="depth",
        type=int,
        default=None,
        metavar="N",
        help="descend at most N levels (0 shows only DIR itself)",
    )
    parser.add_argument(
        "-L",
        "--level",
        dest="depth",
        type=int,
        default=None,
        metavar="N",
        help="alias for --depth",
    )
    parser.add_argument(
        "--sizes",
        action="store_true",
        help="print file sizes and per-directory aggregate sizes",
    )
    parser.add_argument(
        "--dirs-only",
        action="store_true",
        help="list directories only (aggregate sizes still shown with --sizes)",
    )
    glyphs = parser.add_mutually_exclusive_group()
    glyphs.add_argument(
        "--ascii",
        dest="ascii",
        action="store_true",
        help="use ASCII connector glyphs (default)",
    )
    glyphs.add_argument(
        "--unicode",
        dest="ascii",
        action="store_false",
        help="use Unicode box-drawing connector glyphs",
    )
    parser.set_defaults(ascii=True)
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            ".gitignore-style pattern to exclude; repeatable, or pass a "
            "comma-separated list"
        ),
    )
    parser.add_argument(
        "--ignore-file",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "read .gitignore-style patterns from a file; PATH is resolved "
            "relative to DIR first, then the current directory"
        ),
    )
    parser.add_argument(
        "--sort",
        choices=("name", "size", "mtime"),
        default="name",
        help="sort entries at each level: name (default), size (desc), mtime (desc)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the tree as JSON (name/type/size/children) and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"treescope {__version__}",
        help="print the version and exit",
    )
    return parser


def _resolve_ignore_file(path: Path, start: Path) -> Optional[Path]:
    candidates: List[Path] = []
    if not path.is_absolute():
        candidates.append(start / path)  # relative to DIR first
    candidates.append(path)  # then the current directory
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_ignore_file(path: Path, opts: Options) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _warn(opts, f"treescope: warning: cannot read ignore file '{path}': {exc.strerror or exc}")
        return []
    return text.splitlines()


def _warn(opts: Options, message: str) -> None:
    if opts.warn is not None:
        opts.warn(message)


def _summary(num_dirs: int, num_files: int) -> str:
    dir_word = "directory" if num_dirs == 1 else "directories"
    file_word = "file" if num_files == 1 else "files"
    return f"{num_dirs} {dir_word}, {num_files} {file_word}"


def _split_ignores(values: Sequence[str]) -> List[str]:
    patterns: List[str] = []
    for value in values:
        for part in value.split(","):
            if part:
                patterns.append(part)
    return patterns


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.depth is not None and args.depth < 0:
        parser.error("--depth/--level must be >= 0")

    root = Path(args.directory)
    if not root.exists():
        print(f"treescope: error: '{args.directory}': no such file or directory",
              file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"treescope: error: '{args.directory}': not a directory",
              file=sys.stderr)
        return 2

    opts = Options(
        depth=args.depth,
        sizes=args.sizes,
        dirs_only=args.dirs_only,
        sort=args.sort,
        ascii=args.ascii,
    )
    opts.warn = lambda message: print(message, file=sys.stderr)

    patterns = _split_ignores(args.ignore)
    for file_arg in args.ignore_file:
        resolved = _resolve_ignore_file(Path(file_arg), root)
        if resolved is None:
            _warn(
                opts,
                f"treescope: warning: ignore file '{file_arg}' not found "
                "(looked for it relative to both DIR and the current directory)",
            )
        else:
            patterns.extend(_load_ignore_file(resolved, opts))

    tree = collect_tree(root, opts)
    dir_size(tree)
    apply_ignore(tree, patterns, opts)
    if opts.dirs_only:
        filter_dirs(tree)
    sort_tree(tree, opts)

    if args.json:
        print(json.dumps(tree_to_dict(tree), indent=2))
        return 0

    print(render(tree, opts))
    num_dirs, num_files = counts(tree)
    print(_summary(num_dirs, num_files))
    return 0
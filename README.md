# treescope

A `tree`-like directory viewer for the command line. Prints a directory tree
with connector glyphs (ASCII or Unicode), optional per-directory size
summaries, `.gitignore`-style ignore patterns, sort modes, a directory-only
mode, and a `--json` dump. Pure Python standard library (`os`, `pathlib`,
`fnmatch`, `argparse`, `json`) — zero dependencies, fully offline, and
deterministic (no locale-sensitive sorting, no ambient state).

```
.
|-- src
|   |-- core.py
|   `-- cli.py
|-- tests
|   |-- test_core.py
|   `-- test_cli.py
`-- pyproject.toml
```

## Features

* **Connector glyphs** — ASCII (`|-- `, `` `-- ``) by default for deterministic
  output, or Unicode box-drawing (`├── `, `└── `) with `--unicode`.
* **Size summaries** — `--sizes` right-aligns a `(123 B)` / `(1.5 KB)` /
  `(2.0 MB)` column; directories show their **aggregate** size plus a
  ` [DIR]` marker.
* **`.gitignore`-style ignores** — `--ignore` (repeatable or comma-list) and
  `--ignore-file`. Negation, directory-only patterns, and `*` / `?` / `[...]`
  wildcards; ignored directories are never descended into. `.git` directories
  are always ignored.
* **Sort modes** — `--sort name` (default: directories first, then files, each
  alphabetical), `--sort size` (largest first), `--sort mtime` (newest first).
* **Directory-only mode** — `--dirs-only` lists only directories (file sizes
  still count towards aggregates).
* **Depth limit** — `-d/--depth N` or `-L/--level N`.
* **JSON output** — `--json` dumps the tree as `{name, type, size, children}`
  for scripting and testing.

## Installation

```sh
python -m pip install -e .
treescope --version   # treescope 1.0.0
```

## Usage

```
usage: treescope [-h] [-d N | -L N] [--sizes] [--dirs-only]
                 [--ascii | --unicode] [--ignore PATTERN]
                 [--ignore-file PATH] [--sort name|size|mtime]
                 [--json] [--version] [DIR]
```

| Flag | Description |
|------|-------------|
| `DIR` | Directory to display (default: `.`, the current directory). |
| `-d N`, `--depth N` | Descend at most `N` levels (`0` shows only `DIR` itself). |
| `-L N`, `--level N` | Alias for `--depth`. |
| `--sizes` | Print a right-aligned size column; directories show aggregate size and ` [DIR]`. |
| `--dirs-only` | List only directories (aggregates still shown with `--sizes`). |
| `--ascii` | ASCII connector glyphs (default). |
| `--unicode` | Unicode box-drawing connector glyphs. |
| `--ignore PATTERN` | `.gitignore`-style pattern; repeatable, or a comma-separated list. |
| `--ignore-file PATH` | Read patterns from a file (relative to `DIR` first, then the current directory). |
| `--sort MODE` | `name` (default), `size` (desc), `mtime` (desc). |
| `--json` | Print the tree as JSON and exit. |
| `--version` | Print `treescope 1.0.0` and exit. |
| `-h`, `--help` | Show help and exit. |

Every invocation ends with a summary line like `3 directories, 5 files`
(JSON mode skips it).

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (tree printed / JSON dumped, or `--help` / `--version`). |
| `2` | Usage error: `DIR` missing or not a directory, negative `--depth`, bad `--sort` value. |

Warnings (unreadable subdirectories, missing ignore files) are printed to
stderr and do not change the exit code.

## Ignore patterns

A subset of `.gitignore` semantics:

| Pattern | Meaning |
|---------|---------|
| `build` | Ignores a file **or** directory named `build` at any depth. |
| `build/` | Directory-only: ignores directories named `build`, never files. |
| `!keep.log` | Negation: re-includes the last thing the pattern matches. |
| `*.log` | `fnmatch` glob: any name ending in `.log`. |
| `a?.txt` | `?` matches exactly one character. |
| `a[0-9].txt` | `[...]` character class. |
| `src/main.py` | Contains `/`: matches the path **relative to `DIR`** (root-anchored). A leading `/` is stripped. |
| `# comment` | Lines starting with `#` and blank lines are skipped. |

Patterns are evaluated in order and the **last match wins**, so
`*.log` followed by `!keep.log` removes everything except `keep.log`. A
matched directory is pruned wholesale — its contents are never descended into
(and `!` can't re-include anything inside an excluded directory, as in git).
`.git` is always ignored and cannot be re-included. Matching is done with
`fnmatch` on relative paths, so a `*` inside a slash-containing pattern may
match across `/` boundaries (e.g. `docs/*.md` also matches
`docs/deep/b.md`).

## Examples

These outputs were produced by actually running the tool.

### 1. Default listing of this repository

```sh
$ treescope . --ignore "*.pyc,__pycache__*,*.egg-info,build,dist,.git"
.
|-- .github
|   `-- workflows
|       `-- ci.yml
|-- tests
|   |-- helpers.py
|   |-- test_cli.py
|   `-- test_core.py
|-- treescope
|   |-- __init__.py
|   |-- __main__.py
|   |-- cli.py
|   `-- core.py
|-- .gitignore
|-- LICENSE
`-- pyproject.toml
4 directories, 11 files
```

### 2. With sizes, directories only

```sh
$ treescope . --sizes --dirs-only --ignore "*.pyc,__pycache__*,*.egg-info"
. [DIR]                 (163.1 KB)
|-- .github [DIR]          (605 B)
|   `-- workflows [DIR]    (605 B)
|-- tests [DIR]         (103.3 KB)
`-- treescope [DIR]      (56.8 KB)
4 directories, 0 files
```

### 3. JSON dump

```sh
$ treescope . --json --ignore "*.pyc,__pycache__*,*.egg-info"
{
  "name": ".",
  "type": "dir",
  "size": 167054,
  "children": [
    {
      "name": ".github",
      "type": "dir",
      "size": 605,
      "children": [
        {
          "name": "workflows",
          "type": "dir",
          "size": 605,
          "children": [
            {
              "name": "ci.yml",
              "type": "file",
              "size": 605,
              "children": []
            }
          ]
        }
      ]
    }
  ]
  ...
}
```

### 4. Unicode, sorted by size

```sh
$ treescope . --unicode --sort size --sizes --level 1
```

## Design decisions & semantics

* **Ordering** — `collect_tree` walks depth-first and lists each directory as
  **directories first, then files**, each group sorted by `name`. Size and
  mtime sorts are applied separately and interleave directories and files.
* **Sizes** — Directory sizes are the sum of every file in the subtree,
  computed by `dir_size()` and cached on each node *before* ignore/dir-only
  filtering. So `--dirs-only` aggregates stay correct even though the files
  are hidden, and ignore patterns hide listing entries **without** changing
  directory totals (a `build/` folder still counts its bytes in the parent —
  like `du`, sizes describe the filesystem, not the filter).
* **Symlinks** — never followed (loop-safe). A symlink is listed as a plain
  entry; its size is the link itself (`stat` with `follow_symlinks=False`).
* **Depth limit** — directories at the boundary are listed but not expanded,
  so their sizes are reported as `0 B` until expanded.
* **Unreadable directories** — kept as empty directory nodes with a warning
  on stderr; the walk continues.
* **`--sizes` formatting** — `format_size` uses `B`, `KB`, `MB`, `GB`, `TB`
  (base-1024) with one decimal beyond bytes, so `1536` → `1.5 KB`.

## Project layout

```
treescope/
  core.py    # Node model, collect, dir_size, ignore, sort, render (no argparse)
  cli.py     # argparse wrapper, exit codes, JSON dump, summary line
tests/       # unittest: core goldens + end-to-end CLI subprocess tests
pyproject.toml
```

## Development

```sh
python -m unittest discover -s tests -v
```

The test suite builds deterministic temp trees (fixed names, sizes and mtimes)
and asserts **exact** golden snapshots, plus CLI exit codes and JSON shape via
real subprocesses.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Conedope.
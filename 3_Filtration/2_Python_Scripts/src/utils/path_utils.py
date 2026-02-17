# src/utils/path_utils.py
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Union

PathLike = Union[str, Path]


def _as_dir(p: PathLike) -> Path:
    """Normalize to an existing directory path if possible; if p is a file -> parent."""
    x = Path(p).resolve()
    # If path exists and is file -> parent
    if x.exists() and x.is_file():
        return x.parent
    # If it doesn't exist but has a suffix, it *looks* like a file path (e.g. __file__ in weird contexts)
    if x.suffix:
        return x.parent
    return x


def repo_root_from_anchor(anchor: PathLike, *, markers: Iterable[str] = ("src",)) -> Path:
    """
    Determine repo root by walking upwards from anchor until we find one of the marker directories/files.
    For marker 'src', the repo root is the directory that CONTAINS 'src' (i.e. parent/src exists).
    """
    start = _as_dir(anchor)

    for parent in (start, *start.parents):
        for m in markers:
            if (parent / m).exists():
                return parent

    raise RuntimeError(
        f"Could not determine repo root from anchor={anchor!s}. "
        f"Searched parents of {start!s} for markers={tuple(markers)!r}."
    )


def project_root(anchor_file: PathLike | None = None) -> Path:
    """
    Project/repo root directory.

    Recommended: pass __file__.
    If omitted: falls back to Path.cwd().
    """
    anchor = Path.cwd() if anchor_file is None else anchor_file
    return repo_root_from_anchor(anchor, markers=("src",))


def resolve_under(root: PathLike, *parts: str) -> Path:
    """
    Join parts under root.
    If root points to a file (or looks like a file), use its parent directory.
    """
    r = _as_dir(root)
    return r.joinpath(*parts)


def ensure_dir(path: PathLike) -> Path:
    """
    Ensure directory exists (mkdir -p). If path is a file or looks like a file, raise.
    """
    p = Path(path).resolve()

    # If it exists as a file -> hard error
    if p.exists() and p.is_file():
        raise FileExistsError(f"ensure_dir(): path exists as a file, not a directory: {p}")

    # If it does not exist but looks like a file path, also hard error (prevents 'main_window.py/logs')
    if not p.exists() and p.suffix:
        raise FileExistsError(f"ensure_dir(): path looks like a file path, not a directory: {p}")

    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_parent_dir(path: PathLike) -> Path:
    p = Path(path).resolve()
    ensure_dir(p.parent)
    return p.parent


def repo_root_from_file(file_path: PathLike, *, markers: Iterable[str] = ("src",)) -> Path:
    """
    Backwards-compatible alias: determine repo root using a file path anchor.

    Historically some modules import `repo_root_from_file`; internally we now use
    `repo_root_from_anchor`. This keeps old imports working.
    """
    return repo_root_from_anchor(file_path, markers=markers)

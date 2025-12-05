"""Centralized helpers for resolving repository-relative paths."""

from __future__ import annotations

from pathlib import Path

_SCRIPTROOT = Path(__file__).parent
_RESOLVED_SCRIPTROOT = _SCRIPTROOT.resolve()


def _candidate_roots() -> list[Path]:
    """Return potential root directories ordered from nearest to farthest."""
    ordered: list[Path] = []
    seen: set[Path] = set()
    for base in (
        _SCRIPTROOT,
        *_SCRIPTROOT.parents,
        _RESOLVED_SCRIPTROOT,
        *_RESOLVED_SCRIPTROOT.parents,
    ):
        if base in seen:
            continue
        seen.add(base)
        ordered.append(base)
    return ordered


def _discover_project_root() -> Path:
    for base in _candidate_roots():
        if (base / "pyproject.toml").exists():
            return base
    # Fallback to the historical behavior of ascending two directories.
    return _RESOLVED_SCRIPTROOT.parent.parent.resolve()


PROJECT_ROOT = _discover_project_root()
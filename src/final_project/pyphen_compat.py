"""Runtime patches for Pyphen when running under bundled builds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyphen


def _is_hashable(value: Any) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _candidate_path(lang: str, entry: Any, dictionaries_dir: Path) -> Path | None:
    """Best-effort conversion of resource entries into filesystem paths."""
    if isinstance(entry, Path):
        return entry

    try:
        return Path(entry)  # Handles str or os.PathLike implementations.
    except TypeError:
        pass

    filename = getattr(entry, "name", None)
    if isinstance(filename, str):
        candidate = dictionaries_dir / filename
        if candidate.exists():
            return candidate

    fallback = dictionaries_dir / f"hyph_{lang}.dic"
    if fallback.exists():
        return fallback

    return None


def stabilize_pyphen_language_paths() -> None:
    """Ensure Pyphen uses hashable, on-disk paths for dictionary lookups."""
    dictionaries_dir = Path(pyphen.__file__).parent / "dictionaries"
    if not dictionaries_dir.exists():
        return

    updated = False
    for lang, entry in list(pyphen.LANGUAGES.items()):
        if _is_hashable(entry):
            continue

        replacement = _candidate_path(lang, entry, dictionaries_dir)
        if replacement is None:
            continue

        pyphen.LANGUAGES[lang] = replacement
        updated = True

    if updated:
        pyphen.LANGUAGES_LOWERCASE = {name.lower(): name for name in pyphen.LANGUAGES}

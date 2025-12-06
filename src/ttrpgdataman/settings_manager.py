"""Helpers for loading and persisting user-adjustable settings."""

from __future__ import annotations

from lazi.core import lazi

from ttrpgdataman.paths import PROJECT_ROOT

with lazi:  # type: ignore[attr-defined]
    import copy
    import json
    import os
    import sys
    import tomllib
    from collections.abc import Iterable
    from pathlib import Path
    from typing import Any
    from typing import cast

    import structlog

logger = structlog.getLogger("ttrpgdataman")


class _SettingsState:
    def __init__(self) -> None:
        self.cache: dict[str, Any] | None = None
        self.user_settings_path: Path | None = None


DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "data" / "settings.toml"

_STATE = _SettingsState()


def ensure_settings_initialized() -> None:
    """Populate the in-memory cache, creating the file if needed."""
    _get_cache()


def get_settings_snapshot() -> dict[str, Any]:
    """Return a deep copy of the cached settings."""
    return copy.deepcopy(_get_cache())


def reload_settings_from_disk() -> dict[str, Any]:
    """Refresh the cache from disk and return a deep copy."""
    cache = _load_settings_from_disk()
    _STATE.cache = cache
    return copy.deepcopy(cache)


def reset_user_settings_to_defaults() -> dict[str, Any]:
    """Remove the user overrides file and restore the cached defaults."""
    path = _user_settings_path()
    path.unlink(missing_ok=True)
    defaults = _load_default_settings()
    _STATE.cache = copy.deepcopy(defaults)
    return copy.deepcopy(defaults)


def save_settings(new_settings: dict[str, Any]) -> dict[str, Any]:
    """Persist user-specific settings, merged over defaults."""
    defaults = _load_default_settings()
    merged = _merge_dicts(copy.deepcopy(defaults), new_settings)
    overrides = _calculate_overrides(defaults, merged)
    user_path = _user_settings_path()
    if overrides:
        _write_settings(user_path, overrides)
    else:
        user_path.unlink(missing_ok=True)
    _STATE.cache = copy.deepcopy(merged)
    return copy.deepcopy(merged)


def get_setting(group: str, key: str, fallback: Any = None) -> Any:
    """Retrieve a specific setting with an optional fallback."""
    grouped = _get_cache().get(group, {})
    return copy.deepcopy(grouped.get(key, fallback))


def path_from_settings(
    key: str,
    *,
    group: str = "Paths",
    fallback: str | os.PathLike[str] | None = None,
) -> Path:
    """Return an absolute Path for the requested setting key."""
    raw_value = get_setting(group, key, fallback=fallback)
    if raw_value is None:
        msg = f"Missing setting: {group}.{key}"
        raise KeyError(msg)
    path = Path(str(raw_value).strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _get_cache() -> dict[str, Any]:
    cache = _STATE.cache
    if cache is None:
        cache = _load_settings_from_disk()
        _STATE.cache = cache
    return cache


def _load_settings_from_disk() -> dict[str, Any]:
    defaults = _load_default_settings()
    user_overrides = _read_settings_file(_user_settings_path())
    logger.debug("Loading user settings", path=str(_user_settings_path()))
    if user_overrides:
        return _merge_dicts(defaults, user_overrides)
    return defaults


def _merge_dicts(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            nested_base = cast(dict[str, Any], base[key])
            nested_override = cast(dict[str, Any], value)
            base[key] = _merge_dicts(nested_base, nested_override)
        else:
            base[key] = value
    return base


def _write_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for group in sorted(settings):
        lines.append(f"[{group}]")
        group_values = settings[group]
        for key in sorted(group_values):
            serialized = _format_toml_value(group_values[key])
            lines.append(f"{key} = {serialized}")
        lines.append("")
    content = "\n".join(lines).strip() + "\n"
    path.write_text(content, encoding="utf-8")


def _read_settings_file(path: Path, *, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            msg = f"required settings file missing: {path}"
            raise FileNotFoundError(msg)
        return {}
    with path.open("rb") as handle:
        try:
            return tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            if required:
                msg = f"settings file contains invalid TOML: {path}"
                raise ValueError(msg) from exc
            return {}


def _load_default_settings() -> dict[str, Any]:
    defaults = _read_settings_file(DEFAULT_SETTINGS_PATH, required=True)
    return copy.deepcopy(defaults)


def _user_settings_path() -> Path:
    if _STATE.user_settings_path is None:
        _STATE.user_settings_path = _resolve_user_settings_path()
    return _STATE.user_settings_path


def _calculate_overrides(
    defaults: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in current.items():
        default_value = defaults.get(key)
        if isinstance(value, dict) and isinstance(default_value, dict):
            nested_defaults = cast(dict[str, Any], default_value)
            nested_value = cast(dict[str, Any], value)
            nested = _calculate_overrides(nested_defaults, nested_value)
            if nested:
                overrides[key] = nested
        elif default_value != value:
            overrides[key] = value
    return overrides


def _resolve_user_settings_path() -> Path:
    base_dir: Path
    home = Path.home()
    if sys.platform.startswith("win"):
        base_dir = Path(os.environ.get("APPDATA", home))
    elif sys.platform == "darwin":
        base_dir = home / "Library" / "Application Support"
    else:
        base_dir = Path(os.environ.get("XDG_CONFIG_HOME", home))
    return base_dir / ".ttrpgdataman" / "settings.toml"


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        iterable_items = list(cast(Iterable[Any], value))
        serialized_items = [_format_toml_value(item) for item in iterable_items]
        return "[" + ", ".join(serialized_items) + "]"
    return json.dumps(value)

"""Unit tests for the settings manager helpers."""

# ruff: noqa: S101, SLF001
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from final_project import settings_manager as sm

DEFAULT_IMAGE_STEPS = 15
OVERRIDE_IMAGE_STEPS = 20
ORIGINAL_RESOLVE_USER_PATH = sm._resolve_user_settings_path


@pytest.fixture(autouse=True)
def reset_settings_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Clear cached state and point default/user paths to a temp directory."""
    backup_state = sm._STATE  # type: ignore[attr-defined]
    backup_cache = backup_state.cache
    backup_user_path = backup_state.user_settings_path
    user_path = tmp_path / "user" / "settings.toml"

    def fake_resolve() -> Path:
        return user_path

    monkeypatch.setattr(sm, "_resolve_user_settings_path", fake_resolve)

    backup_state.cache = None
    backup_state.user_settings_path = user_path
    sm.reload_settings_from_disk()
    assert sm._STATE.cache is not None
    assert sm._STATE.cache
    assert sm._user_settings_path() == user_path

    yield

    backup_state.cache = backup_cache
    backup_state.user_settings_path = backup_user_path


def test_get_setting_returns_deepcopy() -> None:
    """get_setting should return copies so the source cache stays pristine."""
    sm.ensure_settings_initialized()
    original = sm.get_setting("LLM", "image_steps")
    assert original == DEFAULT_IMAGE_STEPS
    original = 42
    # A second read should be unaffected by mutating the previous value
    assert sm.get_setting("LLM", "image_steps") == DEFAULT_IMAGE_STEPS


def test_save_settings_writes_overrides() -> None:
    """save_settings should persist overrides to the user configuration file."""
    sm.ensure_settings_initialized()
    result = sm.save_settings({"LLM": {"image_steps": OVERRIDE_IMAGE_STEPS}})
    assert result["LLM"]["image_steps"] == OVERRIDE_IMAGE_STEPS
    user_path = sm._user_settings_path()
    written = user_path.read_text(encoding="utf-8")
    assert f"image_steps = {OVERRIDE_IMAGE_STEPS}" in written


def test_path_from_settings_relative_and_absolute(tmp_path: Path) -> None:
    """path_from_settings should join PROJECT_ROOT or honor absolute overrides."""
    sm.ensure_settings_initialized()
    rel_path = sm.path_from_settings("sample_npc")
    assert rel_path.is_absolute()
    assert rel_path.parent == sm.PROJECT_ROOT / "data"

    absolute_file = tmp_path / "absolute" / "file.txt"
    absolute_file.parent.mkdir(parents=True)
    override = {"Paths": {"sample_npc": str(absolute_file)}}
    sm.save_settings(override)
    assert sm.path_from_settings("sample_npc") == absolute_file


def test_reload_and_reset_roundtrip() -> None:
    """reload/reset helpers should round-trip overrides and defaults."""
    sm.ensure_settings_initialized()
    sm.save_settings({"LLM": {"image_steps": OVERRIDE_IMAGE_STEPS}})
    reloaded = sm.reload_settings_from_disk()
    assert reloaded["LLM"]["image_steps"] == OVERRIDE_IMAGE_STEPS

    defaults = sm.reset_user_settings_to_defaults()
    assert defaults["LLM"]["image_steps"] == DEFAULT_IMAGE_STEPS
    user_path = sm._user_settings_path()
    assert not user_path.exists()


def test_missing_setting_raises_key_error() -> None:
    """path_from_settings should raise when a requested key is absent."""
    sm.ensure_settings_initialized()
    with pytest.raises(KeyError):
        sm.path_from_settings("missing_key")


def test_save_settings_removes_file_when_no_overrides() -> None:
    """Writing defaults again should remove the overrides file entirely."""
    sm.ensure_settings_initialized()
    user_path = sm._user_settings_path()
    sm.save_settings({"LLM": {"image_steps": OVERRIDE_IMAGE_STEPS}})
    assert user_path.exists()

    # Saving defaults again should remove the overrides file
    sm.save_settings({"LLM": {"image_steps": DEFAULT_IMAGE_STEPS}})
    assert not user_path.exists()


def test_calculate_overrides_nested_sections() -> None:
    """_calculate_overrides should only return diffed nested values."""
    defaults: dict[str, dict[str, Any]] = {
        "LLM": {
            "image_steps": DEFAULT_IMAGE_STEPS,
            "image_size": 256,
        },
        "Paths": {
            "sample_npc": "data/sample_npc.yaml",
            "sample_locations": "data/sample_locations.yaml",
        },
    }
    current: dict[str, dict[str, Any]] = {
        "LLM": {
            "image_steps": DEFAULT_IMAGE_STEPS,
            "image_size": 512,
        },
        "Paths": {
            "sample_npc": "override.yaml",
            "sample_locations": "data/sample_locations.yaml",
        },
        "Extras": {"feature": True},
    }

    overrides = sm._calculate_overrides(defaults, current)

    assert overrides == {
        "LLM": {"image_size": 512},
        "Paths": {"sample_npc": "override.yaml"},
        "Extras": {"feature": True},
    }


def test_write_settings_serializes_values(tmp_path: Path) -> None:
    """_write_settings should sort groups/keys and serialize TOML values."""
    target = tmp_path / "subdir" / "user_settings.toml"
    payload: dict[str, dict[str, Any]] = {
        "Core": {
            "theme": "light",
            "features": ["names", "encounters"],
        },
        "Paths": {
            "enabled": True,
            "max_items": 3,
        },
    }

    sm._write_settings(target, payload)

    content = target.read_text(encoding="utf-8").splitlines()
    assert content == [
        "[Core]",
        'features = ["names", "encounters"]',
        'theme = "light"',
        "",
        "[Paths]",
        "enabled = true",
        "max_items = 3",
    ]


def test_read_settings_file_missing_required_raises(tmp_path: Path) -> None:
    """_read_settings_file should raise when required=True and file absent."""
    missing = tmp_path / "missing.toml"

    with pytest.raises(FileNotFoundError):
        sm._read_settings_file(missing, required=True)


def test_read_settings_file_invalid_optional_returns_empty(tmp_path: Path) -> None:
    """Invalid TOML should return an empty dict when not required."""
    bad_file = tmp_path / "invalid.toml"
    bad_file.write_text("invalid = [", encoding="utf-8")

    assert sm._read_settings_file(bad_file, required=False) == {}


def test_read_settings_file_invalid_required_raises_value_error(tmp_path: Path) -> None:
    """Invalid TOML should raise ValueError when required=True."""
    bad_file = tmp_path / "invalid_required.toml"
    bad_file.write_text("invalid = [", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid TOML"):
        sm._read_settings_file(bad_file, required=True)


def test_format_toml_value_serializes_unknown_types() -> None:
    """_format_toml_value should JSON-serialize unknown objects (like dicts)."""
    payload = {"extra": [1, 2, 3]}

    assert sm._format_toml_value(payload) == '{"extra": [1, 2, 3]}'


def test_resolve_user_settings_path_darwin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_resolve_user_settings_path should use the macOS application support dir."""
    monkeypatch.setattr(sm, "_resolve_user_settings_path", ORIGINAL_RESOLVE_USER_PATH)
    monkeypatch.setattr(sm.sys, "platform", "darwin")
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    def fake_home(_: type[Path]) -> Path:  # type: ignore[override]
        return home_dir

    monkeypatch.setattr(sm.Path, "home", classmethod(fake_home))
    sm._STATE.user_settings_path = None

    expected = (
        home_dir
        / "Library"
        / "Application Support"
        / ".final_project"
        / "settings.toml"
    )
    assert sm._resolve_user_settings_path() == expected


def test_resolve_user_settings_path_linux(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_resolve_user_settings_path should honor XDG_CONFIG_HOME on linux."""
    monkeypatch.setattr(sm, "_resolve_user_settings_path", ORIGINAL_RESOLVE_USER_PATH)
    monkeypatch.setattr(sm.sys, "platform", "linux")
    xdg_dir = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
    sm._STATE.user_settings_path = None

    expected = xdg_dir / ".final_project" / "settings.toml"
    assert sm._resolve_user_settings_path() == expected

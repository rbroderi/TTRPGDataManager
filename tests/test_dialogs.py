"""GUI-adjacent tests for final_project.dialogs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from collections.abc import Sequence
from copy import deepcopy
from typing import cast

import customtkinter as ctk
import pytest

from final_project import dialogs
from final_project.campaign_dialog import CampaignDialog


@pytest.fixture(name="tk_app")
def fixture_tk_app() -> Iterator[ctk.CTk]:
    try:
        root = ctk.CTk()
    except tk.TclError as exc:
        pytest.skip(f"tk unavailable: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def test_llm_progress_dialog_updates_state_and_progress(tk_app: ctk.CTk) -> None:
    dialog = dialogs.LLMProgressDialog(tk_app)
    dialog.withdraw()
    dialog.update_status("Connecting", None)
    assert dialog.status_label.cget("text") == "Connecting"
    assert dialog._mode == "indeterminate"

    dialog.update_status("Halfway", 50)
    assert dialog._mode == "determinate"
    assert dialog.progress.get() == pytest.approx(0.5, rel=0.01)

    dialog.close()
    assert dialog.winfo_exists() == 0


@pytest.fixture(name="settings_dialog")
def fixture_settings_dialog() -> dialogs.SettingsDialog:
    return dialogs.SettingsDialog.__new__(dialogs.SettingsDialog)


def test_settings_dialog_convert_value_handles_various_types(
    settings_dialog: dialogs.SettingsDialog,
) -> None:
    original_bool = False
    assert settings_dialog._convert_value("true", original_bool) is True
    original_int = 1
    numeric_result = settings_dialog._convert_value("42", original_int)
    forty_two = 42
    assert numeric_result == forty_two
    assert settings_dialog._convert_value("3.5", 0.0) == pytest.approx(3.5)
    assert settings_dialog._convert_value("{'k': 1}", {"k": 0}) == {"k": 1}
    assert settings_dialog._convert_value("", None) is None


def test_settings_dialog_convert_value_rejects_bad_boolean(
    settings_dialog: dialogs.SettingsDialog,
) -> None:
    bad_original = False
    with pytest.raises(ValueError, match="enter true or false"):
        settings_dialog._convert_value("maybe", bad_original)


def test_settings_dialog_handle_save_updates_settings(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {"ui": {"refresh_seconds": 5, "theme": "dark"}}
    new_refresh_value = 15

    def fake_snapshot() -> dict[str, dict[str, int | str]]:
        return deepcopy(snapshot)

    saved_payloads: list[dict[str, dict[str, int | str]]] = []
    monkeypatch.setattr(
        dialogs.settings_manager,
        "get_settings_snapshot",
        fake_snapshot,
    )
    monkeypatch.setattr(
        dialogs.settings_manager,
        "save_settings",
        lambda payload: saved_payloads.append(payload) or payload,
    )
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialogs.messagebox,
        "showinfo",
        lambda *args: infos.append(args),
    )
    monkeypatch.setattr(
        dialogs.messagebox,
        "showerror",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected showerror")),
    )
    callbacks: list[dict[str, dict[str, int | str]]] = []
    dialog = dialogs.SettingsDialog(tk_app, on_settings_saved=callbacks.append)
    dialog.withdraw()
    entry, _original = dialog._fields[("ui", "refresh_seconds")]
    entry.delete(0, tk.END)
    entry.insert(0, str(new_refresh_value))

    dialog._handle_save()

    assert saved_payloads
    assert saved_payloads[0]["ui"]["refresh_seconds"] == new_refresh_value
    assert callbacks
    assert callbacks[0] is saved_payloads[0]
    assert infos
    assert infos[-1] == ("Settings", "Settings saved successfully.")


def test_settings_dialog_handle_save_reports_save_error(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {"ui": {"refresh_seconds": 5}}
    monkeypatch.setattr(
        dialogs.settings_manager,
        "get_settings_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        dialogs.settings_manager,
        "save_settings",
        lambda _payload: (_ for _ in ()).throw(OSError("disk full")),
    )
    errors: list[tuple[str, str]] = []
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialogs.messagebox,
        "showerror",
        lambda *args: errors.append(args),
    )
    monkeypatch.setattr(
        dialogs.messagebox,
        "showinfo",
        lambda *args: infos.append(args),
    )
    dialog = dialogs.SettingsDialog(tk_app)
    dialog.withdraw()
    entry, _original = dialog._fields[("ui", "refresh_seconds")]
    entry.delete(0, tk.END)
    entry.insert(0, "10")

    dialog._handle_save()

    try:
        assert errors
        assert "Unable to save settings" in errors[-1][1]
        assert not infos
        assert dialog.winfo_exists()
    finally:
        if dialog.winfo_exists():
            dialog._handle_cancel()


def test_settings_dialog_handle_save_validation_error_shows_message(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {"ui": {"refresh_seconds": 5}}
    monkeypatch.setattr(
        dialogs.settings_manager,
        "get_settings_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        dialogs.settings_manager,
        "save_settings",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should not save")),
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialogs.messagebox,
        "showerror",
        lambda *args: errors.append(args),
    )
    monkeypatch.setattr(dialogs.messagebox, "showinfo", lambda *args, **kwargs: None)
    dialog = dialogs.SettingsDialog(tk_app)
    dialog.withdraw()
    entry, _original = dialog._fields[("ui", "refresh_seconds")]
    entry.delete(0, tk.END)

    dialog._handle_save()

    try:
        assert errors
        assert "enter an integer value" in errors[0][1]
    finally:
        if dialog.winfo_exists():
            dialog._handle_cancel()


def test_settings_dialog_handle_reset_defaults_overwrites_fields(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_snapshot = {"ui": {"theme": "dark"}}
    new_snapshot = {"ui": {"theme": "light", "refresh_seconds": 9}}
    monkeypatch.setattr(
        dialogs.settings_manager,
        "get_settings_snapshot",
        lambda: deepcopy(initial_snapshot),
    )
    monkeypatch.setattr(
        dialogs.settings_manager,
        "reset_user_settings_to_defaults",
        lambda: deepcopy(new_snapshot),
    )
    monkeypatch.setattr(dialogs.messagebox, "askyesno", lambda *args, **kwargs: True)
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialogs.messagebox,
        "showinfo",
        lambda *args: infos.append(args),
    )
    dialog = dialogs.SettingsDialog(tk_app)
    dialog.withdraw()

    dialog._handle_reset_defaults()

    try:
        for key, (_entry, original) in dialog._fields.items():
            group, setting = key
            assert original == new_snapshot[group][setting]
        entry, _original = dialog._fields[("ui", "theme")]
        assert entry.get() == "light"
        assert infos
        assert infos[-1][1] == "Settings reset to defaults."
    finally:
        if dialog.winfo_exists():
            dialog._handle_cancel()


def test_settings_dialog_reset_defaults_failure_shows_error(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {"ui": {"theme": "dark"}}
    monkeypatch.setattr(
        dialogs.settings_manager,
        "get_settings_snapshot",
        lambda: deepcopy(snapshot),
    )
    monkeypatch.setattr(
        dialogs.settings_manager,
        "reset_user_settings_to_defaults",
        lambda: (_ for _ in ()).throw(OSError("nope")),
    )
    monkeypatch.setattr(dialogs.messagebox, "askyesno", lambda *args, **kwargs: True)
    errors: list[tuple[str, str]] = []
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dialogs.messagebox,
        "showerror",
        lambda *args: errors.append(args),
    )
    monkeypatch.setattr(
        dialogs.messagebox,
        "showinfo",
        lambda *args: infos.append(args),
    )
    dialog = dialogs.SettingsDialog(tk_app)
    dialog.withdraw()

    dialog._handle_reset_defaults()

    try:
        assert errors
        assert "Unable to reset settings" in errors[-1][1]
        assert not infos
    finally:
        if dialog.winfo_exists():
            dialog._handle_cancel()


def test_build_relationship_row_specs_handles_none_rows() -> None:
    assert dialogs.build_relationship_row_specs(None) == ()
    first_target_id = 10
    rows = dialogs.build_relationship_row_specs(
        [
            (first_target_id, "Aelin", "Mentor"),
            (11, "Nyx", ""),
        ],
    )
    assert rows[0].target_id == first_target_id
    assert rows[0].target_name == "Aelin"
    assert rows[1].relation_name == ""


def test_build_encounter_member_specs_normalizes_notes() -> None:
    assert dialogs.build_encounter_member_specs(None) == ()
    first_member_id = 5
    rows = dialogs.build_encounter_member_specs(
        [
            (first_member_id, "Rian", None),
            (6, "Seren", "Scout"),
        ],
    )
    assert rows[0].npc_id == first_member_id
    assert rows[0].npc_name == "Rian"
    assert rows[0].notes == ""
    assert rows[1].notes == "Scout"


def test_build_combo_box_state_prefers_current_option() -> None:
    state = dialogs.build_combo_box_state(["alpha", "beta"], " beta ")
    assert state.values == ("alpha", "beta")
    assert state.selected == "beta"


def test_build_combo_box_state_handles_empty_options() -> None:
    state = dialogs.build_combo_box_state([], "anything")
    assert state.values == ()
    assert state.selected == ""


class RelationshipManagerStub:
    def __init__(
        self,
        targets: Sequence[dialogs.NpcOption] | None = None,
    ) -> None:
        self.requested_source_id: int | None = None
        self.targets = tuple(targets or ())
        self.last_target_request: dict[str, object] | None = None

    def relationship_targets_for_campaign(
        self,
        campaign: str | None,
        *,
        exclude: Sequence[int] | None = None,
    ) -> list[dialogs.NpcOption]:
        self.last_target_request = {
            "campaign": campaign,
            "exclude": tuple(exclude or ()),
        }
        return list(self.targets)

    def fetch_relationship_rows(self, source_id: int) -> list[tuple[int, str, str]]:
        self.requested_source_id = source_id
        return [(999, "ignored", "ignored")]

    def upsert_relationship(
        self,
        source_id: int,
        target_id: int,
        relation_name: str,
    ) -> None:
        raise NotImplementedError

    def delete_relationship(self, source_id: int, target_id: int) -> None:
        raise NotImplementedError

    def on_relationship_dialog_close(
        self,
        dialog: dialogs.RelationshipDialog,
    ) -> None:
        raise NotImplementedError

    def fetch_encounter_members(
        self,
        encounter_id: int,
    ) -> list[tuple[int, str, str | None]]:
        return []

    def add_encounter_member(
        self,
        encounter_id: int,
        npc_id: int,
        notes: str,
    ) -> None:
        raise NotImplementedError

    def remove_encounter_member(self, encounter_id: int, npc_id: int) -> None:
        raise NotImplementedError

    def on_encounter_members_dialog_close(
        self,
        dialog: dialogs.EncounterMembersDialog,
    ) -> None:
        raise NotImplementedError


def test_relationship_dialog_reload_rows_uses_specs(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = dialogs.RelationshipDialog.__new__(dialogs.RelationshipDialog)
    manager = RelationshipManagerStub()
    dialog.manager = cast(dialogs.DialogManager, manager)
    dialog.source_name = "Aelin"
    source_id = 77
    dialog.source_id = source_id
    dialog._rows_frame = ctk.CTkScrollableFrame(tk_app)
    dialog._delete_icon = cast(ctk.CTkImage, None)
    sentinel = dialogs.RelationshipRowSpec(
        target_id=88,
        target_name="Quill",
        relation_name="Ally",
    )
    monkeypatch.setattr(
        dialogs,
        "build_relationship_row_specs",
        lambda _rows: (sentinel,),
    )

    dialog._reload_rows()

    try:
        assert manager.requested_source_id == source_id
        rows = dialog._rows_frame.winfo_children()
        assert len(rows) == 1
        labels = [
            child
            for child in rows[0].winfo_children()
            if isinstance(child, ctk.CTkLabel)
        ]
        assert labels[0].cget("text") == sentinel.target_name
        assert labels[1].cget("text") == sentinel.relation_name
    finally:
        dialog._rows_frame.destroy()


class EncounterManagerStub:
    def __init__(
        self,
        targets: Sequence[dialogs.NpcOption] | None = None,
    ) -> None:
        self.requested_id: int | None = None
        self.targets = tuple(targets or ())
        self.last_target_request: dict[str, object] | None = None

    def relationship_targets_for_campaign(
        self,
        campaign: str | None,
        *,
        exclude: Sequence[int] | None = None,
    ) -> list[dialogs.NpcOption]:
        self.last_target_request = {
            "campaign": campaign,
            "exclude": tuple(exclude or ()),
        }
        return list(self.targets)

    def fetch_relationship_rows(self, source_id: int) -> list[tuple[int, str, str]]:
        return []

    def upsert_relationship(
        self,
        source_id: int,
        target_id: int,
        relation_name: str,
    ) -> None:
        raise NotImplementedError

    def delete_relationship(self, source_id: int, target_id: int) -> None:
        raise NotImplementedError

    def on_relationship_dialog_close(
        self,
        dialog: dialogs.RelationshipDialog,
    ) -> None:
        raise NotImplementedError

    def fetch_encounter_members(
        self,
        encounter_id: int,
    ) -> list[tuple[int, str, str | None]]:
        self.requested_id = encounter_id
        return [(101, "ignored", None)]

    def add_encounter_member(
        self,
        encounter_id: int,
        npc_id: int,
        notes: str,
    ) -> None:
        raise NotImplementedError

    def remove_encounter_member(self, encounter_id: int, npc_id: int) -> None:
        raise NotImplementedError

    def on_encounter_members_dialog_close(
        self,
        dialog: dialogs.EncounterMembersDialog,
    ) -> None:
        raise NotImplementedError


def test_encounter_dialog_reload_rows_uses_specs(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = dialogs.EncounterMembersDialog.__new__(dialogs.EncounterMembersDialog)
    manager = EncounterManagerStub()
    dialog.manager = cast(dialogs.DialogManager, manager)
    encounter_id = 42
    dialog.encounter_id = encounter_id
    dialog._rows_frame = ctk.CTkScrollableFrame(tk_app)
    dialog._delete_icon = cast(ctk.CTkImage, None)
    dialog._current_members = set()
    sentinel = dialogs.EncounterMemberSpec(
        npc_id=91,
        npc_name="Nyx",
        notes="Scout",
    )
    monkeypatch.setattr(
        dialogs,
        "build_encounter_member_specs",
        lambda _rows: (sentinel,),
    )

    dialog._reload_rows()

    try:
        assert manager.requested_id == encounter_id
        assert dialog._current_members == {sentinel.npc_id}
        rows = dialog._rows_frame.winfo_children()
        assert len(rows) == 1
        labels = [
            child
            for child in rows[0].winfo_children()
            if isinstance(child, ctk.CTkLabel)
        ]
        assert labels[0].cget("text") == sentinel.npc_name
        assert labels[1].cget("text") == sentinel.notes
    finally:
        dialog._rows_frame.destroy()


class ComboStub:
    def __init__(self, value: str = "") -> None:
        self.configured_values: tuple[str, ...] = ()
        self.selected_value = value

    def configure(self, *, values: Sequence[str]) -> None:  # type: ignore[override]
        self.configured_values = tuple(values)

    def set(self, value: str) -> None:
        self.selected_value = value

    def get(self) -> str:
        return self.selected_value


def test_relationship_dialog_refresh_target_options_uses_combo_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = dialogs.RelationshipDialog.__new__(dialogs.RelationshipDialog)
    targets: tuple[dialogs.NpcOption, ...] = (
        dialogs.NpcOption(identifier=11, name="Quill", campaign="alpha"),
        dialogs.NpcOption(identifier=12, name="Nyx", campaign=None),
    )
    manager = RelationshipManagerStub(targets=targets)
    dialog.manager = cast(dialogs.DialogManager, manager)
    dialog.source_name = "Aelin"
    dialog.source_id = 70
    dialog.campaign = "alpha"
    dialog._target_option_map = {}
    selected_label = dialogs.format_npc_option_label(targets[1])
    combo_stub = ComboStub(selected_label)
    dialog._target_combo = cast(ctk.CTkComboBox, combo_stub)
    combo_state = dialogs.ComboBoxState(values=("Quill",), selected="Quill")
    captured: dict[str, object] = {}

    def fake_build(
        options: Sequence[str],
        current: str | None,
    ) -> dialogs.ComboBoxState:
        captured["options"] = tuple(options)
        captured["current"] = current
        return combo_state

    monkeypatch.setattr(dialogs, "build_combo_box_state", fake_build)

    dialog._refresh_target_options()

    expected_options = tuple(
        dialogs.format_npc_option_label(option) for option in manager.targets
    )
    assert captured["options"] == expected_options
    assert captured["current"] == selected_label
    assert combo_stub.configured_values == combo_state.values
    assert combo_stub.selected_value == combo_state.selected
    assert manager.last_target_request == {
        "campaign": "alpha",
        "exclude": (dialog.source_id,),
    }


def test_encounter_dialog_refresh_npc_options_uses_combo_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = dialogs.EncounterMembersDialog.__new__(dialogs.EncounterMembersDialog)
    targets: tuple[dialogs.NpcOption, ...] = (
        dialogs.NpcOption(identifier=15, name="Nyx", campaign="beta"),
        dialogs.NpcOption(identifier=16, name="Rian", campaign=None),
    )
    manager = EncounterManagerStub(targets=targets)
    dialog.manager = cast(dialogs.DialogManager, manager)
    dialog.campaign = "beta"
    existing_member_id = targets[0].identifier
    dialog._current_members = {existing_member_id}
    dialog._npc_option_map = {}
    selected_label = dialogs.format_npc_option_label(targets[0])
    combo_stub = ComboStub(selected_label)
    dialog._npc_combo = cast(ctk.CTkComboBox, combo_stub)
    combo_state = dialogs.ComboBoxState(values=("Rian",), selected="Rian")
    captured: dict[str, object] = {}

    def fake_build(
        options: Sequence[str],
        current: str | None,
    ) -> dialogs.ComboBoxState:
        captured["options"] = tuple(options)
        captured["current"] = current
        return combo_state

    monkeypatch.setattr(dialogs, "build_combo_box_state", fake_build)

    dialog._refresh_npc_options()

    expected_options = tuple(
        dialogs.format_npc_option_label(option) for option in manager.targets
    )
    assert captured["options"] == expected_options
    assert captured["current"] == selected_label
    assert combo_stub.configured_values == combo_state.values
    assert combo_stub.selected_value == combo_state.selected
    assert manager.last_target_request == {
        "campaign": "beta",
        "exclude": (existing_member_id,),
    }


def test_campaign_dialog_configure_status_combo_uses_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = CampaignDialog.__new__(CampaignDialog)
    combo_stub = ComboStub("Active")
    dialog._status_combo = cast(ctk.CTkComboBox, combo_stub)
    combo_state = dialogs.ComboBoxState(values=("Active", "Paused"), selected="Paused")
    captured: dict[str, object] = {}

    def fake_build(
        options: Sequence[str],
        current: str | None,
    ) -> dialogs.ComboBoxState:
        captured["options"] = tuple(options)
        captured["current"] = current
        return combo_state

    monkeypatch.setattr(dialogs, "build_combo_box_state", fake_build)

    dialog._configure_status_combo(["Active", "Paused"], "Paused")

    assert captured["options"] == ("Active", "Paused")
    assert captured["current"] == "Paused"
    assert combo_stub.configured_values == combo_state.values
    assert combo_stub.selected_value == combo_state.selected


def test_build_settings_group_specs_formats_and_sorts() -> None:
    snapshot = {
        "zeta_options": {"beta_flag": True, "alpha_value": 5},
        "alpha_settings": {"omega": "x"},
    }
    specs = dialogs.build_settings_group_specs(snapshot)
    assert [spec.key for spec in specs] == ["alpha_settings", "zeta_options"]
    assert specs[0].label == "alpha settings"
    assert [field.key for field in specs[0].fields] == ["omega"]
    assert specs[1].fields[0].label == "Alpha value"
    assert specs[1].fields[1].label == "Beta flag"


def test_settings_dialog_build_widgets_uses_group_specs(
    tk_app: ctk.CTk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_field = dialogs.SettingFieldSpec(
        key="hp_limit",
        label="HP Limit",
        original_value=7,
    )
    sentinel_group = dialogs.SettingGroupSpec(
        key="combat_rules",
        label="Combat Rules",
        fields=(sentinel_field,),
    )
    captured_snapshot: dict[str, object] = {}

    def fake_build(snapshot: dict[str, object]) -> tuple[dialogs.SettingGroupSpec, ...]:
        captured_snapshot.update(snapshot)
        return (sentinel_group,)

    sample_snapshot = {"combat_rules": {"hp_limit": 3}}
    monkeypatch.setattr(dialogs, "build_settings_group_specs", fake_build)
    monkeypatch.setattr(
        dialogs.settings_manager,
        "get_settings_snapshot",
        lambda: sample_snapshot,
    )

    dialog = dialogs.SettingsDialog(tk_app)
    dialog.withdraw()
    try:
        assert captured_snapshot == sample_snapshot
        field_key = (sentinel_group.key, sentinel_field.key)
        assert field_key in dialog._fields
        entry, original = dialog._fields[field_key]
        assert original == sentinel_field.original_value
        assert entry.get() == "7"
        section_frames = dialog._scroll_frame.winfo_children()
        assert section_frames, "expected at least one section frame"
        group_label = section_frames[0].winfo_children()[0]
        assert isinstance(group_label, ctk.CTkLabel)
        assert group_label.cget("text") == sentinel_group.label
    finally:
        dialog._handle_cancel()

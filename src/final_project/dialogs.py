"""Reusable dialog widgets for the Final Project GUI."""

from __future__ import annotations

# pyright: reportUnknownMemberType=false
import customtkinter as ctk  # type: ignore[import-untyped]
from lazi.core import lazi

from final_project import settings_manager
from final_project.db import CAMPAIGN_STATUSES

with lazi:  # type: ignore[attr-defined]
    import ast
    import json
    import tkinter as tk
    from collections.abc import Callable
    from collections.abc import Sequence
    from contextlib import suppress
    from datetime import UTC
    from datetime import datetime
    from tkinter import messagebox
    from typing import Any
    from typing import Protocol
    from typing import cast

    import structlog
    import tkfontawesome as tkfa  # type: ignore[import-untyped]
    from PIL import ImageTk

logger = structlog.getLogger("final_project")


class DialogManager(Protocol):
    """Structural contract expected from the main GUI window."""

    def relationship_targets_for_campaign(
        self,
        campaign: str | None,
        *,
        exclude: Sequence[str] | None = None,
    ) -> Sequence[str]:
        """Return NPC names available for the provided campaign context."""
        ...

    def fetch_relationship_rows(
        self,
        source_name: str,
    ) -> Sequence[tuple[str, str]]:
        """Fetch relationship tuples for the given NPC."""
        ...

    def upsert_relationship(
        self,
        source_name: str,
        target_name: str,
        relation_name: str,
    ) -> None:
        """Create or update the relationship between two NPCs."""
        ...

    def delete_relationship(self, source_name: str, target_name: str) -> None:
        """Remove the relationship between the two NPCs."""
        ...

    def on_relationship_dialog_close(self, dialog: RelationshipDialog) -> None:
        """Handle cleanup once the relationship dialog closes."""
        ...

    def fetch_encounter_members(
        self,
        encounter_id: int,
    ) -> Sequence[tuple[str, str | None]]:
        """Return encounter member rows for the given encounter id."""
        ...

    def add_encounter_member(
        self,
        encounter_id: int,
        npc_name: str,
        notes: str,
    ) -> None:
        """Attach the specified NPC to an encounter."""
        ...

    def remove_encounter_member(
        self,
        encounter_id: int,
        npc_name: str,
    ) -> None:
        """Detach the specified NPC from an encounter."""
        ...

    def on_encounter_members_dialog_close(
        self,
        dialog: EncounterMembersDialog,
    ) -> None:
        """Handle cleanup once the encounter members dialog closes."""
        ...


class LLMProgressDialog(ctk.CTkToplevel):
    """Modal progress window shown while waiting on the LLM."""

    def __init__(self, master: ctk.CTk) -> None:
        """Create the dialog shell and initial widgets."""
        super().__init__(master)
        self.title("Generating...")
        self.geometry("360x150")
        self.resizable(width=False, height=False)
        self.attributes("-topmost", 1)
        self._mode = "indeterminate"
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.status_label = ctk.CTkLabel(self, text="Contacting local LLM...")
        self.status_label.pack(padx=20, pady=(20, 10))
        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=(0, 20))
        self.progress.start()
        self.grab_set()

    def update_status(self, message: str, percent: float | None) -> None:
        """Mutate the UI to reflect streamed llamafile output."""
        if not self.winfo_exists():
            return
        truncated = message[-200:] if message else "Working..."
        self.status_label.configure(text=truncated)
        if percent is None:
            if self._mode != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start()
                self._mode = "indeterminate"
            return
        if self._mode != "determinate":
            self.progress.configure(mode="determinate")
            self.progress.stop()
            self._mode = "determinate"
        self.progress.set(max(0.0, min(1.0, percent / 100.0)))

    def close(self) -> None:
        """Dismiss the dialog safely."""
        if not self.winfo_exists():
            return
        if self._mode == "indeterminate":
            self.progress.stop()
        with suppress(tk.TclError):
            self.grab_release()
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """Scrollable dialog for editing user-configurable settings."""

    def __init__(
        self,
        master: ctk.CTk,
        *,
        on_settings_saved: Callable[[dict[str, Any]], None] | None = None,
        on_close: Callable[[SettingsDialog], None] | None = None,
    ) -> None:
        """Create the settings dialog shell and dynamic form."""
        super().__init__(master)
        self.title("Settings")
        self.geometry("520x520")
        self.resizable(width=False, height=False)
        self.transient(master)
        self._on_settings_saved = on_settings_saved
        self._on_close = on_close
        self._fields: dict[tuple[str, str], tuple[ctk.CTkEntry, Any]] = {}
        self._settings_snapshot = settings_manager.get_settings_snapshot()

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self._handle_cancel())

    def _build_widgets(self) -> None:
        heading_font = ctk.CTkFont(size=18, weight="bold")
        group_font = ctk.CTkFont(size=14, weight="bold")
        ctk.CTkLabel(
            self,
            text="Application Settings",
            font=heading_font,
            anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 10))

        self._scroll_frame = ctk.CTkScrollableFrame(self, height=360, width=460)
        self._scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        if not self._settings_snapshot:
            ctk.CTkLabel(
                self._scroll_frame,
                text="No configurable settings were found.",
                anchor="w",
            ).pack(fill="x", padx=10, pady=10)
        else:
            for group in sorted(self._settings_snapshot):
                group_values = self._settings_snapshot[group]
                section = ctk.CTkFrame(self._scroll_frame, fg_color="transparent")
                section.pack(fill="x", expand=True, padx=5, pady=(0, 12))
                ctk.CTkLabel(
                    section,
                    text=self._format_group_name(group),
                    font=group_font,
                    anchor="w",
                ).pack(fill="x", pady=(0, 6))
                for key in sorted(group_values):
                    value = group_values[key]
                    row = ctk.CTkFrame(section, fg_color="transparent")
                    row.pack(fill="x", pady=(0, 6))
                    ctk.CTkLabel(
                        row,
                        text=self._format_key_label(key),
                        width=190,
                        anchor="w",
                    ).pack(side="left")
                    entry = ctk.CTkEntry(row)
                    entry.insert(0, self._stringify_value(value))
                    entry.pack(side="left", fill="x", expand=True, padx=(10, 0))
                    self._fields[(group, key)] = (entry, value)

        actions = ctk.CTkFrame(self)
        actions.pack(fill="x", padx=20, pady=(0, 20))
        reset_btn = ctk.CTkButton(
            actions,
            text="Reset to Defaults",
            command=self._handle_reset_defaults,
        )
        reset_btn.pack(side="left")
        cancel_btn = ctk.CTkButton(actions, text="Cancel", command=self._handle_cancel)
        cancel_btn.pack(side="right", padx=(10, 0))
        self._save_btn = ctk.CTkButton(
            actions,
            text="Save",
            command=self._handle_save,
            state="normal" if self._fields else "disabled",
        )
        self._save_btn.pack(side="right")

    def _handle_save(self) -> None:
        updated_settings = settings_manager.get_settings_snapshot()
        for (group, key), (entry, original) in self._fields.items():
            display_name = (
                f"{self._format_group_name(group)} / {self._format_key_label(key)}"
            )
            try:
                parsed_value = self._convert_value(entry.get(), original)
            except ValueError as exc:
                messagebox.showerror("Settings", f"{display_name}: {exc}")
                entry.focus_set()
                entry.select_range(0, tk.END)
                return
            bucket = updated_settings.setdefault(group, {})
            bucket[key] = parsed_value
        saved = settings_manager.save_settings(updated_settings)
        if self._on_settings_saved is not None:
            self._on_settings_saved(saved)
        messagebox.showinfo("Settings", "Settings saved successfully.")
        self._close()

    def _handle_cancel(self) -> None:
        self._close()

    def _handle_reset_defaults(self) -> None:
        if not messagebox.askyesno(
            "Settings",
            (
                "Reset all settings to their defaults?\n\n"
                "This will remove your custom settings file."
            ),
            icon="warning",
        ):
            return
        try:
            defaults = settings_manager.reset_user_settings_to_defaults()
        except OSError as exc:
            logger.exception("failed to reset settings to defaults")
            messagebox.showerror(
                "Settings",
                f"Unable to reset settings: {exc}",
            )
            return
        self._settings_snapshot = defaults
        for key, (entry, _original) in self._fields.items():
            group, setting = key
            updated_value = defaults.get(group, {}).get(setting)
            entry.delete(0, tk.END)
            if updated_value is not None:
                entry.insert(0, self._stringify_value(updated_value))
            self._fields[key] = (entry, updated_value)
        messagebox.showinfo("Settings", "Settings reset to defaults.")

    def _close(self) -> None:
        if not self.winfo_exists():
            return
        with suppress(tk.TclError):
            self.grab_release()
        if self._on_close is not None:
            self._on_close(self)
        self.destroy()

    def _format_group_name(self, name: str) -> str:
        return name.replace("_", " ")

    def _format_key_label(self, key: str) -> str:
        return key.replace("_", " ").capitalize()

    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def _convert_value(self, raw_value: str, original: Any) -> Any:
        text = raw_value.strip()
        result: Any
        if isinstance(original, bool):
            result = self._parse_bool(text)
        elif isinstance(original, int) and not isinstance(original, bool):
            result = self._parse_int(text)
        elif isinstance(original, float):
            result = self._parse_float(text)
        elif isinstance(original, (list, tuple, dict)):
            result = self._parse_literal(raw_value)
        elif original is None:
            if text == "":
                result = None
            else:
                result = self._parse_literal(raw_value, default=raw_value)
        else:
            result = raw_value
        return result

    def _parse_bool(self, text: str) -> bool:
        lowered = text.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        msg = "enter true or false"
        raise ValueError(msg)

    def _parse_int(self, text: str) -> int:
        if text == "":
            msg = "enter an integer value"
            raise ValueError(msg)
        return int(text)

    def _parse_float(self, text: str) -> float:
        if text == "":
            msg = "enter a numeric value"
            raise ValueError(msg)
        return float(text)

    def _parse_literal(self, raw_value: str, *, default: Any | None = None) -> Any:
        try:
            return ast.literal_eval(raw_value)
        except (ValueError, SyntaxError) as exc:
            if default is not None:
                return default
            msg = "enter a valid Python literal (e.g. [1, 2])"
            raise ValueError(msg) from exc


class RelationshipDialog(ctk.CTkToplevel):
    """Detached window for managing NPC relationships."""

    def __init__(
        self,
        manager: DialogManager,
        source_name: str,
        campaign: str | None,
    ) -> None:
        """Build the relationship dialog and load the current NPC context."""
        super().__init__(manager)
        self.manager: DialogManager = manager
        self.source_name = source_name
        self.campaign = campaign
        trash_photo = tkfa.icon_to_image(
            "trash",
            fill="white",
            scale_to_height=16,
        )
        self._delete_icon = ctk.CTkImage(
            light_image=ImageTk.getimage(cast(Any, trash_photo)),
            size=(16, 16),
        )

        self.title("Relationships")
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.update_context(source_name, campaign)
        self.grab_set()

    def _build_layout(self) -> None:
        self._header_label = ctk.CTkLabel(
            self,
            text="Relationships",
            font=("Arial", 16, "bold"),
        )
        self._header_label.pack(fill="x", pady=(0, 10))

        table_frame = ctk.CTkFrame(self)
        table_frame.pack(fill="both", expand=True)

        header_row = ctk.CTkFrame(table_frame)
        header_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(header_row, text="Name", anchor="w").pack(
            side="left",
            expand=True,
            fill="x",
        )
        ctk.CTkLabel(header_row, text="Type", anchor="w").pack(
            side="left",
            expand=True,
            fill="x",
        )
        ctk.CTkLabel(header_row, text="Actions", anchor="center", width=70).pack(
            side="left",
            padx=(5, 0),
        )

        self._rows_frame = ctk.CTkScrollableFrame(table_frame, height=240)
        self._rows_frame.pack(fill="both", expand=True)

        controls = ctk.CTkFrame(self)
        controls.pack(fill="x", pady=(10, 0))

        self._target_combo = ctk.CTkComboBox(controls, values=[], state="readonly")
        self._target_combo.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self._type_entry = ctk.CTkEntry(
            controls,
            placeholder_text="Relationship Type",
        )
        self._type_entry.pack(side="left", expand=True, fill="x", padx=(0, 10))

        add_btn = ctk.CTkButton(controls, text="Add", command=self._handle_add)
        add_btn.pack(side="left")

    def update_context(self, source_name: str, campaign: str | None) -> None:
        """Refresh the dialog contents for a different NPC or campaign."""
        self.source_name = source_name
        self.campaign = campaign
        self._header_label.configure(text=f"Relationships - {source_name}")
        self._refresh_target_options()
        self._reload_rows()

    def _refresh_target_options(self) -> None:
        values = self.manager.relationship_targets_for_campaign(
            self.campaign,
            exclude=[self.source_name],
        )
        self._target_combo.configure(values=values)
        if not values:
            self._target_combo.set("")
            return
        current = self._target_combo.get()
        if current and current in values:
            self._target_combo.set(current)
            return
        self._target_combo.set(values[0])

    def _reload_rows(self) -> None:
        for child in self._rows_frame.winfo_children():
            child.destroy()
        rows = self.manager.fetch_relationship_rows(self.source_name)
        if not rows:
            ctk.CTkLabel(
                self._rows_frame,
                text="No relationships recorded.",
                anchor="w",
            ).pack(fill="x", padx=5, pady=5)
            return
        for target, relation in rows:
            row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=2)
            ctk.CTkLabel(row, text=target, anchor="w").pack(
                side="left",
                expand=True,
                fill="x",
            )
            ctk.CTkLabel(row, text=relation, anchor="w").pack(
                side="left",
                expand=True,
                fill="x",
            )
            delete_btn = ctk.CTkButton(
                row,
                text="",
                width=36,
                image=self._delete_icon,
                command=lambda target_name=target: self._handle_delete(target_name),
            )
            delete_btn.pack(side="left", padx=(5, 0))

    def _handle_add(self) -> None:
        target_name = self._target_combo.get().strip()
        relation_name = self._type_entry.get().strip()
        if not target_name:
            messagebox.showerror("Relationships", "Select an NPC to relate to.")
            return
        if not relation_name:
            messagebox.showerror("Relationships", "Enter a relationship type.")
            return
        try:
            self.manager.upsert_relationship(
                self.source_name,
                target_name,
                relation_name,
            )
        except ValueError as exc:
            messagebox.showerror("Relationships", str(exc))
            return
        except RuntimeError as exc:
            logger.exception("failed to save relationship")
            messagebox.showerror("Relationships", str(exc))
            return
        self._type_entry.delete(0, tk.END)
        self._reload_rows()

    def _handle_delete(self, target_name: str) -> None:
        try:
            self.manager.delete_relationship(self.source_name, target_name)
        except RuntimeError as exc:
            logger.exception("failed to delete relationship")
            messagebox.showerror("Relationships", str(exc))
            return
        self._reload_rows()

    def _handle_close(self) -> None:
        self.manager.on_relationship_dialog_close(self)
        self.destroy()


class EncounterMembersDialog(ctk.CTkToplevel):
    """Modal dialog for editing encounter participants."""

    def __init__(
        self,
        manager: DialogManager,
        encounter_id: int,
        campaign: str | None,
    ) -> None:
        """Initialize the encounter members dialog for a specific encounter."""
        super().__init__(manager)
        self.manager: DialogManager = manager
        self.encounter_id = encounter_id
        self.campaign = campaign
        self._current_members: set[str] = set()

        trash_photo = tkfa.icon_to_image(
            "trash",
            fill="white",
            scale_to_height=16,
        )
        self._delete_icon = ctk.CTkImage(
            light_image=ImageTk.getimage(cast(Any, trash_photo)),
            size=(16, 16),
        )

        self.title("Encounter Members")
        self.resizable(width=False, height=False)
        self.transient(manager)  # type: ignore[arg-type]
        self.configure(padx=20, pady=10)

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.update_context(encounter_id, campaign)
        self.grab_set()

    def _build_layout(self) -> None:
        self._header_label = ctk.CTkLabel(
            self,
            text="Encounter Members",
            font=("Arial", 16, "bold"),
        )
        self._header_label.pack(fill="x", pady=(0, 10))

        table_frame = ctk.CTkFrame(self)
        table_frame.pack(fill="both", expand=True)

        header_row = ctk.CTkFrame(table_frame)
        header_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(header_row, text="NPC", anchor="w").pack(
            side="left",
            expand=True,
            fill="x",
        )
        ctk.CTkLabel(header_row, text="Notes", anchor="w").pack(
            side="left",
            expand=True,
            fill="x",
        )
        ctk.CTkLabel(header_row, text="Actions", anchor="center", width=70).pack(
            side="left",
            padx=(5, 0),
        )

        self._rows_frame = ctk.CTkScrollableFrame(table_frame, height=240)
        self._rows_frame.pack(fill="both", expand=True)

        controls = ctk.CTkFrame(self)
        controls.pack(fill="x", pady=(10, 0))

        self._npc_combo = ctk.CTkComboBox(controls, values=[], state="readonly")
        self._npc_combo.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self._notes_entry = ctk.CTkTextbox(controls, height=80)
        self._notes_entry.pack(side="left", expand=True, fill="both", padx=(0, 10))

        add_btn = ctk.CTkButton(controls, text="Add", command=self._handle_add)
        add_btn.pack(side="left")

    def update_context(self, encounter_id: int, campaign: str | None) -> None:
        """Refresh available NPCs and member rows for the encounter."""
        self.encounter_id = encounter_id
        self.campaign = campaign
        if encounter_id:
            header = f"Encounter Members - #{encounter_id}"
        else:
            header = "Encounter Members (unsaved)"
        self._header_label.configure(text=header)
        self._reload_rows()
        self._refresh_npc_options()

    def _refresh_npc_options(self) -> None:
        values = self.manager.relationship_targets_for_campaign(
            self.campaign,
            exclude=tuple(self._current_members),
        )
        self._npc_combo.configure(values=values)
        current = self._npc_combo.get().strip()
        if values and current in values:
            self._npc_combo.set(current)
        elif values:
            self._npc_combo.set(values[0])
        else:
            self._npc_combo.set("")

    def _reload_rows(self) -> None:
        for child in self._rows_frame.winfo_children():
            child.destroy()
        rows = self.manager.fetch_encounter_members(self.encounter_id)
        self._current_members = {name for name, _ in rows}
        if not rows:
            ctk.CTkLabel(
                self._rows_frame,
                text="No participants assigned to this encounter.",
                anchor="w",
            ).pack(fill="x", padx=5, pady=5)
            return
        for npc_name, notes in rows:
            row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=2)
            ctk.CTkLabel(row, text=npc_name, anchor="w").pack(
                side="left",
                expand=True,
                fill="x",
            )
            ctk.CTkLabel(row, text=notes or "", anchor="w", wraplength=260).pack(
                side="left",
                expand=True,
                fill="x",
            )
            delete_btn = ctk.CTkButton(
                row,
                text="",
                width=36,
                image=self._delete_icon,
                command=lambda name=npc_name: self._handle_remove(name),
            )
            delete_btn.pack(side="left", padx=(5, 0))

    def _handle_add(self) -> None:
        npc_name = self._npc_combo.get().strip()
        notes = self._notes_entry.get("1.0", tk.END).strip()
        if not npc_name:
            messagebox.showerror("Encounter Members", "Select an NPC to add.")
            return
        try:
            self.manager.add_encounter_member(self.encounter_id, npc_name, notes)
        except ValueError as exc:
            messagebox.showerror("Encounter Members", str(exc))
            return
        except RuntimeError as exc:
            logger.exception("failed to add encounter member")
            messagebox.showerror("Encounter Members", str(exc))
            return
        self._notes_entry.delete("1.0", tk.END)
        self._reload_rows()
        self._refresh_npc_options()

    def _handle_remove(self, npc_name: str) -> None:
        try:
            self.manager.remove_encounter_member(self.encounter_id, npc_name)
        except RuntimeError as exc:
            logger.exception("failed to remove encounter member")
            messagebox.showerror("Encounter Members", str(exc))
            return
        self._reload_rows()
        self._refresh_npc_options()

    def _handle_close(self) -> None:
        self.manager.on_encounter_members_dialog_close(self)
        self.destroy()


class FactionDialog(ctk.CTkToplevel):
    """Modal dialog used to capture new faction details."""

    def __init__(
        self,
        manager: DialogManager,
        initial_name: str,
        campaign: str,
        on_submit: Callable[[str, str, str], None],
        on_cancel: Callable[[], None] | None = None,
        **dialog_options: Any,
    ) -> None:
        """Initialize dialog widgets and register callbacks."""
        super().__init__(manager)
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        dialog_title = dialog_options.get("dialog_title")
        save_button_label = dialog_options.get("save_button_label", "Save")
        allow_name_edit = dialog_options.get("allow_name_edit", True)
        initial_description = dialog_options.get("initial_description", "")
        initial_notes = dialog_options.get("initial_notes", "")

        self.title(dialog_title or "New Faction")
        self.resizable(width=False, height=False)
        self.transient(manager)  # type: ignore[arg-type]
        self.grab_set()

        self._campaign_label = ctk.CTkLabel(
            self,
            text=f"Campaign: {campaign}",
            font=("Arial", 14, "bold"),
        )
        self._campaign_label.pack(fill="x", padx=20, pady=(15, 5))

        form = ctk.CTkFrame(self)
        form.pack(fill="both", expand=True, padx=20, pady=10)

        ctk.CTkLabel(form, text="Faction Name:").pack(anchor="w")
        self._name_entry = ctk.CTkEntry(form)
        self._name_entry.pack(fill="x", pady=(0, 10))
        self._name_entry.insert(0, initial_name)
        self._allow_name_edit = allow_name_edit
        if not allow_name_edit:
            self._name_entry.configure(state="disabled")

        ctk.CTkLabel(form, text="Description:").pack(anchor="w")
        self._description = ctk.CTkTextbox(form, height=120)
        self._description.pack(fill="both", expand=True, pady=(0, 10))
        if initial_description:
            self._description.insert("1.0", initial_description)

        ctk.CTkLabel(form, text="Membership Notes:").pack(anchor="w")
        self._notes = ctk.CTkTextbox(form, height=80)
        self._notes.pack(fill="both", expand=True)
        if initial_notes:
            self._notes.insert("1.0", initial_notes)

        buttons = ctk.CTkFrame(self)
        buttons.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkButton(buttons, text="Cancel", command=self._handle_cancel).pack(
            side="right",
            padx=(0, 10),
        )
        self._save_btn = ctk.CTkButton(
            buttons,
            text=save_button_label,
            command=self._handle_submit,
        )
        self._save_btn.pack(side="right")

        self.bind("<Return>", lambda event: self._handle_submit())  # noqa: ARG005
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)

    def _handle_submit(self) -> None:
        name = self._name_entry.get().strip()
        description = self._description.get("1.0", tk.END).strip()
        notes = self._notes.get("1.0", tk.END).strip()
        if not name:
            messagebox.showerror("Faction", "Enter a faction name.")
            return
        self._on_submit(name, description, notes)
        self.destroy()

    def _handle_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()
        self.destroy()

    def update_context(
        self,
        initial_name: str,
        campaign: str,
        *,
        dialog_options: dict[str, Any] | None = None,
    ) -> None:
        """Refresh dialog contents when reused via the dialog tracker."""
        options = dialog_options or {}
        dialog_title = cast(str | None, options.get("dialog_title"))
        save_button_label = cast(str | None, options.get("save_button_label"))
        allow_name_edit = options.get("allow_name_edit")
        initial_description = cast(str | None, options.get("initial_description"))
        initial_notes = cast(str | None, options.get("initial_notes"))

        if dialog_title:
            self.title(dialog_title)
        self._campaign_label.configure(text=f"Campaign: {campaign}")

        effective_allow_edit = (
            self._allow_name_edit if allow_name_edit is None else bool(allow_name_edit)
        )
        self._allow_name_edit = effective_allow_edit
        self._name_entry.configure(state="normal")
        self._name_entry.delete(0, tk.END)
        self._name_entry.insert(0, initial_name)
        if not effective_allow_edit:
            self._name_entry.configure(state="disabled")

        self._description.delete("1.0", tk.END)
        if initial_description:
            self._description.insert("1.0", initial_description)

        self._notes.delete("1.0", tk.END)
        if initial_notes:
            self._notes.insert("1.0", initial_notes)

        if save_button_label:
            self._save_btn.configure(text=save_button_label)


class CampaignDialog(ctk.CTkToplevel):
    """Modal dialog to capture new campaign information."""

    def __init__(
        self,
        master: ctk.CTk,
        *,
        on_submit: Callable[[str, str, str], None],
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Build the modal UI and register callbacks for submit/cancel."""
        super().__init__(master)
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self.title("New Campaign")
        self.resizable(width=False, height=False)
        self.transient(master)
        self.grab_set()

        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(container, text="Campaign Name:").pack(anchor="w")
        self._name_entry = ctk.CTkEntry(container)
        self._name_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(container, text="Start Date (YYYY-MM-DD):").pack(anchor="w")
        self._date_entry = ctk.CTkEntry(container)
        today_text = datetime.now(UTC).date().isoformat()
        self._date_entry.insert(0, today_text)
        self._date_entry.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(container, text="Status:").pack(anchor="w")
        self._status_combo = ctk.CTkComboBox(
            container,
            values=list(CAMPAIGN_STATUSES),
            state="readonly",
        )
        status_combo = cast(Any, self._status_combo)
        status_combo.set(CAMPAIGN_STATUSES[0])
        self._status_combo.pack(fill="x", pady=(0, 10))

        button_row = ctk.CTkFrame(container)
        button_row.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(button_row, text="Cancel", command=self._handle_cancel).pack(
            side="right",
            padx=(0, 10),
        )
        ctk.CTkButton(button_row, text="Create", command=self._handle_submit).pack(
            side="right",
        )

        self.bind("<Return>", lambda event: self._handle_submit())  # noqa: ARG005
        self.protocol("WM_DELETE_WINDOW", self._handle_cancel)
        self._name_entry.focus_set()

    def _handle_submit(self) -> None:
        name = self._name_entry.get().strip()
        start_date = self._date_entry.get().strip()
        status_combo = cast(Any, self._status_combo)
        status = status_combo.get().strip().upper()
        if not name:
            messagebox.showerror("New Campaign", "Enter a campaign name.")
            return
        if not start_date:
            messagebox.showerror("New Campaign", "Enter a start date.")
            return
        if not status:
            messagebox.showerror("New Campaign", "Select a campaign status.")
            return
        self._on_submit(name, start_date, status)

    def _handle_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()
        self.destroy()

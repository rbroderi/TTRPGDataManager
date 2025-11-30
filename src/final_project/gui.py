"""Holds the user interface classes and functions."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Protocol, runtime_checkable

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownLambdaType=false
# ruff: noqa: FBT003, I001
from lazi.core import lazi
import customtkinter as ctk  # type: ignore[import-untyped]
from customtkinter.windows.widgets.ctk_entry import (  # type: ignore[import-untyped]
    CTkEntry,
)
from final_project import version
from final_project.dialogs import EncounterMembersDialog
from final_project.dialogs import FactionDialog
from final_project.dialogs import LLMProgressDialog
from final_project.dialogs import RelationshipDialog
from final_project.dialogs import SettingsDialog
from final_project.logic import DataLogic
from final_project.logic import DuplicateRecordError
from final_project.logic import FieldSpec
from final_project.llmrunner import LLMAssetDownloadSpec
from final_project.llmrunner import LLM_DOWNLOAD_SIZE_GB
from final_project.llmrunner import did_text_llm_server_fail
from final_project.llmrunner import download_llm_asset
from final_project.llmrunner import generate_portrait_from_image_llm
from final_project.llmrunner import get_llm_asset_requirements
from final_project.llmrunner import get_missing_llm_assets
from final_project.llmrunner import get_random_name_from_text_llm
from final_project.llmrunner import is_text_llm_server_ready
from final_project.llmrunner import reload_image_generation_defaults
from final_project.llmrunner import start_text_llm_server_async
from final_project.widgets import AppMenuBar
from final_project.widgets import HtmlPreviewWindow
from final_project.widgets import RadioField
from final_project.widgets import RandomIcon

with lazi:  # type: ignore[attr-defined]
    import json
    import threading
    import logging
    import re
    import sys
    import textwrap
    import tkinter as tk
    from enum import Enum
    from tkinter import filedialog
    from tkinter import font as tkfont
    from io import BytesIO
    from collections.abc import Callable, Sequence
    from datetime import date as dtdate
    from pathlib import Path
    from tkinter import Event
    from tkinter import messagebox
    from typing import Any
    from typing import NamedTuple
    from typing import cast
    from PIL import Image
    from PIL import UnidentifiedImageError
    import pyphen
    import structlog
    from pygments import lex
    from pygments.lexers import get_lexer_by_name  # pyright: ignore[reportUnknownVariableType]
    from pygments.token import Token
    from mistletoe import markdown as render_markdown

    # Pillow 10+ removed Image.ANTIALIAS but tkhtmlview still references it when
    # resizing images inside the README preview. Reintroduce the alias so the
    # embedded HTML renderer keeps working across Pillow releases.
    if not hasattr(Image, "ANTIALIAS") and hasattr(Image, "Resampling"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]

# disable debug in pillow
pil_logger = logging.getLogger("PIL")
pil_logger.setLevel(logging.INFO)

logger = structlog.getLogger("final_project")

SCRIPTROOT = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPTROOT / ".." / ".." / "project").resolve() / ".."
PLACEHOLDER_IMG = PROJECT_ROOT / "data" / "img" / "placeholder.png"
SOFT_HYPHEN = "\u00ad"
WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
LOAD_PAUSE: Annotated[int, "ms"] = 2500
LLM_POLL_INTERVAL: Annotated[int, "ms"] = 1000

type EntryWidget = CTkEntry | ctk.CTkComboBox | ctk.CTkTextbox | RadioField


@dataclass(slots=True)
class ButtonRowSpec:
    """Describe a label/button pair rendered in a single row."""

    label: str
    button_text: str
    command: Callable[[], None]
    width: int = 150


@dataclass(slots=True)
class RelationshipDialogContext:
    """Hold the NPC/campaign pair used when opening the relationships dialog."""

    source_name: str
    campaign: str | None


@dataclass(slots=True)
class EncounterDialogContext:
    """Encapsulate encounter dialog parameters."""

    encounter_id: int
    campaign: str | None


@dataclass(slots=True)
class FactionDialogContext:
    """Store staged faction dialog metadata and callbacks."""

    initial_name: str
    campaign: str
    on_submit: Callable[[str, str, str], None]
    on_cancel: Callable[[], None] | None
    dialog_options: dict[str, Any]


@dataclass(slots=True)
class ReadmeDialogContext:
    """Track README preview HTML and its source path."""

    html_output: str
    readme_path: Path


@dataclass(slots=True)
class _ImageRequestContext:
    """Describe an image generation request for the overlay icon."""

    title: str
    progress_message: str
    empty_prompt_message: str
    success_message: str
    prompt_builder: Callable[[], str]


@runtime_checkable
class _ManagedDialog(Protocol):
    def winfo_exists(self) -> bool: ...

    def deiconify(self) -> None: ...

    def lift(self) -> None: ...

    def destroy(self) -> None: ...


class _DialogTracker[DialogT: _ManagedDialog, ContextT]:
    """Manage opening, refreshing, and clearing a tkinter dialog instance."""

    __slots__ = (
        "_builder",
        "_dialog",
        "_get_context",
        "_name",
        "_updater",
    )

    def __init__(
        self,
        *,
        name: str,
        context_getter: Callable[[bool], ContextT | None],
        builder: Callable[[ContextT], DialogT],
        updater: Callable[[DialogT, ContextT], None],
    ) -> None:
        self._name = name
        self._get_context = context_getter
        self._builder = builder
        self._updater = updater
        self._dialog: DialogT | None = None

    def show(self) -> None:
        """Display the dialog, creating it on demand."""
        context = self._get_context(False)
        if context is None:
            return
        dialog = self._dialog
        if dialog is not None and dialog.winfo_exists():
            self._updater(dialog, context)
            dialog.deiconify()
            dialog.lift()
            return
        self._spawn_dialog(context)

    def refresh(self) -> None:
        """Update the dialog or destroy it if context vanished."""
        dialog = self._dialog
        if dialog is None:
            return
        if not dialog.winfo_exists():
            self._dialog = None
            return
        context = self._get_context(True)
        if context is None:
            dialog.destroy()
            self._dialog = None
            return
        self._updater(dialog, context)

    def clear(self, dialog: DialogT) -> None:
        """Forget the cached dialog reference when it closes."""
        if self._dialog is dialog:
            self._dialog = None

    def _spawn_dialog(self, context: ContextT) -> None:
        try:
            dialog = self._builder(context)
        except Exception:
            self._dialog = None
            raise
        self._dialog = dialog

    def current_dialog(self) -> DialogT | None:
        """Return the active dialog instance if one exists."""
        return self._dialog


class _NPCFormState:
    """Track NPC-only widgets while building a form."""

    __slots__ = ("faction_widget", "relationship_inserted")

    def __init__(self) -> None:
        self.relationship_inserted = False
        self.faction_widget: ctk.CTkComboBox | None = None


class _LLMServerStatus(Enum):
    READY = "ready"
    FAILED = "failed"
    WAITING = "waiting"


def init() -> None:
    """Initialize gui."""
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme(
        str((PROJECT_ROOT / "data" / "sun_valleyish.json").resolve()),
    )
    app = TTRPGDataManager()
    app.mainloop()


class Img:
    """Holds image data for use with CTK."""

    __slots__ = ("aspect_ratio", "ctkimage", "pil")

    def __init__(
        self,
        source: Path | bytes | bytearray | memoryview | Image.Image,
        width: int,
        height: int,
    ) -> None:
        """Initialize, size is set to max of width, height, keeping aspect ratio."""
        self.pil = self._load_image(source)
        self.aspect_ratio = self.pil.width / self.pil.height
        self.resize(width, height)

    @staticmethod
    def _load_image(
        source: Path | bytes | bytearray | memoryview | Image.Image,
    ) -> Image.Image:
        if isinstance(source, Image.Image):
            return source
        if isinstance(source, Path):
            return Image.open(source)
        return Image.open(BytesIO(bytes(source)))

    def resize(self, width: int, height: int) -> None:
        """Resize image while preserving aspect ratio and avoiding cropping."""
        # Compute new size that fits inside (width, height)

        if width / height > self.aspect_ratio:
            # Height is limiting
            new_height = height
            new_width = int(new_height * self.aspect_ratio)
        else:
            # Width is limiting
            new_width = width
            new_height = int(new_width / self.aspect_ratio)

        new_height = max(120, new_height - 120)  # padding 20 comes from frame padding
        self.ctkimage = ctk.CTkImage(
            light_image=self.pil,
            dark_image=self.pil,
            size=(new_width, new_height),
        )


class Size(NamedTuple):
    """Holds wxh."""

    width: int
    height: int


class TTRPGDataManager(ctk.CTk):  # type: ignore[misc]
    """Main gui class."""

    def __init__(self, delay: int = LOAD_PAUSE) -> None:  # noqa: PLR0915
        """Initialize the main gui class."""
        super().__init__()
        self.title("TTRPG Data Manager")
        size = (900, 650)
        self.geometry("x".join(map(str, size)))
        self.wm_minsize(width=size[0], height=size[1] + 175)  # minimum size

        self.resizable(True, True)
        self.min_change_threshold = 10
        self._last_size = Size(*size)
        self.placeholder_img = Img(PLACEHOLDER_IMG, 400, 400)
        self._image_width_cap = 400
        self._image_height_cap = 400
        self._field_overlay_icons: dict[str, list[RandomIcon]] = {}
        self._image_overlay_icon: RandomIcon | None = None
        self._image_generation_in_progress = False
        self._active_image_request: _ImageRequestContext | None = None
        self.logic = DataLogic()
        self._hyphenator = pyphen.Pyphen(lang="en_US")
        self._search_results: list[Any] = []
        self._search_index: int = -1
        self._results_entry_type: str | None = None
        self._pending_changes: dict[tuple[str, str], dict[str, Any]] = {}
        self._pending_images: dict[tuple[str, str], bytes] = {}
        self._pending_faction_changes: dict[tuple[str, str], tuple[str, str]] = {}
        self._pending_faction_for_new_record: tuple[str, str] | None = None
        self._pending_faction_context: FactionDialogContext | None = None
        self._current_record_key: tuple[str, str] | None = None
        self._current_image_payload: bytes | None = None
        self._image_dirty = False
        self._form_specs = self.logic.build_form_field_map()
        self._relationship_dialogs = _DialogTracker[
            RelationshipDialog,
            RelationshipDialogContext,
        ](
            name="Relationships",
            context_getter=lambda silent: self._relationship_dialog_context(
                silent=silent,
            ),
            builder=self._build_relationship_dialog,
            updater=lambda dialog, ctx: dialog.update_context(
                ctx.source_name,
                ctx.campaign,
            ),
        )
        self._encounter_dialogs = _DialogTracker[
            EncounterMembersDialog,
            EncounterDialogContext,
        ](
            name="Encounter Members",
            context_getter=lambda silent: self._encounter_dialog_context(
                silent=silent,
            ),
            builder=self._build_encounter_dialog,
            updater=lambda dialog, ctx: dialog.update_context(
                ctx.encounter_id,
                ctx.campaign,
            ),
        )
        self._npc_faction_widget: ctk.CTkComboBox | None = None
        self._faction_view_button: ctk.CTkButton | None = None
        self._faction_dialogs = _DialogTracker[
            FactionDialog,
            FactionDialogContext,
        ](
            name="Faction",
            context_getter=lambda silent: self._faction_dialog_context(
                silent=silent,
            ),
            builder=self._build_faction_dialog,
            updater=self._update_faction_dialog,
        )
        self._current_faction_value: str | None = None
        self._current_faction_note: str = ""
        self._staged_faction_assignment: tuple[str, str] | None = None
        self._pending_readme_context: ReadmeDialogContext | None = None
        self._last_readme_context: ReadmeDialogContext | None = None
        self._readme_dialogs = _DialogTracker[
            HtmlPreviewWindow,
            ReadmeDialogContext,
        ](
            name="README",
            context_getter=lambda silent: self._readme_dialog_context(
                silent=silent,
            ),
            builder=self._build_readme_window,
            updater=lambda dialog, ctx: dialog.load_content(
                ctx.html_output,
                ctx.readme_path,
            ),
        )
        self._settings_dialogs = _DialogTracker[
            SettingsDialog,
            bool,
        ](
            name="Settings",
            context_getter=lambda _silent: True,
            builder=self._build_settings_dialog,
            updater=self._update_settings_dialog,
        )
        self._llm_ready = self._get_llm_server_status() is _LLMServerStatus.READY
        self._llm_watch_job: str | None = None
        self._llm_server_started = False
        self._llm_download_in_progress = False
        self._text_model_available = True
        self._image_model_available = True
        self._llm_asset_probe_running = False

        self.splash_frame = ctk.CTkFrame(self)
        self.splash_frame.pack(expand=True, fill="both")

        splash_label = ctk.CTkLabel(
            self.splash_frame,
            text="Loading TTRPG Data Manager...",
            font=("Arial", 24),
        )
        splash_label.pack(expand=True)

        # After delay, remove splash and build main UI
        self.after(LOAD_PAUSE - 1000, lambda: self.prepare(delay=delay))
        self.after(0, self._prepare_llm_assets)

    def prepare(self, delay: int) -> None:
        """Build all widgets and layout while hidden."""
        self.splash_frame.destroy()
        # Custom menu bar widget
        self.menubar = AppMenuBar(
            self,
            on_save=self.save_data,
            on_exit=self.quit,
            on_about=self.show_about,
            on_show_readme=self.show_readme,
            on_show_settings=self.show_settings_dialog,
            on_entry_type_change=self._handle_entry_type_change,
            on_delete_current_entry=self._handle_delete_current_entry,
        )
        self.menubar.pack(side="top", fill="x")
        self.menubar.set_campaign_change_handler(self._handle_campaign_change)
        self._register_shortcuts()

        # Layout Frames
        self.left_frame = ctk.CTkFrame(self, width=200)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)

        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.pack(side="right", expand=True, fill="both", padx=10, pady=10)

        # Left Panel
        self.image_label = ctk.CTkLabel(
            self.left_frame,
            text="",
            font=("Arial", 48),
            image=self.placeholder_img.ctkimage,
        )
        self.image_label.pack(expand=True)
        self._create_image_overlay_button()

        # image right click menu
        self.rmenu = tk.Menu(self, tearoff=0)
        self.rmenu.add_command(
            label="Replace Image",
            command=self.replace_image,
        )
        self.rmenu.add_command(
            label="Download Image",
            command=self.download_image,
        )

        self.arrow_left = ctk.CTkButton(
            self.left_frame,
            text="<",
            width=30,
            state="disabled",
            command=self.show_previous_result,
        )
        self.arrow_left.place(relx=0.1, rely=0.5, anchor="center")

        self.arrow_right = ctk.CTkButton(
            self.left_frame,
            text=">",
            width=30,
            state="disabled",
            command=self.show_next_result,
        )
        self.arrow_right.place(relx=0.9, rely=0.5, anchor="center")

        # Right Panel (Form)
        self.forms: dict[str, dict[str, Any]] = {}
        self._active_form: str | None = None
        self._build_forms()
        self._show_form(self.menubar.entry_type, clear_campaign=True)
        self._initialize_llm_generator_state()

        # bindings
        self.after(
            delay + 1,
            lambda: (self.resize, self.bind("<Configure>", self.resize)),
        )
        self.image_label.bind("<Button-3>", self.show_rmenu)  # Windows/Linux
        self.image_label.bind("<Button-2>", self.show_rmenu)  # macOS
        self.after(250, self._maybe_prompt_sample_seed)

    def _register_shortcuts(self) -> None:
        shortcuts = {
            "<Control-Shift-KeyPress-N>": "NPC",
            "<Control-Shift-KeyPress-L>": "Location",
            "<Control-Shift-KeyPress-E>": "Encounter",
        }
        for sequence, entry_type in shortcuts.items():
            self.bind_all(
                sequence,
                lambda event, value=entry_type: self._handle_entry_type_shortcut(
                    event,
                    value,
                ),
                add="+",
            )
        self.bind_all(
            "<Control-Shift-KeyPress-F>",
            self._handle_search_shortcut,
            add="+",
        )
        self.bind_all(
            "<Control-Shift-KeyPress-C>",
            self._handle_campaign_shortcut,
            add="+",
        )

    def _handle_entry_type_shortcut(self, event: Event, entry_type: str) -> str:
        del event
        self.menubar.select_entry_type(entry_type)
        return "break"

    def _handle_search_shortcut(self, event: Event) -> str:
        del event
        self.search_entry()
        return "break"

    def _handle_campaign_shortcut(self, event: Event) -> str:
        del event
        self.menubar.select_first_campaign()
        return "break"

    def _build_forms(self) -> None:
        for entry_type, specs in self._form_specs.items():
            self._create_form(entry_type, specs)
        self._update_campaign_dropdowns()

    def _create_image_overlay_button(self) -> None:
        label = RandomIcon(
            self.left_frame,
            command=self._handle_image_overlay_click,
        )
        label.place(
            in_=self.image_label,
            relx=0.95,
            rely=0.95,
            anchor="se",
        )
        label.lift()

        # TODO: FIND MAC AND LINUX VERSIONS
        # this only sets the icon background as truly transparent on windows
        if sys.platform == "win32":
            import pywinstyles  # noqa: PLC0415

            bg_color = "#212121" if ctk.get_appearance_mode() == "Dark" else "#e5e5e5"
            pywinstyles.set_opacity(  # type: ignore[attr-defined]
                label,
                color=bg_color if bg_color else "#000001",
            )
        self.image_label.bind("<Configure>", lambda _: label.lift())
        self._image_overlay_icon = label
        self._set_image_overlay_enabled(True)

    def _set_image_overlay_enabled(self, enabled: bool) -> None:
        if self._image_overlay_icon is None:
            return
        effective = (
            enabled
            and self._image_model_available
            and not self._llm_download_in_progress
        )
        self._image_overlay_icon.set_enabled(effective)

    def _attach_npc_name_overlay(self, widget: CTkEntry) -> None:
        icon = RandomIcon(
            widget.master,
            command=self._handle_npc_name_overlay_click,
        )
        icon.place(in_=widget, relx=1.0, rely=0.5, x=-20, anchor="center")
        icon.lift()
        widget.bind("<Configure>", lambda _: icon.lift())
        self._field_overlay_icons.setdefault("NPC", []).append(icon)
        self._set_random_name_icon_enabled(self._llm_ready)

    def _handle_faction_focus_event(self, event: Event | None = None) -> None:
        del event
        if self._active_form != "NPC":
            return
        widget = self._get_faction_widget()
        if widget is None:
            return
        value = widget.get().strip()
        raw_values: tuple[Any] | list[Any] | str | Any = cast(
            Any,
            widget.cget("values"),
        )
        current_values: tuple[str, ...]
        if isinstance(raw_values, (tuple, list)):
            iterable = cast(Sequence[Any], raw_values)
            current_values = tuple(str(value) for value in iterable)
        elif isinstance(raw_values, str):
            segments = [segment.strip() for segment in raw_values.split(",")]
            current_values = tuple(segment for segment in segments if segment)
        else:
            current_values = ()
        if value and value not in current_values:
            self._prompt_new_faction(value)
            return
        self._stage_faction_value(value)
        self._update_faction_view_state(value)

    def _prompt_new_faction(self, initial_value: str) -> None:
        campaign = self._current_campaign_name()
        widget = self._get_faction_widget()
        if campaign is None:
            messagebox.showwarning(
                "Faction",
                "Select a campaign before assigning factions.",
            )
            if widget is not None:
                widget.set(self._current_faction_value or "")
            return

        def _on_submit(name: str, description: str, notes: str) -> None:
            self._finalize_new_faction(name, description, notes, campaign)

        def _on_cancel() -> None:
            if widget is not None:
                widget.set(self._current_faction_value or "")
            self._update_faction_view_state(self._current_faction_value or "")

        self._open_faction_dialog(initial_value, campaign, _on_submit, _on_cancel)

    def _open_faction_dialog(
        self,
        initial_name: str,
        campaign: str,
        on_submit: Callable[[str, str, str], None],
        on_cancel: Callable[[], None] | None,
        **dialog_options: Any,
    ) -> None:
        """Stage context for the faction dialog tracker and display the modal."""
        self._pending_faction_context = FactionDialogContext(
            initial_name=initial_name,
            campaign=campaign,
            on_submit=on_submit,
            on_cancel=on_cancel,
            dialog_options=dialog_options,
        )
        self._faction_dialogs.show()

    def _finalize_new_faction(
        self,
        name: str,
        description: str,
        notes: str,
        campaign: str,
    ) -> None:
        try:
            self.logic.ensure_faction(name, description, campaign)
        except Exception:
            logger.exception("failed to create faction", name=name)
            messagebox.showerror(
                "Faction",
                "Unable to create the faction. Check logs for details.",
            )
            return
        self._staged_faction_assignment = (name, notes)
        self._update_faction_dropdown(campaign)
        widget = self._get_faction_widget()
        if widget is not None:
            widget.set(name)
        self._stage_faction_value(name, notes)
        self._update_faction_view_state(name)

    def _stage_faction_value(
        self,
        faction_name: str | None,
        notes: str | None = None,
    ) -> None:
        if self._active_form != "NPC":
            return
        normalized = faction_name.strip() if faction_name else ""
        key = self._current_record_key
        if notes is None:
            staged = self._staged_faction_assignment
            if staged and staged[0] == normalized:
                notes = staged[1]
            elif normalized == (self._current_faction_value or ""):
                notes = self._current_faction_note
            else:
                notes = ""
        if key is None:
            self._pending_faction_for_new_record = (normalized, notes or "")
            self._update_faction_view_state(normalized)
            return
        if key[0] != "NPC":
            return
        if normalized == (self._current_faction_value or ""):
            self._pending_faction_changes.pop(key, None)
            self._update_faction_view_state(normalized)
            return
        self._pending_faction_changes[key] = (normalized, notes or "")
        self._update_faction_view_state(normalized)

    def _create_form(self, entry_type: str, specs: tuple[FieldSpec, ...]) -> None:
        frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        fields: dict[str, EntryWidget] = {}
        npc_state = _NPCFormState() if entry_type == "NPC" else None

        for spec in specs:
            widget = self._build_form_field(frame, spec)
            fields[spec.key] = widget

            if npc_state is not None:
                self._handle_npc_specific_fields(spec.key, widget, frame, npc_state)

        faction_widget: ctk.CTkComboBox | None = None
        if npc_state is not None:
            faction_widget = self._finalize_npc_fields(frame, npc_state)
        elif entry_type == "Encounter":
            self._insert_encounter_members_button(frame)

        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.pack(pady=10)

        ctk.CTkButton(button_frame, text="New", command=self.new_entry).pack(
            side="left",
            padx=5,
        )
        ctk.CTkButton(button_frame, text="Clear", command=self.clear_form).pack(
            side="left",
            padx=5,
        )
        ctk.CTkButton(button_frame, text="Search", command=self.search_entry).pack(
            side="left",
            padx=5,
        )

        frame.pack_forget()
        form_payload: dict[str, Any] = {"frame": frame, "fields": fields}
        if entry_type == "NPC":
            form_payload["faction_widget"] = faction_widget
        self.forms[entry_type] = form_payload

    def _build_form_field(
        self,
        frame: ctk.CTkFrame,
        spec: FieldSpec,
    ) -> EntryWidget:
        """Create a labeled field row for the provided spec."""
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=5, padx=10)

        lbl = ctk.CTkLabel(row, text=f"{spec.label}:")
        lbl.pack(side="left", padx=(0, 10))

        widget = self._create_widget_for_spec(row, spec)
        widget.pack(side="right", fill="x", expand=True)
        if isinstance(widget, ctk.CTkComboBox):
            widget.set("")
        return widget

    def _create_widget_for_spec(
        self,
        row: ctk.CTkFrame,
        spec: FieldSpec,
    ) -> EntryWidget:
        values: Sequence[str] | None = None
        if spec.key == "gender" and spec.enum_values:
            return self._create_gender_widget(row, spec)
        if spec.enum_values:
            values = list(spec.enum_values)
            return ctk.CTkComboBox(
                row,
                values=values,
                state="readonly",
                width=200,
            )
        if spec.preset_values:
            values = list(spec.preset_values)
            state = "readonly" if spec.key == "location_name" else "normal"
            return ctk.CTkComboBox(
                row,
                values=values,
                state=state,
                width=200,
            )
        if spec.multiline:
            wrap_mode = "word" if not spec.is_json else "char"
            widget = ctk.CTkTextbox(row, height=140, wrap=wrap_mode)
            self._configure_multiline_widget(widget, spec)
            return widget
        return CTkEntry(row)

    def _create_gender_widget(
        self,
        row: ctk.CTkFrame,
        spec: FieldSpec,
    ) -> RadioField:
        """Return a radio field tailored for gender selection."""
        display_labels = {
            "FEMALE": "Female",
            "MALE": "Male",
            "NONBINARY": "Other",
        }
        options: list[tuple[str, str]] = []
        for value in spec.enum_values or ():
            upper_value = value.strip().upper()
            if upper_value == "UNSPECIFIED":
                continue
            label = display_labels.get(upper_value, upper_value.title())
            options.append((upper_value, label))
        return RadioField(
            row,
            options=options,
            empty_value="UNSPECIFIED",
            show_clear=False,
        )

    def _configure_multiline_widget(
        self,
        widget: ctk.CTkTextbox,
        spec: FieldSpec,
    ) -> None:
        """Attach formatting handlers for multiline widgets."""
        if spec.is_json:
            widget.bind(
                "<KeyRelease>",
                self._make_highlight_handler(widget),
            )
            widget.bind(
                "<FocusOut>",
                self._make_format_handler(widget),
            )
            return
        widget.bind(
            "<FocusOut>",
            self._make_hyphenate_handler(widget),
        )

    def _handle_npc_specific_fields(
        self,
        spec_key: str,
        widget: EntryWidget,
        frame: ctk.CTkFrame,
        state: _NPCFormState,
    ) -> None:
        """Attach NPC-only helpers (name overlays, relationships, etc.)."""
        if spec_key == "name" and isinstance(widget, CTkEntry):
            self._attach_npc_name_overlay(widget)

        if spec_key == "species_name" and not state.relationship_inserted:
            self._insert_npc_relationship_section(frame, state)

    def _finalize_npc_fields(
        self,
        frame: ctk.CTkFrame,
        state: _NPCFormState,
    ) -> ctk.CTkComboBox | None:
        """Ensure relationship controls exist and return the faction combo."""
        if not state.relationship_inserted:
            self._insert_npc_relationship_section(frame, state)
        return state.faction_widget

    def _insert_npc_relationship_section(
        self,
        frame: ctk.CTkFrame,
        state: _NPCFormState,
    ) -> None:
        """Insert NPC relationship and faction controls and update state."""
        self._insert_relationship_button(frame)
        state.relationship_inserted = True
        state.faction_widget = self._insert_faction_field(frame)

    def _insert_relationship_button(self, frame: ctk.CTkFrame) -> None:
        self._insert_button_row(
            frame,
            ButtonRowSpec(
                label="Relationships:",
                button_text="Manage...",
                command=self._relationship_dialogs.show,
            ),
        )

    def _insert_encounter_members_button(self, frame: ctk.CTkFrame) -> None:
        self._insert_button_row(
            frame,
            ButtonRowSpec(
                label="Encounter Members:",
                button_text="Manage...",
                command=self._encounter_dialogs.show,
            ),
        )

    def _insert_button_row(
        self,
        frame: ctk.CTkFrame,
        spec: ButtonRowSpec,
    ) -> None:
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=5, padx=10)
        lbl = ctk.CTkLabel(row, text=spec.label)
        lbl.pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            row,
            text=spec.button_text,
            command=spec.command,
            width=spec.width,
        ).pack(side="right")

    def _insert_faction_field(self, frame: ctk.CTkFrame) -> ctk.CTkComboBox:
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=5, padx=10)

        lbl = ctk.CTkLabel(row, text="Faction:")
        lbl.pack(side="left", padx=(0, 10))

        combo = ctk.CTkComboBox(
            row,
            values=[],
            state="normal",
            width=200,
        )
        combo.configure(command=self._handle_faction_selection_command)
        view_btn = ctk.CTkButton(
            row,
            text="View",
            width=70,
            state="disabled",
            command=self._show_faction_details,
        )
        view_btn.pack(side="right")
        combo.pack(side="right", fill="x", expand=True, padx=(0, 10))
        combo.bind("<FocusOut>", self._handle_faction_focus_event)
        combo.bind("<Return>", self._handle_faction_focus_event)
        combo.bind("<<ComboboxSelected>>", self._handle_faction_focus_event)
        combo.bind("<KeyRelease>", self._handle_faction_text_change)
        entry_widget = getattr(combo, "_entry", None)
        if entry_widget is not None:
            entry_widget.bind("<KeyRelease>", self._handle_faction_text_change)
        combo.set("")
        self._npc_faction_widget = combo
        self._faction_view_button = view_btn
        return combo

    def on_relationship_dialog_close(self, dialog: RelationshipDialog) -> None:
        """Clear dialog tracking when the window is dismissed."""
        self._relationship_dialogs.clear(dialog)

    def on_encounter_members_dialog_close(
        self,
        dialog: EncounterMembersDialog,
    ) -> None:
        """Clear encounter dialog ref when closed."""
        self._encounter_dialogs.clear(dialog)

    def _relationship_dialog_context(
        self,
        *,
        silent: bool,
    ) -> RelationshipDialogContext | None:
        key = self._current_record_key
        if key is None or key[0] != "NPC":
            if not silent:
                messagebox.showwarning(
                    "Relationships",
                    "Select an NPC before managing relationships.",
                )
            return None
        return RelationshipDialogContext(
            source_name=key[1],
            campaign=self._current_campaign_name(),
        )

    def _build_relationship_dialog(
        self,
        context: RelationshipDialogContext,
    ) -> RelationshipDialog:
        return RelationshipDialog(
            self,
            context.source_name,
            context.campaign,
        )

    def _encounter_dialog_context(
        self,
        *,
        silent: bool,
    ) -> EncounterDialogContext | None:
        key = self._current_record_key
        if key is None or key[0] != "Encounter":
            if not silent:
                messagebox.showwarning(
                    "Encounter Members",
                    "Select an encounter before managing participants.",
                )
            return None
        try:
            encounter_id = int(key[1])
        except (TypeError, ValueError):
            if not silent:
                messagebox.showwarning(
                    "Encounter Members",
                    "Save the encounter before editing participants.",
                )
            return None
        return EncounterDialogContext(
            encounter_id=encounter_id,
            campaign=self._current_campaign_name(),
        )

    def _build_encounter_dialog(
        self,
        context: EncounterDialogContext,
    ) -> EncounterMembersDialog:
        return EncounterMembersDialog(
            self,
            context.encounter_id,
            context.campaign,
        )

    def _faction_dialog_context(
        self,
        *,
        silent: bool,
    ) -> FactionDialogContext | None:
        context = self._pending_faction_context
        if context is not None:
            self._pending_faction_context = None
            return context
        if not silent:
            messagebox.showerror("Faction", "Unable to open the faction dialog.")
        return None

    def _build_faction_dialog(
        self,
        context: FactionDialogContext,
    ) -> FactionDialog:
        def _wrapped_submit(name: str, description: str, notes: str) -> None:
            try:
                context.on_submit(name, description, notes)
            finally:
                dialog_ref = self._faction_dialogs.current_dialog()
                if dialog_ref is not None:
                    self._faction_dialogs.clear(dialog_ref)

        def _wrapped_cancel() -> None:
            try:
                if context.on_cancel is not None:
                    context.on_cancel()
            finally:
                dialog_ref = self._faction_dialogs.current_dialog()
                if dialog_ref is not None:
                    self._faction_dialogs.clear(dialog_ref)

        return FactionDialog(
            self,
            context.initial_name,
            context.campaign,
            _wrapped_submit,
            _wrapped_cancel,
            **context.dialog_options,
        )

    def _update_faction_dialog(
        self,
        dialog: FactionDialog,
        context: FactionDialogContext,
    ) -> None:
        dialog.update_context(
            context.initial_name,
            context.campaign,
            dialog_options=context.dialog_options,
        )
        dialog.lift()
        dialog.focus_force()

    def _readme_dialog_context(
        self,
        *,
        silent: bool,
    ) -> ReadmeDialogContext | None:
        context = self._pending_readme_context
        if context is not None:
            self._last_readme_context = context
            self._pending_readme_context = None
            return context
        if self._last_readme_context is not None:
            return self._last_readme_context
        if not silent:
            messagebox.showerror("README", "Unable to prepare README preview.")
        return None

    def _build_readme_window(
        self,
        context: ReadmeDialogContext,
    ) -> HtmlPreviewWindow:
        window_ref: HtmlPreviewWindow | None = None

        def _on_close() -> None:
            nonlocal window_ref
            if window_ref is not None:
                self._readme_dialogs.clear(window_ref)
                window_ref = None

        window_ref = HtmlPreviewWindow(
            self,
            title="Project README",
            initial_html=context.html_output,
            source_path=context.readme_path,
            on_close=_on_close,
        )
        return window_ref

    def _build_settings_dialog(self, _: bool) -> SettingsDialog:
        def _handle_close(dialog: SettingsDialog) -> None:
            self._settings_dialogs.clear(dialog)

        return SettingsDialog(
            self,
            on_settings_saved=self._handle_settings_saved,
            on_close=_handle_close,
        )

    def _update_settings_dialog(self, dialog: SettingsDialog, _: bool) -> None:
        dialog.lift()
        dialog.focus_force()

    def relationship_targets_for_campaign(
        self,
        campaign: str | None,
        *,
        exclude: Sequence[str] | None = None,
    ) -> list[str]:
        """Return available NPC names for relationship dropdowns."""
        try:
            return self.logic.relationship_targets_for_campaign(
                campaign,
                exclude=exclude,
            )
        except Exception:
            logger.exception("failed to load npc list for relationships")
            return []

    def fetch_relationship_rows(self, source_name: str) -> list[tuple[str, str]]:
        """Fetch persisted relationships for display in the dialog."""
        try:
            return self.logic.fetch_relationship_rows(source_name)
        except Exception:
            logger.exception("failed to fetch relationships")
            return []

    def upsert_relationship(
        self,
        source_name: str,
        target_name: str,
        relation_name: str,
    ) -> None:
        """Create or update the relationship between two NPCs."""
        self.logic.upsert_relationship(source_name, target_name, relation_name)

    def delete_relationship(self, source_name: str, target_name: str) -> None:
        """Delete an existing relationship between two NPCs."""
        self.logic.delete_relationship(source_name, target_name)

    def fetch_encounter_members(self, encounter_id: int) -> list[tuple[str, str]]:
        """Fetch encounter participants for display in the dialog."""
        try:
            return self.logic.fetch_encounter_members(encounter_id)
        except Exception:
            logger.exception("failed to load encounter members", encounter=encounter_id)
            return []

    def add_encounter_member(
        self,
        encounter_id: int,
        npc_name: str,
        notes: str,
    ) -> None:
        """Assign an NPC to the encounter."""
        self.logic.add_encounter_member(encounter_id, npc_name, notes)

    def remove_encounter_member(
        self,
        encounter_id: int,
        npc_name: str,
    ) -> None:
        """Remove an NPC from the encounter."""
        self.logic.remove_encounter_member(encounter_id, npc_name)

    def _show_form(self, entry_type: str, *, clear_campaign: bool = False) -> None:
        self._remember_current_form()
        self._clear_results()
        if self._active_form and self._active_form in self.forms:
            self.forms[self._active_form]["frame"].pack_forget()

        if entry_type not in self.forms:
            fallback_specs = self._form_specs.get("NPC")
            if fallback_specs is None:
                fallback_specs = (
                    FieldSpec(label="Name", key="name"),
                    FieldSpec(label="Description", key="description", multiline=True),
                )
            self._create_form(entry_type, fallback_specs)

        form = self.forms.get(entry_type)
        if form is None:
            return
        form["frame"].pack(expand=True, fill="both")
        self._active_form = entry_type
        self._load_preview_image(None)
        self._update_campaign_dropdowns(clear_selection=clear_campaign)

    def _handle_entry_type_change(self, entry_type: str) -> None:
        """Swap the visible form when the menu selection changes."""
        self._show_form(entry_type)
        self.clear_form()

    def _handle_campaign_change(self, _: str) -> None:
        """Clear the current form whenever the campaign selection changes."""
        self.clear_form()
        self._update_campaign_dropdowns(clear_selection=True)

    def _handle_delete_current_entry(self, entry_type: str) -> None:  # noqa: C901, PLR0912
        """Delete the currently loaded record for the active form."""
        normalized = (entry_type or "").strip()
        error_message = None
        if normalized not in {"NPC", "Location", "Encounter"}:
            error_message = "Switch to NPC, Location, or Encounter before deleting."
        else:
            key = self._current_record_key
            if key is None or key[0] != normalized or not key[1]:
                label = normalized.lower()
                error_message = f"Load an existing {label} before deleting it."
        if error_message:
            messagebox.showinfo("Delete", error_message)
            return
        key = self._current_record_key
        if key is None:
            return
        identifier = key[1]
        if normalized == "Encounter":
            display_name = f"{normalized} #{identifier}"
        else:
            display_name = f"{normalized} '{identifier}'"
        prompt = f"Delete {display_name}?\n\nThis action cannot be undone."
        if self._has_pending_changes_for(key):
            prompt += "\n\nUnsaved edits for this record will be lost."
        if not messagebox.askyesno("Delete", prompt):
            return
        try:
            deleted = self.logic.delete_entry(normalized, identifier)
        except ValueError as exc:
            messagebox.showerror("Delete", str(exc))
            return
        except Exception:
            logger.exception("failed to delete %s", normalized.lower())
            messagebox.showerror(
                "Delete",
                "Unable to delete the entry. Check logs for details.",
            )
            return
        if not deleted:
            messagebox.showwarning(
                "Delete",
                (f"{display_name} was not found. It may have already been removed."),
            )
            return
        self._pending_changes.pop(key, None)
        self._pending_images.pop(key, None)
        self._pending_faction_changes.pop(key, None)
        handled = self._show_next_result_after_delete(normalized, identifier)
        if not handled:
            self.clear_form()
        self._update_campaign_dropdowns()
        messagebox.showinfo("Delete", f"Deleted {display_name}.")

    def _get_active_fields(self) -> dict[str, EntryWidget]:
        form_key = self._active_form
        if form_key is None:
            return {}
        form = self.forms.get(form_key)
        if form is None:
            return {}
        return cast("dict[str, EntryWidget]", form["fields"])

    def _get_form_widget(self, entry_type: str, field_key: str) -> EntryWidget | None:
        form = self.forms.get(entry_type)
        if form is None:
            return None
        fields = cast("dict[str, EntryWidget]", form["fields"])
        return fields.get(field_key)

    def _get_faction_widget(self) -> ctk.CTkComboBox | None:
        if self._npc_faction_widget is not None:
            return self._npc_faction_widget
        form = self.forms.get("NPC")
        if not form:
            return None
        combo = form.get("faction_widget")
        if isinstance(combo, ctk.CTkComboBox):
            self._npc_faction_widget = combo
            return combo
        return None

    def _update_faction_view_state(self, faction_name: str | None) -> None:
        button = self._faction_view_button
        if button is None:
            return
        normalized = faction_name.strip() if faction_name else ""
        if not normalized:
            widget = self._get_faction_widget()
            if widget is not None:
                normalized = widget.get().strip()
        if normalized:
            button.configure(state="normal")
        else:
            button.configure(state="disabled")

    def _ensure_faction_option(
        self,
        widget: ctk.CTkComboBox,
        faction_name: str,
    ) -> None:
        if not faction_name:
            return
        raw_values = cast(
            tuple[Any, ...] | list[Any] | str | None,
            widget.cget("values"),
        )
        if isinstance(raw_values, (tuple, list)):
            values = [str(item) for item in raw_values]
        elif isinstance(raw_values, str):
            values = [segment.strip() for segment in raw_values.split(",") if segment]
        else:
            values = []
        if faction_name in values:
            return
        values.append(faction_name)
        widget.configure(values=values)

    def _resolve_membership_note_for_display(self, faction_name: str) -> str:
        normalized = faction_name.strip()
        staged = self._staged_faction_assignment
        pending_new = self._pending_faction_for_new_record
        candidates: list[str | None] = []
        key = self._current_record_key
        if key is None:
            if pending_new and pending_new[0] == normalized:
                candidates.append(pending_new[1])
            if staged and staged[0] == normalized:
                candidates.append(staged[1])
        else:
            assignment = self._pending_faction_changes.get(key)
            if assignment and assignment[0] == normalized:
                candidates.append(assignment[1])
            if normalized == (self._current_faction_value or ""):
                candidates.append(self._current_faction_note)
            if staged and staged[0] == normalized:
                candidates.append(staged[1])
            if pending_new and pending_new[0] == normalized:
                candidates.append(pending_new[1])
        for candidate in candidates:
            if candidate:
                return candidate
        return ""

    def _show_faction_details(self) -> None:
        widget = self._get_faction_widget()
        if widget is None:
            return
        faction_name = widget.get().strip()
        if not faction_name:
            messagebox.showinfo("Faction", "Select a faction to view.")
            return
        try:
            details = self.logic.fetch_faction_details(faction_name)
        except Exception:
            logger.exception("failed to load faction details", faction=faction_name)
            messagebox.showerror(
                "Faction",
                "Unable to load faction details. Check logs for details.",
            )
            return
        if details is None:
            self._prompt_new_faction(faction_name)
            return
        description, campaign_name = details
        note = self._resolve_membership_note_for_display(faction_name)

        def _on_submit(name: str, desc: str, updated_note: str) -> None:
            self._finalize_existing_faction(
                original_name=faction_name,
                submitted_name=name,
                description=desc,
                notes=updated_note,
                campaign=campaign_name,
            )

        self._open_faction_dialog(
            faction_name,
            campaign_name,
            _on_submit,
            None,
            dialog_title="Faction Details",
            save_button_label="Update",
            allow_name_edit=False,
            initial_description=description,
            initial_notes=note,
        )

    def _handle_faction_details_updated(self, faction_name: str, notes: str) -> None:
        self._stage_faction_value(faction_name, notes)
        if faction_name == (self._current_faction_value or ""):
            self._current_faction_note = notes
        messagebox.showinfo("Faction", "Membership notes updated.")

    def _handle_faction_selection_command(self, value: str | None) -> None:
        normalized = value.strip() if value else ""
        if normalized:
            self._stage_faction_value(normalized)
        self._update_faction_view_state(normalized)

    def _handle_faction_text_change(self, event: Event | None = None) -> None:
        del event
        widget = self._get_faction_widget()
        if widget is None:
            return
        self._update_faction_view_state(widget.get())

    def _finalize_existing_faction(
        self,
        *,
        original_name: str,
        submitted_name: str,
        description: str,
        notes: str,
        campaign: str,
    ) -> None:
        normalized_name = submitted_name.strip() or original_name
        if normalized_name != original_name:
            messagebox.showwarning(
                "Faction",
                "Renaming factions is not supported from this dialog.",
            )
            return
        try:
            self.logic.ensure_faction(original_name, description, campaign)
        except Exception:
            logger.exception("failed to update faction", name=original_name)
            messagebox.showerror(
                "Faction",
                "Unable to update the faction details. Check logs for details.",
            )
            return
        self._handle_faction_details_updated(original_name, notes)

    def _current_campaign_name(self) -> str | None:
        campaign = getattr(self.menubar, "campaign", "").strip()
        if campaign in {"", "New Campaign", "No Campaigns"}:
            return None
        return campaign

    def _apply_combo_values(
        self,
        combo: ctk.CTkComboBox,
        values: Sequence[str],
        *,
        auto_select: bool = True,
    ) -> None:
        sequence = list(values)
        combo.configure(values=sequence)
        current = combo.get().strip()
        if not sequence:
            combo.set("")
            return
        if current and current in sequence:
            combo.set(current)
            return
        if auto_select and sequence:
            combo.set(sequence[0])
            return
        combo.set("")

    def _update_campaign_dropdowns(self, *, clear_selection: bool = False) -> None:
        campaign = self._current_campaign_name()
        self._update_species_dropdown(campaign, clear_selection=clear_selection)
        self._update_location_dropdown(campaign, clear_selection=clear_selection)
        self._update_faction_dropdown(campaign, clear_selection=clear_selection)
        if clear_selection:
            self._current_record_key = None
        self._relationship_dialogs.refresh()
        self._encounter_dialogs.refresh()

    def _maybe_prompt_sample_seed(self) -> None:
        if not self.logic.should_seed_sample_data():
            return
        if not messagebox.askyesno(
            "Sample Data",
            (
                "No NPCs, locations, or encounters were found in the database.\n"
                "Would you like to load the bundled sample data now?"
            ),
        ):
            return
        try:
            results = self.logic.load_sample_data()
        except Exception:
            logger.exception("failed to load sample data")
            messagebox.showerror(
                "Sample Data",
                "Unable to load the sample data. Check logs for details.",
            )
            return
        total_loaded = sum(results.values())
        summary = ", ".join(
            f"{label.capitalize()}: {count}" for label, count in results.items()
        )
        messagebox.showinfo(
            "Sample Data",
            f"Loaded {total_loaded} sample record(s).\n{summary}",
        )
        self.menubar.refresh_campaigns(notify=True)
        self._update_campaign_dropdowns(clear_selection=True)

    def _update_species_dropdown(
        self,
        campaign: str | None,
        *,
        clear_selection: bool = False,
    ) -> None:
        widget = self._get_form_widget("NPC", "species_name")
        if not isinstance(widget, ctk.CTkComboBox):
            return
        try:
            values = self.logic.list_species(campaign)
        except Exception:
            logger.exception("failed to load species list")
            return
        self._apply_combo_values(widget, values, auto_select=not clear_selection)
        if clear_selection:
            widget.set("")

    def _update_location_dropdown(
        self,
        campaign: str | None,
        *,
        clear_selection: bool = False,
    ) -> None:
        widget = self._get_form_widget("Encounter", "location_name")
        if not isinstance(widget, ctk.CTkComboBox):
            return
        try:
            values = self.logic.list_locations(campaign)
        except Exception:
            logger.exception("failed to load location list")
            return
        self._apply_combo_values(widget, values, auto_select=not clear_selection)
        if clear_selection:
            widget.set("")

    def _update_faction_dropdown(
        self,
        campaign: str | None,
        *,
        clear_selection: bool = False,
    ) -> None:
        widget = self._get_faction_widget()
        if widget is None:
            return
        try:
            values = list(self.logic.list_factions(campaign))
        except Exception:
            logger.exception("failed to load faction list")
            return
        current_value = self._current_faction_value or ""
        if current_value and current_value not in values:
            values.append(current_value)
        widget.configure(values=values)
        if clear_selection:
            widget.set("")
            self._current_faction_value = None
            self._current_faction_note = ""
            self._update_faction_view_state("")
            return
        if current_value:
            widget.set(current_value)
        self._update_faction_view_state(current_value)

    def save_data(self) -> None:  # noqa: C901
        """Persist any pending in-memory changes to the database."""
        self._remember_current_form()
        no_record_changes = not self._pending_changes and not self._pending_images
        if no_record_changes and not self._pending_faction_changes:
            messagebox.showinfo("Save", "There are no pending edits to save.")
            return
        result = None
        renamed_keys: dict[tuple[str, str], tuple[str, str]] = {}
        updated = 0
        if not no_record_changes:
            try:
                result = self.logic.persist_pending_records(
                    self._pending_changes,
                    self._pending_images,
                    self._get_spec_map,
                )
            except ValueError as exc:
                messagebox.showerror("Save", str(exc))
                return
            except Exception:
                logger.exception("failed to persist pending changes")
                messagebox.showerror(
                    "Save",
                    "Unable to save changes. Check logs for details.",
                )
                return
            updated = result.updated
            for key in result.applied_keys:
                self._pending_changes.pop(key, None)
                self._pending_images.pop(key, None)
            renamed_keys = result.renamed_keys
            for old_key, new_key in renamed_keys.items():
                if self._current_record_key == old_key:
                    self._current_record_key = new_key
        faction_failures, faction_updates = self._apply_pending_faction_changes(
            renamed_keys,
        )
        if updated > 0:
            messagebox.showinfo("Save", f"Saved {updated} record(s) to the database.")
        elif faction_updates > 0:
            messagebox.showinfo("Save", "Faction memberships updated.")
        elif not faction_failures:
            messagebox.showinfo("Save", "No records required saving.")
        if faction_failures:
            failures = ", ".join(faction_failures)
            messagebox.showwarning(
                "Faction",
                f"Unable to update faction membership for: {failures}.",
            )

    def show_settings_dialog(self) -> None:
        """Open the dynamic settings dialog, creating it on demand."""
        self._settings_dialogs.show()

    def _handle_settings_saved(self, _: dict[str, Any]) -> None:
        try:
            reload_image_generation_defaults()
        except ValueError as exc:
            logger.exception("failed to reload image defaults")
            messagebox.showerror("Settings", str(exc))

    def show_about(self) -> None:
        """About window callback."""
        attribution = self._build_attribution_message()
        messagebox.showinfo(
            "About",
            f"TTRPG Data Manager\nVersion {version()}\n\n{attribution}",
        )

    def show_readme(self) -> None:
        """Render README markdown to HTML and display it inside a CTk window."""
        readme_path = PROJECT_ROOT / "README.md"
        if not readme_path.exists():
            messagebox.showerror("README", f"README not found at {readme_path}.")
            return
        try:
            markdown_text = readme_path.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("README", f"Unable to read README: {exc}.")
            return
        try:
            html_output: str = cast(str, render_markdown(markdown_text))
        except Exception:
            logger.exception("failed to render readme markdown")
            messagebox.showerror("README", "Failed to render README content.")
            return
        padding = HtmlPreviewWindow.PRE_PADDING_CHARS
        max_chars = max(40, self._readme_char_width() - padding)
        stylized_html = HtmlPreviewWindow.prepare_html(html_output, max_chars)
        self._display_readme_html(stylized_html, readme_path)

    def _display_readme_html(self, html_output: str, readme_path: Path) -> None:
        self._pending_readme_context = ReadmeDialogContext(
            html_output=html_output,
            readme_path=readme_path,
        )
        self._readme_dialogs.show()

    def _readme_char_width(self) -> int:
        """Estimate max characters per line based on window width."""
        width_px = 0
        try:
            width_px = max(width_px, int(self.winfo_width()))
        except tk.TclError:
            width_px = 0
        window = self._readme_dialogs.current_dialog()
        if window is not None and window.winfo_exists():
            width_px = max(width_px, window.winfo_width())
        if width_px <= 0:
            width_px = 960
        approx_char_width = 9
        return max(60, width_px // approx_char_width)

    def _build_attribution_message(self) -> str:
        """Return newline separated attribution text for bundled assets."""
        parts = [
            "Attributions:",
            "- Font Awesome Free icons: https://fontawesome.com/",
            "- CustomTkinter UI toolkit: https://github.com/TomSchimansky/CustomTkinter",
        ]
        return "\n".join(parts)

    def new_entry(self) -> None:
        """Create and immediately persist a new record for the active form."""
        entry_type: str = "Entry"
        created_instance: Any
        try:
            (
                entry_type,
                model_cls,
                campaign_name,
                field_values,
                spec_map,
            ) = self._gather_new_entry_context()
            created_instance = self.logic.create_entry(
                entry_type,
                model_cls,
                field_values,
                campaign_name,
                self._current_image_payload,
                spec_map,
            )
        except DuplicateRecordError as exc:
            messagebox.showwarning("New", str(exc))
            return
        except ValueError as exc:
            messagebox.showerror("New", str(exc))
            return
        except Exception:
            logger.exception("failed to create new %s entry", entry_type.lower())
            error_msg = (
                f"Unable to create the {entry_type.lower()} entry. "
                "Check logs for details."
            )
            messagebox.showerror("New", error_msg)
            return

        self._clear_results()
        record_key = self._record_key_from_instance(entry_type, created_instance)
        self._current_record_key = record_key
        if record_key is not None:
            self._pending_changes.pop(record_key, None)
            self._pending_images.pop(record_key, None)
        self._populate_form_from_instance(created_instance, entry_type)
        self._update_image_from_instance(entry_type, created_instance)
        self._update_campaign_dropdowns()
        if entry_type == "NPC":
            self._apply_pending_faction_for_new_record(
                getattr(created_instance, "name", ""),
            )

        if entry_type == "Encounter":
            identifier = f"#{getattr(created_instance, 'id', 'unknown')}"
        else:
            name_text = getattr(created_instance, "name", "unknown")
            identifier = f"'{name_text}'"
        messagebox.showinfo(
            "New",
            f"Created new {entry_type.lower()} {identifier}.",
        )

    def clear_form(self) -> None:
        """Clear the form."""
        self._clear_results()
        for key, widget in self._get_active_fields().items():
            if isinstance(widget, CTkEntry):
                widget.delete(0, tk.END)
            elif isinstance(widget, ctk.CTkTextbox):
                widget.delete("1.0", tk.END)
                if key.endswith("_json"):
                    self._highlight_json(widget)
            else:
                widget.set("")
        self._load_preview_image(None)
        faction_widget = self._get_faction_widget()
        if faction_widget is not None:
            faction_widget.set("")
        self._current_faction_value = None
        self._current_faction_note = ""
        self._pending_faction_for_new_record = None
        self._update_faction_view_state("")
        self._reset_current_record()
        self._relationship_dialogs.refresh()
        self._encounter_dialogs.refresh()

    def _handle_image_overlay_click(self) -> None:
        """Kick off context-aware image generation via the local image model."""
        if self._image_generation_in_progress:
            messagebox.showinfo(
                "Image Generator",
                "An image request is already running. Please wait for it to finish.",
            )
            return
        entry_type = self._active_form or self.menubar.entry_type
        context = self._resolve_image_request_context(entry_type)
        if context is None:
            messagebox.showinfo(
                "Image Generator",
                (
                    "Switch to the NPC, Location, or Encounter form to generate "
                    "images automatically."
                ),
            )
            return
        prompt = context.prompt_builder()
        if not prompt:
            messagebox.showinfo(context.title, context.empty_prompt_message)
            return
        dialog = LLMProgressDialog(self)
        dialog.update_status(context.progress_message, None)
        self._image_generation_in_progress = True
        self._active_image_request = context
        self._set_image_overlay_enabled(False)
        thread = threading.Thread(
            target=self._generate_image_async,
            args=(prompt, dialog),
            daemon=True,
        )
        thread.start()

    def _resolve_image_request_context(
        self,
        entry_type: str | None,
    ) -> _ImageRequestContext | None:
        if entry_type == "NPC":
            return _ImageRequestContext(
                title="Portrait Generator",
                progress_message="Requesting a new portrait...",
                empty_prompt_message=(
                    "Add a name, species, or description before generating a portrait."
                ),
                success_message=(
                    "A new portrait has been loaded. Save the NPC to keep it."
                ),
                prompt_builder=self._build_portrait_prompt,
            )
        if entry_type == "Location":
            return _ImageRequestContext(
                title="Location Generator",
                progress_message="Composing a new location scene...",
                empty_prompt_message=(
                    "Add a name, type, or description before generating a location"
                    " image."
                ),
                success_message=(
                    "A new location image has been loaded. Save the location to keep"
                    " it."
                ),
                prompt_builder=self._build_location_image_prompt,
            )
        if entry_type == "Encounter":
            return _ImageRequestContext(
                title="Battlemat Generator",
                progress_message="Drafting an overhead battlemat...",
                empty_prompt_message=(
                    "Add a location or description before generating a battlemat."
                ),
                success_message=(
                    "A new battlemat has been loaded. Save the encounter to keep it."
                ),
                prompt_builder=self._build_battlemat_prompt,
            )
        return None

    def _handle_npc_name_overlay_click(self) -> None:
        """Generate and populate a random NPC name via the local LLM."""
        status = self._get_llm_server_status()
        if status is _LLMServerStatus.WAITING:
            messagebox.showinfo(
                "NPC Generator",
                "The local LLM is still starting. Please try again in a moment.",
            )
            return
        if self._active_form != "NPC":
            messagebox.showinfo(
                "NPC Generator",
                "Switch to the NPC form to use the name generator.",
            )
            return
        name_widget = self._get_form_widget("NPC", "name")
        if not isinstance(name_widget, CTkEntry):
            messagebox.showwarning(
                "NPC Generator",
                "Unable to locate the NPC name field.",
            )
            return
        species_widget = self._get_form_widget("NPC", "species_name")
        species_value = ""
        if isinstance(species_widget, ctk.CTkComboBox):
            species_value = species_widget.get().strip()
        gender_widget = self._get_form_widget("NPC", "gender")
        gender_value = self._widget_value(gender_widget) if gender_widget else ""
        gender_descriptor = self._gender_descriptor(gender_value)
        descriptor_bits = [bit for bit in (gender_descriptor, species_value) if bit]
        descriptor = " ".join(descriptor_bits) if descriptor_bits else "NPC"
        dialog = LLMProgressDialog(self)
        dialog.update_status(f"Requesting a name for {descriptor}...", None)

        thread = threading.Thread(
            target=self._generate_name_async,
            args=(descriptor, name_widget, dialog),
            daemon=True,
        )
        thread.start()

    def _get_llm_server_status(self) -> _LLMServerStatus:
        if is_text_llm_server_ready():
            return _LLMServerStatus.READY
        if did_text_llm_server_fail():
            return _LLMServerStatus.FAILED
        return _LLMServerStatus.WAITING

    def _build_portrait_prompt(self) -> str:
        if (self._active_form or self.menubar.entry_type) != "NPC":
            return ""

        def _value(field: str) -> str:
            widget = self._get_form_widget("NPC", field)
            return self._widget_value(widget) if widget is not None else ""

        name = _value("name")
        species = _value("species_name")
        description = _value("description")
        alignment = _value("alignment_name")
        age = _value("age")
        gender_value = _value("gender")
        gender_descriptor = self._gender_descriptor(gender_value)

        descriptor_text = ", ".join(
            part
            for part in (
                gender_descriptor,
                f"{age}-year-old" if age else "",
                alignment.lower() if alignment else "",
                species,
            )
            if part
        )
        subject = f"Portrait of {name or 'an NPC'}"
        if descriptor_text:
            subject = f"{subject}, {descriptor_text}"
        appearance = ""
        if description:
            collapsed = " ".join(description.split())
            appearance = textwrap.shorten(collapsed, width=220, placeholder="...")
        style_bits = (
            "fantasy character concept art; bust shot; dramatic lighting; "
            "digital painting; high detail"
        )
        prompt = f"{subject}. {style_bits}."
        if appearance:
            prompt += f" Appearance details: {appearance}"
        if not (name or species or appearance):
            return ""
        return prompt

    def _build_location_image_prompt(self) -> str:
        if (self._active_form or self.menubar.entry_type) != "Location":
            return ""

        def _value(field: str) -> str:
            return self._form_value("Location", field)

        name = _value("name")
        location_type = _value("type")
        description = _value("description")
        if not any((name, location_type, description)):
            return ""
        descriptor_bits: list[str] = []
        if location_type:
            descriptor_bits.append(location_type.replace("_", " ").lower())
        descriptor = ", ".join(bit for bit in descriptor_bits if bit)
        subject = name or "a fantasy location"
        prompt = f"Atmospheric fantasy location concept art of {subject}"
        if descriptor:
            prompt += f", {descriptor}: "
        if description:
            collapsed = " ".join(description.split())
            prompt += f"{textwrap.shorten(collapsed, width=220, placeholder='...')}"
        prompt += (
            ". sweeping vista; environmental concept art; cinematic lighting; "
            "ultra detailed; 4k render."
        )
        return prompt

    def _build_battlemat_prompt(self) -> str:
        if (self._active_form or self.menubar.entry_type) != "Encounter":
            return ""

        def _value(field: str) -> str:
            return self._form_value("Encounter", field)

        location_name = _value("location_name")
        description = _value("description")
        date_value = _value("date")
        if not any((location_name, description)):
            return ""
        subject = location_name or "a fantasy encounter"
        prompt = (
            f"Top-down tactical battlemat for {subject}. "
            "overhead view; 32x32 grid; richly textured terrain; clear movement "
            "paths; fantasy tabletop RPG map; high-contrast lighting."
        )
        context_bits: list[str] = []
        if date_value:
            context_bits.append(f"date: {date_value}")
        if context_bits:
            prompt += f" Session context: {', '.join(context_bits)}."
        if description:
            collapsed = " ".join(description.split())
            prompt += (
                " Encounter description: "
                f"{textwrap.shorten(collapsed, width=220, placeholder='...')}"
            )
        prompt += " Emphasize tactical readability and overhead perspective."
        return prompt

    def _generate_image_async(
        self,
        prompt: str,
        dialog: LLMProgressDialog,
    ) -> None:
        """Generate an image without blocking the GUI thread."""

        def _emit(message: str, percent: float | None) -> None:
            self.after(0, lambda: dialog.update_status(message, percent))

        payload: bytes | None = None
        error_message: str | None = None
        try:
            payload = generate_portrait_from_image_llm(
                prompt,
                progress_callback=_emit,
            )
        except FileNotFoundError:
            logger.exception("image generator binary missing")
            error_message = (
                "The image generator binary was not found. Confirm sdfile-0.9.3 "
                "exists in data/llm."
            )
        except RuntimeError as exc:
            error_message = str(exc) or "Image generation failed."
        except Exception:
            logger.exception("unexpected error during image generation")
            error_message = "Unexpected error while generating the portrait."
        self.after(
            0,
            lambda: self._finalize_image_generation(
                payload,
                dialog,
                error_message,
            ),
        )

    def _finalize_image_generation(
        self,
        payload: bytes | None,
        dialog: LLMProgressDialog,
        error_message: str | None,
    ) -> None:
        """Update the UI once the background image call completes."""
        if dialog.winfo_exists():
            dialog.close()
        self._image_generation_in_progress = False
        self._set_image_overlay_enabled(True)
        context = self._active_image_request
        self._active_image_request = None
        title = context.title if context else "Image Generator"
        success_message = (
            context.success_message
            if context
            else "A new image has been loaded. Save the record to keep it."
        )
        if error_message:
            messagebox.showerror(title, error_message)
            return
        if not payload:
            messagebox.showwarning(
                title,
                "The image generator did not return any data.",
            )
            return
        if not self._load_preview_image(payload, mark_dirty=True):
            messagebox.showerror(
                title,
                "Unable to display the generated image.",
            )
            return
        if self._current_record_key is not None:
            self._remember_image_override()
        messagebox.showinfo(title, success_message)

    def _generate_name_async(
        self,
        descriptor: str,
        name_widget: CTkEntry,
        dialog: LLMProgressDialog,
    ) -> None:
        """Run the name generation call without blocking the GUI."""

        def _emit(message: str, percent: float | None) -> None:
            self.after(0, lambda: dialog.update_status(message, percent))

        error_message: str | None = None
        suggestion: str | None = None
        try:
            suggestion = get_random_name_from_text_llm(
                descriptor,
                progress_callback=_emit,
            )
        except Exception:
            logger.exception("failed to generate npc name", species=descriptor)
            error_message = "Unable to contact the local LLM for a random name."

        self.after(
            0,
            lambda: self._finalize_name_generation(
                name_widget,
                suggestion,
                dialog,
                error_message,
            ),
        )

    def _finalize_name_generation(
        self,
        name_widget: CTkEntry,
        suggestion: str | None,
        dialog: LLMProgressDialog,
        error_message: str | None,
    ) -> None:
        """Handle UI updates after the LLM attempt completes."""
        if dialog.winfo_exists():
            dialog.close()
        if error_message:
            messagebox.showerror("NPC Generator", error_message)
            return
        cleaned = (suggestion or "").strip()
        if not cleaned or cleaned == "Unknown Name":
            messagebox.showwarning(
                "NPC Generator",
                "The LLM did not return a usable name. Please try again.",
            )
            return
        if not name_widget.winfo_exists():
            return
        name_widget.delete(0, tk.END)
        name_widget.insert(0, cleaned)
        name_widget.focus_set()

    def _prepare_llm_assets(self) -> None:
        if self._llm_download_in_progress or self._llm_asset_probe_running:
            return
        self._llm_asset_probe_running = True

        def _probe() -> None:
            try:
                missing_assets = get_missing_llm_assets()
            except Exception as exc:  # pragma: no cover - defensive UI path
                logger.exception("failed to inspect llm assets")
                self.after(0, lambda err=exc: self._handle_llm_probe_failure(err))
                return
            self.after(
                0,
                lambda specs=missing_assets: self._handle_llm_probe_result(specs),
            )

        threading.Thread(target=_probe, name="llm-asset-probe", daemon=True).start()

    def _handle_llm_probe_failure(self, exc: Exception) -> None:
        self._llm_asset_probe_running = False
        messagebox.showerror(
            "LLM Initialization",
            (f"Unable to inspect the local LLM assets.\n\nDetails: {exc}"),
        )

    def _handle_llm_probe_result(
        self,
        missing: Sequence[LLMAssetDownloadSpec],
    ) -> None:
        self._llm_asset_probe_running = False
        self._update_llm_asset_availability(missing)
        if not missing:
            self._start_llm_server()
            return
        asset_list = "\n".join(f"- {spec.name}" for spec in missing)
        prompt = (
            "Required LLM model files are missing:\n\n"
            f"{asset_list}\n\n"
            f"Approximately {LLM_DOWNLOAD_SIZE_GB} GB of free disk space is needed. "
            "Would you like to download them now?"
        )
        if not messagebox.askyesno(
            "Download LLM Models",
            prompt,
            icon="warning",
        ):
            messagebox.showwarning(
                "Download LLM Models",
                (
                    "LLM-powered features will remain unavailable until the models "
                    "are installed. You can add the files to data/llm manually at "
                    "any time."
                ),
            )
            return
        self._begin_llm_asset_download(missing)

    def _begin_llm_asset_download(
        self,
        assets: Sequence[LLMAssetDownloadSpec],
    ) -> None:
        if self._llm_download_in_progress:
            return
        self._llm_download_in_progress = True
        self._sync_llm_controls()
        dialog = LLMProgressDialog(self)
        dialog.update_status("Preparing download...", None)

        def _emit(message: str, percent: float | None) -> None:
            self.after(
                0,
                lambda msg=message, pct=percent: self._update_llm_download_dialog(
                    dialog,
                    msg,
                    pct,
                ),
            )

        def _worker() -> None:
            try:
                for asset in assets:
                    download_llm_asset(asset, _emit)
            except Exception as exc:
                logger.exception("failed to download llm assets")
                self.after(
                    0,
                    lambda err=exc: self._handle_llm_download_error(dialog, err),
                )
            else:
                self.after(0, lambda: self._handle_llm_download_success(dialog))

        threading.Thread(
            target=_worker,
            name="llm-asset-download",
            daemon=True,
        ).start()

    def _update_llm_asset_availability(
        self,
        missing_assets: Sequence[LLMAssetDownloadSpec] | None = None,
    ) -> None:
        specs = get_llm_asset_requirements()
        assets = (
            missing_assets if missing_assets is not None else get_missing_llm_assets()
        )
        missing_paths = {spec.path for spec in assets}
        image_available = True
        text_available = True
        image_found = False
        text_found = False
        for spec in specs:
            available = spec.path not in missing_paths
            suffix = spec.path.suffix.lower()
            if suffix == ".safetensors" and not image_found:
                image_found = True
                image_available = available
            elif suffix == ".llamafile" and not text_found:
                text_found = True
                text_available = available
        if not image_found:
            image_available = True
        if not text_found:
            text_available = True
        self._image_model_available = image_available
        self._text_model_available = text_available
        self._sync_llm_controls()

    def _update_llm_download_dialog(
        self,
        dialog: LLMProgressDialog,
        message: str,
        percent: float | None,
    ) -> None:
        if dialog.winfo_exists():
            dialog.update_status(message, percent)

    def _handle_llm_download_error(
        self,
        dialog: LLMProgressDialog,
        exc: Exception,
    ) -> None:
        self._llm_download_in_progress = False
        self._update_llm_asset_availability()
        if dialog.winfo_exists():
            dialog.close()
        messagebox.showerror(
            "Download LLM Models",
            f"Unable to download the required models: {exc}",
        )

    def _handle_llm_download_success(self, dialog: LLMProgressDialog) -> None:
        self._llm_download_in_progress = False
        self._update_llm_asset_availability()
        if dialog.winfo_exists():
            dialog.close()
        messagebox.showinfo(
            "Download LLM Models",
            "Model files downloaded successfully.",
        )
        self._start_llm_server()

    def _start_llm_server(self) -> None:
        if self._llm_server_started:
            return
        self._llm_server_started = True
        start_text_llm_server_async()

    def _initialize_llm_generator_state(self) -> None:
        status = self._get_llm_server_status()
        self._llm_ready = status is _LLMServerStatus.READY
        self._sync_llm_controls()
        if status is _LLMServerStatus.WAITING:
            self._schedule_llm_readiness_check()

    def _schedule_llm_readiness_check(self) -> None:
        if self._llm_watch_job is not None:
            return
        self._llm_watch_job = self.after(
            LLM_POLL_INTERVAL,
            self._poll_llm_server_state,
        )

    def _poll_llm_server_state(self) -> None:
        self._llm_watch_job = None
        status = self._get_llm_server_status()
        if status is _LLMServerStatus.READY:
            self._llm_ready = True
            self._sync_llm_controls()
            return
        if status is _LLMServerStatus.FAILED:
            self._llm_ready = False
            self._sync_llm_controls()
            return
        self._schedule_llm_readiness_check()

    def _set_random_name_icon_enabled(self, enabled: bool) -> None:
        effective = (
            enabled
            and self._text_model_available
            and not self._llm_download_in_progress
        )
        for icon in self._field_overlay_icons.get("NPC", []):
            icon.set_enabled(effective)

    def _sync_llm_controls(self) -> None:
        self._set_random_name_icon_enabled(self._llm_ready)
        self._set_image_overlay_enabled(not self._image_generation_in_progress)

    def replace_image(self) -> None:
        """Prompt the user to select a new portrait image for the preview panel."""
        filetypes = [
            ("Image Files", "*.png *.jpg *.jpeg *.bmp"),
            ("PNG", "*.png"),
            ("JPEG", "*.jpg *.jpeg"),
            ("Bitmap", "*.bmp"),
        ]
        initial_dir = (PROJECT_ROOT / "data" / "img").resolve()
        file_path = filedialog.askopenfilename(
            title="Select Image",
            initialdir=str(initial_dir),
            filetypes=filetypes,
        )
        if not file_path:
            return
        if not self._load_preview_image(Path(file_path), mark_dirty=True):
            # _load_preview_image already logged & reverted, so only inform user.
            messagebox.showerror(
                "Replace Image",
                "Unable to load the selected image file.",
            )
            return
        self._remember_image_override()

    def download_image(self) -> None:
        """Allow the user to export the currently displayed portrait."""
        if not self._current_image_payload:
            messagebox.showinfo(
                "Download Image",
                "No portrait image is available to download.",
            )
            return
        initial_dir = (PROJECT_ROOT / "data" / "img").resolve()
        target_dir = filedialog.askdirectory(
            title="Select Download Folder",
            initialdir=str(initial_dir),
        )
        if not target_dir:
            return
        basename = self._normalize_filename(self._current_entry_label())
        extension = self._guess_image_extension(self._current_image_payload)
        target_path = Path(target_dir) / f"{basename}{extension}"
        try:
            target_path.write_bytes(self._current_image_payload)
        except OSError:
            logger.exception("failed to save portrait image", path=target_path)
            messagebox.showerror(
                "Download Image",
                "Unable to save the selected image. Check logs for details.",
            )
            return
        messagebox.showinfo(
            "Download Image",
            f"Portrait saved to: {target_path}",
        )

    def _current_entry_label(self) -> str:
        """Return a descriptive name for the active entry."""
        key = self._current_record_key
        entry_type = (
            (key[0] if key else None) or self._active_form or self.menubar.entry_type
        )
        candidate = None
        if entry_type:
            widget = self._get_form_widget(entry_type, "name")
            if widget is not None:
                candidate = self._widget_value(widget)
        if not candidate and entry_type == "Encounter":
            location_widget = self._get_form_widget("Encounter", "location_name")
            if location_widget is not None:
                candidate = self._widget_value(location_widget)
        if not candidate and key and key[1]:
            candidate = key[1]
        return candidate or "portrait"

    @staticmethod
    def _normalize_filename(raw_value: str) -> str:
        cleaned = raw_value.strip().lower()
        cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
        return cleaned or "portrait"

    @staticmethod
    def _guess_image_extension(payload: bytes) -> str:
        try:
            with Image.open(BytesIO(payload)) as preview:
                fmt = (preview.format or "png").lower()
        except (UnidentifiedImageError, OSError):
            return ".png"
        mapping = {
            "png": ".png",
            "jpeg": ".jpg",
            "jpg": ".jpg",
            "bmp": ".bmp",
            "gif": ".gif",
            "webp": ".webp",
        }
        return mapping.get(fmt, ".png")

    def show_rmenu(self, event: Event) -> None:
        """Show the right click on image menu."""
        try:
            self.rmenu.tk_popup(event.x_root, event.y_root)
        finally:
            self.rmenu.grab_release()

    def search_entry(self) -> None:
        """Search for entry."""
        entry_type = self._active_form or self.menubar.entry_type
        model_cls = self.logic.model_for(entry_type)
        if model_cls is None:
            messagebox.showerror("Search", f"Unsupported entry type: {entry_type}")
            return

        self._remember_current_form()
        self._reset_current_record()

        filters = self._gather_filters(entry_type, model_cls)
        if filters is None:
            return

        try:
            results = self.logic.search_entries(model_cls, filters)
        except Exception:
            logger.exception("search failed")
            messagebox.showerror(
                "Search",
                "Unable to query the database. Check logs for details.",
            )
            return

        if not results:
            messagebox.showinfo(
                "Search",
                f"No {entry_type.lower()} entries matched the provided values.",
            )
            self._clear_results()
            return

        self._search_results = results
        self._search_index = 0
        self._results_entry_type = entry_type
        self._display_result(self._search_index)
        messagebox.showinfo(
            "Search",
            (
                f"Found {len(results)} {entry_type.lower()} record(s). "
                "Use the arrows to browse them."
            ),
        )

    def _widget_value(self, widget: EntryWidget) -> str:
        if isinstance(widget, ctk.CTkTextbox):
            return cast(str, widget.get("1.0", tk.END).replace(SOFT_HYPHEN, "").strip())  # pyright: ignore[reportUnnecessaryCast]
        return widget.get().strip()

    def _form_value(self, entry_type: str, field_key: str) -> str:
        widget = self._get_form_widget(entry_type, field_key)
        if widget is None:
            return ""
        return self._widget_value(widget)

    @staticmethod
    def _stored_gender_value(value: str) -> str:
        normalized = value.strip().upper()
        return normalized or "UNSPECIFIED"

    @staticmethod
    def _gender_descriptor(value: str) -> str:
        normalized = value.strip().upper()
        if normalized in {"", "UNSPECIFIED"}:
            return ""
        mapping = {
            "FEMALE": "female",
            "MALE": "male",
            "NONBINARY": "nonbinary",
        }
        return mapping.get(normalized, normalized.lower())

    def _get_spec_map(self, entry_type: str) -> dict[str, FieldSpec]:
        return {spec.key: spec for spec in self._form_specs.get(entry_type, ())}

    def _collect_form_state(self, entry_type: str) -> dict[str, Any]:
        specs = self._get_spec_map(entry_type)
        values: dict[str, Any] = {}
        for key, widget in self._get_active_fields().items():
            spec = specs.get(key)
            if isinstance(widget, ctk.CTkTextbox):
                text = widget.get("1.0", tk.END)
                if not (spec and spec.is_json):
                    text = text.replace(SOFT_HYPHEN, "")
                values[key] = text.rstrip("\n")
            else:
                raw_value = widget.get().strip()
                if key == "gender":
                    values[key] = self._stored_gender_value(raw_value)
                else:
                    values[key] = raw_value
        return values

    def _gather_new_entry_context(
        self,
    ) -> tuple[str, type, str, dict[str, Any], dict[str, FieldSpec]]:
        entry_type = self._active_form or self.menubar.entry_type
        model_cls = self.logic.model_for(entry_type)
        if model_cls is None:
            msg = f"Unsupported entry type: {entry_type}"
            raise ValueError(msg)
        campaign_name = getattr(self.menubar, "campaign", "").strip()
        if campaign_name in {"", "New Campaign", "No Campaigns"}:
            msg = "Select an existing campaign before creating entries."
            raise ValueError(msg)
        field_values = self._collect_form_state(entry_type)
        spec_map = self._get_spec_map(entry_type)
        self.logic.validate_required_fields(model_cls, field_values, spec_map)
        return entry_type, model_cls, campaign_name, field_values, spec_map

    @staticmethod
    def _record_key_from_instance(
        entry_type: str,
        instance: Any,
    ) -> tuple[str, str] | None:
        identifier = TTRPGDataManager._extract_instance_identifier(entry_type, instance)
        if identifier in (None, ""):
            return None
        return entry_type, cast(str, identifier)  # pyright: ignore[reportUnnecessaryCast]

    @staticmethod
    def _extract_instance_identifier(entry_type: str, instance: Any) -> str | None:
        if entry_type == "Encounter":
            identifier = getattr(instance, "id", None)
        else:
            identifier = getattr(instance, "name", None)
        if identifier in (None, ""):
            return None
        return str(identifier)

    def _remember_image_override(self) -> None:
        if not self._image_dirty:
            return
        key = self._current_record_key
        if key is None or self._current_image_payload is None:
            self._image_dirty = False
            return
        self._pending_images[key] = self._current_image_payload
        self._image_dirty = False

    def _remember_current_form(self) -> None:
        key = self._current_record_key
        if key is None:
            return
        entry_type, _ = key
        state = self._collect_form_state(entry_type)
        self._pending_changes[key] = state
        if entry_type == "NPC":
            widget = self._get_faction_widget()
            if widget is not None:
                self._stage_faction_value(widget.get().strip())
        self._remember_image_override()

    def _has_pending_changes_for(self, key: tuple[str, str]) -> bool:
        return (
            key in self._pending_changes
            or key in self._pending_images
            or key in self._pending_faction_changes
        )

    def _reset_current_record(self) -> None:
        self._current_record_key = None
        self._current_image_payload = None
        self._image_dirty = False

    def show_previous_result(self) -> None:
        """Navigate to the previous search result."""
        if not self._search_results or self._search_index <= 0:
            return
        self._remember_current_form()
        self._display_result(self._search_index - 1)

    def show_next_result(self) -> None:
        """Navigate to the next search result."""
        if (
            not self._search_results
            or self._search_index >= len(self._search_results) - 1
        ):
            return
        self._remember_current_form()
        self._display_result(self._search_index + 1)

    def _display_result(self, index: int) -> None:
        if not self._search_results:
            return
        if index < 0 or index >= len(self._search_results):
            return
        self._search_index = index
        instance = self._search_results[index]
        entry_type = (
            self._results_entry_type or self._active_form or self.menubar.entry_type
        )
        self._current_record_key = self._record_key_from_instance(entry_type, instance)
        self._populate_form_from_instance(instance, entry_type)
        self._update_image_from_instance(entry_type, instance)
        if entry_type == "NPC":
            self._relationship_dialogs.refresh()
        elif entry_type == "Encounter":
            self._encounter_dialogs.refresh()
        self._update_navigation_state()

    def _show_next_result_after_delete(
        self,
        entry_type: str,
        identifier: str,
    ) -> bool:
        if not self._search_results or self._results_entry_type != entry_type:
            return False
        remaining: list[Any] = []
        removed_index: int | None = None
        for idx, instance in enumerate(self._search_results):
            current_id = self._extract_instance_identifier(entry_type, instance)
            if current_id == identifier and removed_index is None:
                removed_index = idx
                continue
            remaining.append(instance)
        if removed_index is None:
            return False
        self._search_results = remaining
        if not remaining:
            self._clear_results()
            return False
        self._search_index = min(removed_index, len(remaining) - 1)
        self._display_result(self._search_index)
        return True

    def _populate_form_from_instance(
        self,
        instance: Any,
        entry_type: str,
    ) -> None:
        specs = self._get_spec_map(entry_type)
        overrides: dict[str, Any] = {}
        key = self._record_key_from_instance(entry_type, instance)
        if key is not None:
            overrides = self._pending_changes.get(key, {})
        for field_key, widget in self._get_active_fields().items():
            if key is not None and field_key in overrides:
                value = overrides[field_key]
            else:
                value = getattr(instance, field_key, None)
            spec = specs.get(field_key)
            self._set_widget_value(widget, value, spec)
        if entry_type == "NPC":
            self._load_faction_membership(getattr(instance, "name", None))

    def _set_widget_value(
        self,
        widget: EntryWidget,
        value: Any,
        spec: FieldSpec | None,
    ) -> None:
        if value is None:
            text_value = ""
        elif isinstance(value, dtdate):
            text_value = value.isoformat()
        elif isinstance(value, dict):
            text_value = json.dumps(value, indent=2)
        else:
            text_value = str(value)

        if (
            spec
            and spec.key == "gender"
            and text_value.strip().upper() == "UNSPECIFIED"
        ):
            text_value = ""

        if isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", tk.END)
            if spec and not spec.is_json:
                text_value = self._hyphenate_text(text_value, widget)
            widget.insert("1.0", text_value)
            if spec and spec.is_json:
                self._highlight_json(widget)
        elif isinstance(widget, CTkEntry):
            widget.delete(0, tk.END)
            widget.insert(0, text_value)
        else:
            widget.set(text_value)

    def _load_preview_image(
        self,
        source: Path | bytes | bytearray | memoryview | None,
        *,
        mark_dirty: bool = False,
    ) -> bool:
        image_source: Path | bytes | bytearray | memoryview = (
            PLACEHOLDER_IMG if source is None else source
        )
        payload: bytes | None = None
        raw_input: Path | bytes
        if isinstance(image_source, Path):
            try:
                payload = image_source.read_bytes()
                raw_input = payload
            except OSError:
                logger.exception(
                    "failed to read image from disk: %s",
                    image_source,
                )
                if image_source == PLACEHOLDER_IMG:
                    self._current_image_payload = None
                    self._image_dirty = False
                    return False
                return self._load_preview_image(None, mark_dirty=False)
        else:
            payload = bytes(image_source)
            raw_input = payload
        try:
            self.placeholder_img = Img(raw_input, 400, 400)
        except Exception:
            logger.exception("failed to load preview image")
            if image_source == PLACEHOLDER_IMG:
                self._current_image_payload = None
                self._image_dirty = False
                return False
            return self._load_preview_image(None, mark_dirty=False)
        self._current_image_payload = None if source is None else payload
        self._image_dirty = mark_dirty
        self._refresh_image_preview()
        return True

    def _update_image_from_instance(self, entry_type: str, instance: Any) -> None:
        key = self._record_key_from_instance(entry_type, instance)
        if key is not None:
            override = self._pending_images.get(key)
            if override is not None:
                self._load_preview_image(override)
                return
        image_bytes = self._extract_image_bytes(instance)
        self._load_preview_image(image_bytes)

    @staticmethod
    def _extract_image_bytes(instance: Any) -> bytes | None:
        image_rel = getattr(instance, "image", None)
        if image_rel is not None:
            image_value = getattr(image_rel, "image_blob", None)
        else:
            image_value = getattr(instance, "image_blob", None)
        if image_value is None:
            return None
        if isinstance(image_value, memoryview):
            return image_value.tobytes()
        if isinstance(image_value, (bytes, bytearray)):
            return bytes(image_value)
        return None

    def _load_faction_membership(self, npc_name: str | None) -> None:
        widget = self._get_faction_widget()
        if widget is None:
            return
        if not npc_name:
            widget.set("")
            self._current_faction_value = None
            self._current_faction_note = ""
            self._update_faction_view_state("")
            return
        try:
            membership = self.logic.fetch_faction_membership(npc_name)
        except Exception:
            logger.exception("failed to load faction membership", npc=npc_name)
            membership = None
        if membership is None:
            widget.set("")
            self._current_faction_value = None
            self._current_faction_note = ""
            self._update_faction_view_state("")
            return
        faction_name, notes = membership
        self._ensure_faction_option(widget, faction_name)
        widget.set(faction_name)
        self._current_faction_value = faction_name
        self._current_faction_note = notes
        self._update_faction_view_state(faction_name)

    def _apply_pending_faction_for_new_record(self, npc_name: str) -> None:
        assignment = self._pending_faction_for_new_record
        if assignment is None:
            return
        if not npc_name:
            self._pending_faction_for_new_record = None
            return
        faction_name, notes = assignment
        try:
            if faction_name:
                self.logic.assign_faction_to_npc(npc_name, faction_name, notes)
            else:
                self.logic.clear_faction_membership(npc_name)
        except Exception:
            logger.exception("failed to assign faction to new npc", npc=npc_name)
            messagebox.showerror(
                "Faction",
                "Unable to save the faction membership for the new NPC.",
            )
            return
        self._current_faction_value = faction_name or None
        self._current_faction_note = notes
        self._pending_faction_for_new_record = None
        self._staged_faction_assignment = None
        self._update_faction_view_state(faction_name)

    def _apply_pending_faction_changes(
        self,
        renamed_keys: dict[tuple[str, str], tuple[str, str]],
    ) -> tuple[list[str], int]:
        for old_key, new_key in renamed_keys.items():
            payload = self._pending_faction_changes.pop(old_key, None)
            if payload is not None:
                self._pending_faction_changes[new_key] = payload
        failures: list[str] = []
        applied = 0
        for key, (faction_name, notes) in list(self._pending_faction_changes.items()):
            entry_type, identifier = key
            if entry_type != "NPC":
                continue
            try:
                if faction_name:
                    self.logic.assign_faction_to_npc(identifier, faction_name, notes)
                else:
                    self.logic.clear_faction_membership(identifier)
            except Exception:
                logger.exception("failed to update faction membership", npc=identifier)
                failures.append(identifier)
                continue
            del self._pending_faction_changes[key]
            if self._current_record_key and self._current_record_key[1] == identifier:
                self._current_faction_value = faction_name or None
                self._current_faction_note = notes
                self._update_faction_view_state(faction_name)
            if (
                self._staged_faction_assignment is not None
                and self._staged_faction_assignment[0] == faction_name
            ):
                self._staged_faction_assignment = None
            applied += 1
        return failures, applied

    def _refresh_image_preview(
        self,
        width_limit: int | None = None,
        height_limit: int | None = None,
    ) -> None:
        """Resize and display the current image using the left panel's bounds."""
        if not hasattr(self, "left_frame"):
            return
        if width_limit is None:
            width_limit = self._image_width_cap
        else:
            self._image_width_cap = width_limit
        if height_limit is None:
            height_limit = self._image_height_cap
        else:
            self._image_height_cap = height_limit
        available_height = max(self.left_frame.winfo_height() - 80, 120)
        available_width = max(self.left_frame.winfo_width() - 20, 120)
        target_width = min(available_width, width_limit)
        target_height = min(available_height, height_limit)
        self.placeholder_img.resize(target_width, target_height)
        self.image_label.configure(image=self.placeholder_img.ctkimage)

    def _gather_filters(
        self,
        entry_type: str,
        model_cls: type,
    ) -> list[tuple[str, Any, FieldSpec | None]] | None:
        specs = self._get_spec_map(entry_type)
        filters: list[tuple[str, Any, FieldSpec | None]] = []
        for key, widget in self._get_active_fields().items():
            spec = specs.get(key)
            if spec and spec.is_json:
                continue
            raw_value = self._widget_value(widget)
            if not raw_value:
                continue
            column = model_cls.__table__.columns.get(key)  # type: ignore[attr-defined]
            if column is None:
                continue
            try:
                converted = self.logic.coerce_value(column, raw_value)
            except ValueError:
                label = spec.label if spec else key
                messagebox.showerror("Search", f"Invalid value for {label}.")
                return None
            filters.append((key, converted, spec))

        campaign_value = getattr(self.menubar, "campaign", "").strip()
        campaign_column = model_cls.__table__.columns.get("campaign_name")  # type: ignore[attr-defined]
        if (
            campaign_column is not None
            and campaign_value
            and campaign_value not in {"New Campaign", "No Campaigns"}
        ):
            campaign_spec = FieldSpec(
                label="Campaign Name",
                key="campaign_name",
                enum_values=(campaign_value,),
            )
            filters.append(("campaign_name", campaign_value, campaign_spec))
        return filters

    def _clear_results(self) -> None:
        self._reset_current_record()
        self._search_results = []
        self._search_index = -1
        self._results_entry_type = None
        self._update_navigation_state()
        self._relationship_dialogs.refresh()
        self._encounter_dialogs.refresh()

    def _update_navigation_state(self) -> None:
        left_state = "disabled"
        right_state = "disabled"
        if self._search_results:
            if self._search_index > 0:
                left_state = "normal"
            if self._search_index < len(self._search_results) - 1:
                right_state = "normal"
        self.arrow_left.configure(state=left_state)
        self.arrow_right.configure(state=right_state)

    def _highlight_json(self, widget: ctk.CTkTextbox) -> None:
        """Apply simple syntax highlighting to JSON textboxes."""
        content = widget.get("1.0", tk.END)
        widget.tag_remove("json_string", "1.0", tk.END)
        widget.tag_remove("json_number", "1.0", tk.END)
        widget.tag_remove("json_key", "1.0", tk.END)
        widget.tag_remove("json_punct", "1.0", tk.END)

        widget.tag_config("json_string", foreground="#A6E22E")
        widget.tag_config("json_number", foreground="#AE81FF")
        widget.tag_config("json_key", foreground="#66D9EF")
        widget.tag_config("json_punct", foreground="#FD971F")

        index = 0
        for token_type, value in lex(content, get_lexer_by_name("json")):
            length = len(value)
            start = self._index_from_offset(widget, index)
            end = self._index_from_offset(widget, index + length)
            if token_type in Token.String:  # type: ignore[comparison-overlap]
                widget.tag_add("json_string", start, end)
            elif token_type in Token.Number:  # type: ignore[comparison-overlap]
                widget.tag_add("json_number", start, end)
            elif token_type in Token.Punctuation:  # type: ignore[comparison-overlap]
                widget.tag_add("json_punct", start, end)
            elif token_type in Token.Name:  # type: ignore[comparison-overlap]
                widget.tag_add("json_key", start, end)
            index += length

    def _format_json(self, widget: ctk.CTkTextbox) -> None:
        """Pretty print JSON when focus leaves the textbox."""
        content = widget.get("1.0", tk.END).strip()
        if not content:
            return
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return
        widget.delete("1.0", tk.END)
        widget.insert("1.0", json.dumps(parsed, indent=2))
        self._highlight_json(widget)

    @staticmethod
    def _index_from_offset(widget: ctk.CTkTextbox, offset: int) -> str:
        """Convert absolute char offset to tkinter text index."""
        return cast(str, widget.index(f"1.0+{offset}c"))  # pyright: ignore[reportUnnecessaryCast]

    def _make_highlight_handler(self, widget: ctk.CTkTextbox) -> Any:
        def _handler(event: Event) -> None:
            """Highlight JSON widget content."""
            del event
            self._highlight_json(widget)

        return _handler

    def _make_format_handler(self, widget: ctk.CTkTextbox) -> Any:
        def _handler(event: Event) -> None:
            """Format JSON widget content."""
            del event
            self._format_json(widget)

        return _handler

    def _hyphenate_text(self, text: str, widget: ctk.CTkTextbox | None = None) -> str:
        if not text:
            return ""
        cleaned = text.replace(SOFT_HYPHEN, "")
        max_chars = None
        if widget is not None:
            max_chars = self._estimate_line_capacity(widget)

        def _repl(match: re.Match[str]) -> str:
            word = match.group(0)
            if max_chars is None or len(word) <= max_chars:
                return word
            hyphenated = cast(str, self._hyphenator.inserted(word, SOFT_HYPHEN))  # type: ignore[no-untyped-call]
            return hyphenated or word

        return WORD_PATTERN.sub(_repl, cleaned)

    def _make_hyphenate_handler(self, widget: ctk.CTkTextbox) -> Any:
        def _handler(event: Event) -> None:
            """Hyphenate textbox content on focus loss."""
            del event
            text = widget.get("1.0", tk.END).rstrip("\n")
            hyphenated = self._hyphenate_text(text, widget)
            if text == hyphenated:
                return
            widget.delete("1.0", tk.END)
            widget.insert("1.0", hyphenated)

        return _handler

    def _estimate_line_capacity(self, widget: ctk.CTkTextbox) -> int:
        """Approximate how many characters fit on one line for the widget."""
        width_px = widget.winfo_width()
        if width_px <= 1:
            width_px = widget.winfo_reqwidth()
        if width_px <= 1:
            raw_width = cast(str | int | None, widget.cget("width"))
            try:
                width_px = int(raw_width) if raw_width is not None else 200
            except (TypeError, ValueError):
                width_px = 200
        font_descriptor = cast(str | tuple[str, int] | None, widget.cget("font"))
        if not font_descriptor:
            font_descriptor = ("TkDefaultFont", 12)
        font = tkfont.Font(font=font_descriptor)
        char_px = font.measure("M") or 8
        return max(int(width_px / char_px), 1)

    def resize(self, _event: Event) -> None:
        """Resize callback with threshold."""
        # Only update if change exceeds min pixels in either dimension
        if (
            abs(self.winfo_width() - self._last_size.width) < self.min_change_threshold
            and abs(self.winfo_height() - self._last_size.height)
            < self.min_change_threshold
        ):
            return

        # Store new size
        self._last_size = Size(self.winfo_width(), self.winfo_height())
        min_right_form_width = 700
        min_left_form_width = 200

        width = max(
            min_left_form_width,
            min(
                self.winfo_width() - min_right_form_width,
                int(self.winfo_width() * 0.8),
            ),
        )

        height = int(self.winfo_height())

        # Update CTkImage with new size
        self._refresh_image_preview(width, height)


if __name__ == "__main__":
    init()

# pyright: reportUnknownMemberType=false
# pyright: reportUnknownLambdaType=false
# ruff: noqa: I001

"""Custom CTK widget implementations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import customtkinter as ctk  # type: ignore[import-untyped]
from lazi.core import lazi

from final_project.db import create_campaign
from final_project.db import delete_campaign
from final_project.db import get_campaigns
from final_project.db import get_types
from final_project.dialogs import CampaignDialog

with lazi:  # type: ignore[attr-defined]
    import logging
    import re
    import textwrap
    import tkinter as tk
    from functools import cache
    from html import escape
    from html import unescape
    from html.parser import HTMLParser
    from pathlib import Path
    from tkinter import Event
    from tkinter import messagebox
    from typing import ClassVar
    from typing import cast

    import structlog
    import tkfontawesome as tkfa  # type: ignore[import-untyped]
    from PIL import Image
    from PIL import ImageChops
    from PIL import ImageFilter
    from PIL import ImageOps
    from PIL import ImageTk
    from tkhtmlview import HTMLScrolledText


logger = structlog.getLogger("final_project")
# disable debug in pillow
pil_logger = logging.getLogger("PIL")
pil_logger.setLevel(logging.INFO)
type CallableNoArgs = Callable[[], None]
ColorPair = tuple[str, str]
COLOR_PAIR_SIZE = 2


def _dict_str_any() -> dict[str, Any]:
    return {}


def _normalize_color_pair(value: Any, fallback: ColorPair) -> ColorPair:
    if isinstance(value, (list, tuple)):
        entries = [str(entry) for entry in value if isinstance(entry, str)]  # pyright: ignore[reportUnknownVariableType]
        if len(entries) >= COLOR_PAIR_SIZE:
            return (entries[0], entries[1])
    if isinstance(value, str):
        return (value, value)
    return fallback


def _normalize_menu_color(value: Any, fallback: ColorPair) -> str | ColorPair:
    if isinstance(value, str):
        return value
    return _normalize_color_pair(value, fallback)


@dataclass(slots=True)
class ButtonSpec:
    """Describe a menu/button widget using simple data."""

    text: str
    handler: CallableNoArgs
    disabled: bool = False
    config: dict[str, Any] = field(default_factory=_dict_str_any)


@dataclass(slots=True)
class DropdownSpec:
    """Describe a dropdown widget including its options and callbacks."""

    label: str
    options: tuple[str, ...]
    on_change: Callable[[str], None] | None = None
    initial: str | None = None
    state: str = "readonly"
    width: int = 140
    config: dict[str, Any] = field(default_factory=_dict_str_any)


class RadioField(ctk.CTkFrame):
    """Group radio buttons together so they behave like a single entry widget."""

    def __init__(
        self,
        master: ctk.CTkFrame,
        *,
        options: Sequence[tuple[str, str]],
        empty_value: str = "UNSPECIFIED",
        show_clear: bool = True,
    ) -> None:
        """Render all provided radio options plus an optional clear button."""
        super().__init__(master, fg_color="transparent")
        self._variable = tk.StringVar(value="")
        self._empty_value = empty_value.strip().upper()
        self._value_map = {value.strip().upper(): value.strip() for value, _ in options}
        for value, label in options:
            button = ctk.CTkRadioButton(
                self,
                text=label,
                value=value,
                variable=self._variable,
                width=0,
            )
            button.pack(side="left", padx=(0, 10))
        if show_clear and self._empty_value:
            ctk.CTkButton(self, text="Clear", width=60, command=self.clear).pack(
                side="left",
                padx=(4, 0),
            )

    def get(self) -> str:
        """Return the selected value in uppercase form."""
        value = self._variable.get().strip()
        return value.upper() if value else ""

    def set(self, value: str) -> None:
        """Select a matching radio button or clear the selection."""
        normalized = (value or "").strip().upper()
        mapped = self._value_map.get(normalized)
        if mapped is None:
            self._variable.set("")
            return
        self._variable.set(mapped)

    def clear(self) -> None:
        """Reset the control back to an unselected state."""
        self._variable.set("")


class AppMenuBar(ctk.CTkFrame):
    """A custom menu bar implementation."""

    def __init__(  # noqa: PLR0913, PLR0915
        self,
        master: ctk.CTk,
        on_save: CallableNoArgs,
        on_exit: CallableNoArgs,
        on_about: CallableNoArgs,
        on_show_readme: CallableNoArgs,
        on_show_settings: CallableNoArgs,
        *,
        on_entry_type_change: Callable[[str], None],
        on_delete_current_entry: Callable[[str], None],
        popup_offset_x: int = -15,
        **kwargs: Any,
    ) -> None:
        """Initialize."""
        super().__init__(master, height=28, corner_radius=0, **kwargs)  # pyright: ignore[reportCallIssue]

        # References
        self._root_win: ctk.CTk = master
        self._on_save: CallableNoArgs = on_save
        self._on_exit: CallableNoArgs = on_exit
        self._on_about: CallableNoArgs = on_about
        self._on_show_readme: CallableNoArgs = on_show_readme
        self._on_show_settings: CallableNoArgs = on_show_settings
        self._on_entry_type_change: Callable[[str], None] = on_entry_type_change
        self._on_delete_current_entry: Callable[[str], None] = on_delete_current_entry
        self._on_campaign_change_cb: Callable[[str], None] | None = None
        self._menubar_popup_offset_x: int = popup_offset_x

        # --- Theme extraction ----------------------------------------------------
        theme: dict[str, Any] = cast(dict[str, Any], ctk.ThemeManager.theme)

        frame_cfg: dict[str, Any] = theme.get("CTkFrame", {})
        label_cfg: dict[str, Any] = theme.get("CTkLabel", {})
        dropdown_cfg: dict[str, Any] = theme.get("DropdownMenu", {})

        frame_default: ColorPair = ("gray90", "gray13")
        label_default: ColorPair = ("#111111", "#EDEDED")
        dropdown_default: ColorPair = ("#FFFFFF", "#2A2A2A")

        topbar_bg = _normalize_color_pair(
            frame_cfg.get("top_fg_color", frame_cfg.get("fg_color")),
            frame_default,
        )
        base_text = _normalize_color_pair(label_cfg.get("text_color"), label_default)

        menu_bg = _normalize_color_pair(
            dropdown_cfg.get("fg_color", frame_cfg.get("fg_color")),
            dropdown_default,
        )
        menu_hover = _normalize_menu_color(
            dropdown_cfg.get("hover_color", topbar_bg),
            topbar_bg,
        )
        menu_text = _normalize_menu_color(
            dropdown_cfg.get("text_color", base_text),
            base_text,
        )

        self._menu_active_bg = menu_hover
        base_font: ctk.CTkFont = ctk.CTkFont()

        # ------------------------------------------------------------------------
        # This frame *is* the top bar
        # ------------------------------------------------------------------------
        self.configure(fg_color=topbar_bg)  # pyright: ignore[reportUnknownMemberType]

        # --------------------- HEADER BUTTONS -----------------------------------
        self.file_btn: ctk.CTkButton = ctk.CTkButton(
            self,
            text="File",
            width=60,
            height=26,
            fg_color="transparent",
            hover_color=menu_hover,
            corner_radius=0,
            anchor="w",
            text_color=menu_text,
            font=base_font,
            command=self._toggle_file_menu,
        )
        self.file_btn.pack(side="left", padx=(6, 0), pady=1)

        self.help_btn: ctk.CTkButton = ctk.CTkButton(
            self,
            text="Help",
            width=60,
            height=26,
            fg_color="transparent",
            hover_color=menu_hover,
            corner_radius=0,
            anchor="w",
            text_color=menu_text,
            font=base_font,
            command=self._toggle_help_menu,
        )
        self.help_btn.pack(side="left", padx=(0, 0), pady=1)

        # Hover-switching (Windows-like behavior)
        self.file_btn.bind("<Enter>", lambda e: self._menu_header_hover("file"))  # noqa: ARG005
        self.help_btn.bind("<Enter>", lambda e: self._menu_header_hover("help"))  # noqa: ARG005

        # --------------------- RIGHT-SIDE DROPDOWNS -----------------------------
        types = get_types()
        self.entry_type_var: tk.StringVar = tk.StringVar(value=types[0])
        campaigns = get_campaigns()
        combo_values = [*(campaigns or ["No Campaigns"]), "New Campaign"]
        initial_campaign = campaigns[0] if campaigns else "No Campaigns"
        self.campaign_var: tk.StringVar = tk.StringVar(value=initial_campaign)

        entry_type_spec = DropdownSpec(
            label="Entry Type",
            options=tuple(types),
            on_change=self._on_type_change,
            initial=types[0],
            state="readonly",
            width=120,
            config={"font": base_font, "variable": self.entry_type_var},
        )
        campaign_spec = DropdownSpec(
            label="Campaign",
            options=tuple(combo_values),
            on_change=self._on_campaign_change,
            initial=initial_campaign,
            state="readonly",
            width=140,
            config={"font": base_font, "variable": self.campaign_var},
        )

        self.entry_type_combo: ctk.CTkComboBox = self._create_dropdown(
            self,
            entry_type_spec,
            pack_kwargs={"side": "right", "padx": (0, 8), "pady": 2},
        )
        self.campaign_combo: ctk.CTkComboBox = self._create_dropdown(
            self,
            campaign_spec,
            pack_kwargs={"side": "right", "padx": 5, "pady": 2},
        )
        self._campaign_dialog: CampaignDialog | None = None
        self._suppress_campaign_callback = False
        self._suppress_entry_type_callback = False
        self._last_campaign_value = initial_campaign

        # --------------------- POPUP MENUS --------------------------------------
        border_color: list[str] = frame_cfg.get("border_color", ["gray65", "gray28"])

        common_menu_kwargs: dict[str, Any] = {
            "corner_radius": 6,
            "border_width": 1,
            "border_color": border_color,
            "fg_color": menu_bg,
        }

        # Popups live on the root so they overlap all content
        self.file_menu_frame: ctk.CTkFrame = ctk.CTkFrame(
            self._root_win,
            **common_menu_kwargs,
        )
        self.help_menu_frame: ctk.CTkFrame = ctk.CTkFrame(
            self._root_win,
            **common_menu_kwargs,
        )

        # File menu items
        delete_label = self._format_delete_current_label(types[0])
        file_menu_specs = [
            ButtonSpec(text="Save", handler=self._menu_action(self._on_save)),
            ButtonSpec(
                text="Settings",
                handler=self._menu_action(self._on_show_settings),
            ),
            ButtonSpec(
                text=delete_label,
                handler=self._menu_action(self._handle_delete_current_entry),
            ),
            ButtonSpec(
                text="Delete Campaign…",
                handler=self._menu_action(self._confirm_delete_current_campaign),
            ),
            ButtonSpec(text="Exit", handler=self._menu_action(self._on_exit)),
        ]
        self._file_menu_buttons = self._build_menu_buttons(
            self.file_menu_frame,
            file_menu_specs,
            menu_text=menu_text,
            menu_hover=menu_hover,
            font=base_font,
        )
        self._delete_current_button: ctk.CTkButton | None = None
        self._delete_current_button = self._file_menu_buttons[2]

        # Help menu items
        help_menu_specs = [
            ButtonSpec(
                text="View README",
                handler=self._menu_action(self._on_show_readme),
            ),
            ButtonSpec(text="About", handler=self._menu_action(self._on_about)),
        ]
        self._help_menu_buttons = self._build_menu_buttons(
            self.help_menu_frame,
            help_menu_specs,
            menu_text=menu_text,
            menu_hover=menu_hover,
            font=base_font,
        )

        # --------------------- MENU NAV STATE -----------------------------------
        self._active_menu: str | None = None
        self._menu_items: list[ctk.CTkButton] = []
        self._menu_index: int = -1

        # Global bindings
        self._root_win.bind("<Button-1>", self._on_root_click, add="+")
        self._root_win.bind_all("<Alt-f>", lambda e: self._toggle_file_menu())  # pyright: ignore[reportUnknownLambdaType] # noqa: ARG005
        self._root_win.bind_all("<Alt-F>", lambda e: self._toggle_file_menu())  # pyright: ignore[reportUnknownLambdaType] # noqa: ARG005
        self._root_win.bind_all("<Alt-h>", lambda e: self._toggle_help_menu())  # pyright: ignore[reportUnknownLambdaType] # noqa: ARG005
        self._root_win.bind_all("<Alt-H>", lambda e: self._toggle_help_menu())  # pyright: ignore[reportUnknownLambdaType] # noqa: ARG005

    # ==========================================================================
    # Public API
    # ==========================================================================

    @property
    def campaign(self) -> str:
        """Return the currently selected campaign name."""
        return self.campaign_var.get()

    @property
    def entry_type(self) -> str:
        """Return the currently selected entry type."""
        return self.entry_type_var.get()

    def set_campaign_change_handler(self, handler: Callable[[str], None]) -> None:
        """Register callback invoked when the campaign selector changes."""
        self._on_campaign_change_cb = handler

    def select_entry_type(
        self,
        entry_type: str,
        *,
        notify: bool = True,
    ) -> bool:
        """Programmatically choose an entry type and notify listeners."""
        normalized = entry_type.strip()
        options = set(get_types())
        if normalized not in options:
            return False
        self._set_entry_type_selection(normalized, notify=notify)
        return True

    def select_first_campaign(self, *, notify: bool = True) -> bool:
        """Select the first available campaign, if any."""
        campaigns = get_campaigns()
        target = campaigns[0] if campaigns else "No Campaigns"
        self._set_campaign_selection(target, notify=notify)
        return bool(campaigns)

    def refresh_campaigns(
        self,
        *,
        select: str | None = None,
        notify: bool = True,
    ) -> None:
        """Reload campaign dropdown options after external data changes."""
        self._refresh_campaign_options(select=select, notify=notify)

    # ==========================================================================
    # Internal Helpers
    # ==========================================================================

    def _hide_all_menus(self) -> None:
        """Hide all dropdowns and clear highlight / keyboard bindings."""
        for frame_name in ("file_menu_frame", "help_menu_frame"):
            frame = getattr(self, frame_name, None)
            if frame is not None:
                frame.place_forget()

        for btn in self._menu_items:
            btn.configure(fg_color="transparent")

        self._active_menu = None
        self._menu_items = []
        self._menu_index = -1

        for seq in ("<Up>", "<Down>", "<Return>", "<Escape>"):
            self._root_win.unbind_all(seq)

    def _menu_action(self, action: CallableNoArgs) -> CallableNoArgs:
        """Wrap a menu callback so popups close before execution."""

        def _runner() -> None:
            self._hide_all_menus()
            action()

        return _runner

    def _build_menu_buttons(
        self,
        parent: ctk.CTkFrame,
        specs: Sequence[ButtonSpec],
        *,
        menu_text: str | tuple[str, str] | None,
        menu_hover: str | tuple[str, str] | None,
        font: ctk.CTkFont,
    ) -> list[ctk.CTkButton]:
        buttons: list[ctk.CTkButton] = []
        total = len(specs)
        for index, spec in enumerate(specs):
            btn = ctk.CTkButton(
                parent,
                text=spec.text,
                width=160,
                height=26,
                fg_color="transparent",
                corner_radius=4,
                anchor="w",
                text_color=menu_text,
                hover_color=menu_hover,
                font=font,
                state="disabled" if spec.disabled else "normal",
                command=spec.handler,
                **spec.config,
            )
            pady = (4, 2) if index == 0 else (0, 4) if index == total - 1 else (0, 2)
            btn.pack(fill="x", padx=4, pady=pady)
            buttons.append(btn)
        return buttons

    def _format_delete_current_label(self, entry_type: str) -> str:
        normalized = entry_type.strip() or "Entry"
        return f"Delete Current {normalized}"

    def _update_delete_current_label(self, entry_type: str) -> None:
        if self._delete_current_button is None:
            return
        self._delete_current_button.configure(
            text=self._format_delete_current_label(entry_type),
        )

    def _create_dropdown(
        self,
        parent: tk.Misc,
        spec: DropdownSpec,
        *,
        pack_kwargs: dict[str, Any],
    ) -> ctk.CTkComboBox:
        combo = ctk.CTkComboBox(
            parent,
            values=list(spec.options),
            width=spec.width,
            state=spec.state,
            **spec.config,
        )
        variable = spec.config.get("variable")
        if spec.initial is not None:
            if isinstance(variable, tk.StringVar):
                variable.set(spec.initial)
            else:
                combo.set(spec.initial)
        if spec.on_change is not None:
            combo.configure(command=spec.on_change)
        combo.pack(**pack_kwargs)
        return combo

    def _refresh_campaign_options(
        self,
        select: str | None = None,
        *,
        notify: bool = False,
    ) -> None:
        campaigns = get_campaigns()
        values = [*(campaigns or ["No Campaigns"]), "New Campaign"]
        combo = cast(Any, self.campaign_combo)
        combo.configure(values=values)
        target = select or (campaigns[0] if campaigns else "No Campaigns")
        self._set_campaign_selection(target, notify=notify)

    def _set_campaign_selection(self, selection: str, *, notify: bool) -> None:
        value = selection or "No Campaigns"
        self._suppress_campaign_callback = True
        combo = cast(Any, self.campaign_combo)
        combo.set(value)
        self.campaign_var.set(value)
        self._suppress_campaign_callback = False
        self._last_campaign_value = value
        if notify and self._on_campaign_change_cb is not None:
            self._on_campaign_change_cb(value)

    def _set_entry_type_selection(self, selection: str, *, notify: bool) -> None:
        self._suppress_entry_type_callback = True
        combo = cast(Any, self.entry_type_combo)
        combo.set(selection)
        self.entry_type_var.set(selection)
        self._suppress_entry_type_callback = False
        if notify:
            self._on_entry_type_change(selection)

    def _show_new_campaign_dialog(self) -> None:
        if self._campaign_dialog is not None and self._campaign_dialog.winfo_exists():
            self._campaign_dialog.lift()
            self._campaign_dialog.focus_force()
            return
        self._campaign_dialog = CampaignDialog(
            self._root_win,
            on_submit=self._handle_campaign_dialog_submit,
            on_cancel=self._handle_campaign_dialog_cancel,
        )

    def _handle_campaign_dialog_submit(
        self,
        name: str,
        start_date: str,
        status: str,
    ) -> None:
        try:
            create_campaign(name, start_date, status)
        except ValueError as exc:
            messagebox.showerror("New Campaign", str(exc))
            return
        except RuntimeError as exc:
            messagebox.showerror("New Campaign", str(exc))
            return
        messagebox.showinfo(
            "New Campaign",
            f"Campaign '{name}' created successfully.",
        )
        if self._campaign_dialog is not None:
            self._campaign_dialog.destroy()
            self._campaign_dialog = None
        self._refresh_campaign_options(select=name, notify=True)

    def _handle_campaign_dialog_cancel(self) -> None:
        self._campaign_dialog = None
        self._set_campaign_selection(self._last_campaign_value, notify=False)

    def _confirm_delete_current_campaign(self) -> None:
        campaign = self.campaign_var.get().strip()
        if campaign in {"", "No Campaigns", "New Campaign"}:
            messagebox.showwarning(
                "Delete Campaign",
                "Select an existing campaign before deleting.",
            )
            return
        if not messagebox.askyesno(
            "Delete Campaign",
            (
                f"Are you sure you want to delete the campaign '{campaign}'?\n"
                "All NPCs, locations, encounters, and related data will"
                " also be removed."
            ),
            icon="warning",
        ):
            return
        try:
            delete_campaign(campaign)
        except ValueError as exc:
            messagebox.showerror("Delete Campaign", str(exc))
            return
        except RuntimeError as exc:
            messagebox.showerror("Delete Campaign", str(exc))
            return
        messagebox.showinfo(
            "Delete Campaign",
            f"Campaign '{campaign}' and associated data have been deleted.",
        )
        self._refresh_campaign_options(notify=True)

    def _handle_delete_current_entry(self) -> None:
        """Route delete requests to the host using the active entry type."""
        self._on_delete_current_entry(self.entry_type)

    # ----------------------- FILE MENU ----------------------------------------

    def _toggle_file_menu(self) -> None:
        if self.file_menu_frame.winfo_ismapped() and self._active_menu == "file":
            self._hide_all_menus()
            return

        self._hide_all_menus()
        self._root_win.update_idletasks()

        btn_x: int = self.file_btn.winfo_rootx() - self._root_win.winfo_rootx()
        popup_x: int = btn_x  # File aligns flush-left

        y: int = self.winfo_height()
        start_y: int = y - 10

        self.file_menu_frame.place(x=popup_x, y=start_y)
        self.file_menu_frame.lift()
        self._animate_drop(self.file_menu_frame, start_y, y)

        self._open_menu("file", self._file_menu_buttons)

    # ----------------------- HELP MENU ----------------------------------------

    def _toggle_help_menu(self) -> None:
        if self.help_menu_frame.winfo_ismapped() and self._active_menu == "help":
            self._hide_all_menus()
            return

        self._hide_all_menus()
        self._root_win.update_idletasks()
        self.help_menu_frame.update_idletasks()

        btn_x: int = self.help_btn.winfo_rootx() - self._root_win.winfo_rootx()
        popup_x: int = btn_x + self._menubar_popup_offset_x

        y: int = self.winfo_height()

        start_y: int = y - 10

        self.help_menu_frame.place(x=popup_x, y=start_y)
        self.help_menu_frame.lift()
        self._animate_drop(self.help_menu_frame, start_y, y)

        self._open_menu("help", self._help_menu_buttons)

    # ----------------------- CLOSE WHEN CLICK OUTSIDE -------------------------

    def _on_root_click(self, event: Event) -> None:
        widget = event.widget

        # Click on header?
        if (
            widget in (self.file_btn, self.help_btn)
            or str(widget).startswith(str(self.file_btn))
            or str(widget).startswith(str(self.help_btn))
        ):
            return

        # Click inside popup?
        for frame in (self.file_menu_frame, self.help_menu_frame):
            if widget == frame or str(widget).startswith(str(frame)):
                return

        self._hide_all_menus()

    # ----------------------- ANIMATION ----------------------------------------

    def _animate_drop(
        self,
        frame: ctk.CTkFrame,
        start_y: int,
        end_y: int,
        steps: int = 6,
        step: int = 0,
    ) -> None:
        if step >= steps:
            frame.place_configure(y=end_y)
            return

        new_y: int = int(start_y + (end_y - start_y) * (step + 1) / steps)
        frame.place_configure(y=new_y)

        self.after(
            18,
            lambda: self._animate_drop(frame, start_y, end_y, steps, step + 1),
        )

    # ----------------------- KEYBOARD NAV -------------------------------------

    def _open_menu(self, name: str, items: list[ctk.CTkButton]) -> None:
        self._active_menu = name
        self._menu_items = items
        self._menu_index = -1

        for seq in ("<Up>", "<Down>", "<Return>", "<Escape>"):
            self._root_win.bind_all(seq, self._menu_key_nav)

    def _update_menu_highlight(self) -> None:
        active_bg = self._menu_active_bg

        for i, btn in enumerate(self._menu_items):
            if i == self._menu_index >= 0:
                btn.configure(fg_color=active_bg)
            else:
                btn.configure(fg_color="transparent")

    def _menu_key_nav(self, event: Event) -> str | None:
        if not self._menu_items:
            return None

        if event.keysym == "Down":
            self._menu_index = (
                0
                if self._menu_index < 0
                else ((self._menu_index + 1) % len(self._menu_items))
            )
            self._update_menu_highlight()
            self._menu_items[self._menu_index].focus_set()
            return "break"

        if event.keysym == "Up":
            self._menu_index = (
                len(self._menu_items) - 1
                if self._menu_index < 0
                else (self._menu_index - 1) % len(self._menu_items)
            )
            self._update_menu_highlight()
            self._menu_items[self._menu_index].focus_set()
            return "break"

        if event.keysym in ("Return", "KP_Enter"):
            if self._menu_index >= 0:
                self._menu_items[self._menu_index].invoke()
            return "break"

        if event.keysym == "Escape":
            self._hide_all_menus()
            return "break"

        return None

    # ----------------------- HOVER SWITCHING ----------------------------------

    def _menu_header_hover(self, name: str) -> None:
        if self._active_menu is None:
            return

        if name == "file" and self._active_menu != "file":
            self._toggle_file_menu()
        elif name == "help" and self._active_menu != "help":
            self._toggle_help_menu()

    def _on_campaign_change(self, selection: str) -> None:
        """Show placeholder UI when the user opts to create a new campaign."""
        if self._suppress_campaign_callback:
            return
        if selection == "New Campaign":
            self._show_new_campaign_dialog()
            self._set_campaign_selection(self._last_campaign_value, notify=False)
            return
        self._last_campaign_value = selection
        if self._on_campaign_change_cb is not None:
            self._on_campaign_change_cb(selection)

    def _on_type_change(self, selection: str) -> None:
        """Notify host when the entry type selection changes."""
        if self._suppress_entry_type_callback:
            return
        self._update_delete_current_label(selection)
        self._on_entry_type_change(selection)


class HtmlPreviewWindow(ctk.CTkToplevel):
    """Display rendered HTML content inside a scrollable CustomTkinter window."""

    TABLE_PATTERN = re.compile(r"<table\b.*?>.*?</table>", re.IGNORECASE | re.DOTALL)
    MIN_COL_WIDTH = 3
    PRE_PADDING_CHARS = 25
    USE_UNICODE_TABLES = True
    UNICODE_BORDER_MAP: ClassVar[dict[tuple[str, str], tuple[str, str, str]]] = {
        ("top", "-"): ("┌", "┬", "┐"),
        ("middle", "-"): ("├", "┼", "┤"),
        ("bottom", "-"): ("└", "┴", "┘"),
        ("top", "="): ("╒", "╤", "╕"),
        ("header", "="): ("╞", "╪", "╡"),
        ("middle", "="): ("╞", "╪", "╡"),
        ("bottom", "="): ("╘", "╧", "╛"),
    }

    class _AsciiTableParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.rows: list[tuple[bool, list[str]]] = []
            self._current_row: list[str] = []
            self._current_row_is_header = False
            self._capturing_cell = False
            self._cell_buffer: list[str] = []

        def handle_starttag(
            self,
            tag: str,
            attrs: list[tuple[str, str | None]],
        ) -> None:
            del attrs
            if tag == "tr":
                self._current_row = []
                self._current_row_is_header = False
            elif tag in {"td", "th"}:
                self._capturing_cell = True
                self._cell_buffer = []
                if tag == "th":
                    self._current_row_is_header = True

        def handle_endtag(self, tag: str) -> None:
            if tag in {"td", "th"} and self._capturing_cell:
                text = unescape("".join(self._cell_buffer).strip())
                self._current_row.append(text)
                self._capturing_cell = False
                self._cell_buffer = []
            elif tag == "tr" and self._current_row:
                self.rows.append((self._current_row_is_header, self._current_row))
                self._current_row = []
                self._current_row_is_header = False

        def handle_data(self, data: str) -> None:
            if self._capturing_cell:
                self._cell_buffer.append(data)

    def __init__(
        self,
        master: ctk.CTk,
        *,
        title: str,
        initial_html: str,
        source_path: Path,
        on_close: CallableNoArgs,
    ) -> None:
        """Initialize the modal window and populate it with HTML text."""
        super().__init__(master)
        self._on_close = on_close
        self.source_path = source_path
        self.title(title)
        size = (960, 640)
        self.geometry("x".join(map(str, size)))
        self.minsize(*size)
        self.maxsize(*size)
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.transient(master)
        self.grab_set()
        self.focus_force()
        self._display_mode = "rendered"
        self._rendered_html = initial_html

        container = ctk.CTkFrame(self)
        container.pack(fill="both", expand=True, padx=16, pady=12)
        self.html_view = HTMLScrolledText(
            container,
            html=initial_html,
            width=100,
            height=30,
            relief="flat",
            background=self._resolve_tk_color(container),
        )
        self.html_view.pack(fill="both", expand=True)

        button_bar = ctk.CTkFrame(self, fg_color="transparent")
        button_bar.pack(fill="x", padx=16, pady=(0, 16))
        self.toggle_button = ctk.CTkButton(
            button_bar,
            text="Show Raw HTML",
            width=140,
            command=self._toggle_mode,
        )
        self.toggle_button.pack(side="left")
        ctk.CTkButton(button_bar, text="Close", command=self._handle_close).pack(
            side="right",
        )

    def load_content(self, html_output: str, source_path: Path | None = None) -> None:
        """Replace the current HTML text and update the source label."""
        if source_path is not None:
            self.source_path = source_path
        self._rendered_html = html_output
        if self._display_mode == "rendered":
            self.html_view.set_html(self._rendered_html)
        else:
            self._load_raw_html()

    def _handle_close(self) -> None:
        self.destroy()
        self._on_close()

    def _toggle_mode(self) -> None:
        self._display_mode = "raw" if self._display_mode == "rendered" else "rendered"
        if self._display_mode == "rendered":
            self.html_view.set_html(self._rendered_html)
            self.toggle_button.configure(text="Show Raw HTML")
        else:
            self._load_raw_html()
            self.toggle_button.configure(text="Show Rendered HTML")

    def _load_raw_html(self) -> None:
        self.html_view.set_html(f"<pre>{self._escape_html(self._rendered_html)}</pre>")

    @staticmethod
    def _escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _resolve_tk_color(widget: Any) -> str:
        fg_color = getattr(widget, "fg_color", None)
        if isinstance(fg_color, (tuple, list)) and fg_color:
            mode = ctk.get_appearance_mode()
            index = 0 if mode == "Light" else -1
            color = cast(Any, fg_color[index])
            return str(color)
        if isinstance(fg_color, str):
            return fg_color
        return "#FFFFFF" if ctk.get_appearance_mode() == "Light" else "#1C1C1C"

    @classmethod
    def prepare_html(cls, html_content: str, max_chars: int | None) -> str:
        """Convert HTML tables into ASCII blocks sized for the preview window."""
        return cls._replace_tables_with_ascii_blocks(html_content, max_chars)

    @classmethod
    def _replace_tables_with_ascii_blocks(
        cls,
        html_content: str,
        max_chars: int | None,
    ) -> str:
        def _convert(match: re.Match[str]) -> str:
            return cls._table_match_to_pre(match, max_chars)

        try:
            return cls.TABLE_PATTERN.sub(_convert, html_content)
        except re.error:
            logger.exception("failed to replace tables with ascii blocks")
            return html_content

    @classmethod
    def _table_match_to_pre(cls, match: re.Match[str], max_chars: int | None) -> str:
        parser = cls._AsciiTableParser()
        snippet = match.group(0)
        try:
            parser.feed(snippet)
            parser.close()
        except Exception:
            logger.exception("failed to parse html table")
            return snippet
        ascii_table = cls._render_ascii_table(parser.rows, max_chars)
        if not ascii_table.strip():
            return snippet
        return f'<pre class="ascii-table">\n{escape(ascii_table)}\n</pre>'

    @classmethod
    def _render_ascii_table(
        cls,
        rows: list[tuple[bool, list[str]]],
        max_chars: int | None,
    ) -> str:
        if not rows:
            return ""
        column_count = max((len(row) for _, row in rows), default=0)
        if column_count == 0:
            return ""
        padded_rows = [
            (is_header, row + [""] * (column_count - len(row)))
            for is_header, row in rows
        ]
        col_widths = [
            max(len(row[i]) for _, row in padded_rows) for i in range(column_count)
        ]
        col_widths = cls._compress_column_widths(col_widths, column_count, max_chars)

        def _format_row(row: list[str]) -> list[str]:
            wrapped_cells = [
                cls._wrap_cell_lines(value, col_widths[index])
                for index, value in enumerate(row)
            ]
            max_lines = max((len(lines) for lines in wrapped_cells), default=1)
            normalized = [
                lines + [""] * (max_lines - len(lines)) for lines in wrapped_cells
            ]
            row_lines: list[str] = []
            for line_index in range(max_lines):
                cells: list[str] = []
                for col_index in range(column_count):
                    cell_value = normalized[col_index][line_index].ljust(
                        col_widths[col_index],
                    )
                    cells.append(f" {cell_value} ")
                row_lines.append("|" + "|".join(cells) + "|")
            return row_lines

        header_line = cls._build_line(col_widths, "=")
        border_line = cls._build_line(col_widths, "-")
        output: list[str] = [border_line]
        for is_header, row in padded_rows:
            output.extend(_format_row(row))
            output.append(header_line if is_header else border_line)
        if cls.USE_UNICODE_TABLES:
            output = cls._apply_unicode_box_chars(output)
        return "\n".join(output)

    @staticmethod
    def _build_line(col_widths: list[int], fill: str) -> str:
        segments = (fill * (width + 2) for width in col_widths)
        return "+" + "+".join(segments) + "+"

    @classmethod
    def _compress_column_widths(
        cls,
        widths: list[int],
        column_count: int,
        max_chars: int | None,
    ) -> list[int]:
        if max_chars is None or column_count == 0:
            return widths
        static_overhead = (3 * column_count) + 1
        allowance = max_chars - static_overhead
        if allowance <= 0:
            return widths
        total = sum(widths)
        if total <= allowance:
            return widths
        adjusted = widths[:]
        while total > allowance:
            index = max(range(column_count), key=adjusted.__getitem__)
            if adjusted[index] <= cls.MIN_COL_WIDTH:
                break
            adjusted[index] -= 1
            total -= 1
        return adjusted

    @staticmethod
    def _wrap_cell_lines(value: str, width: int) -> list[str]:
        if width <= 0:
            return [""]
        stripped = value.strip()
        if not stripped:
            return [""]
        segments = textwrap.wrap(
            stripped,
            width=width,
            break_long_words=True,
            drop_whitespace=False,
        )
        return segments or [""]

    @classmethod
    def _apply_unicode_box_chars(cls, lines: list[str]) -> list[str]:
        if not lines:
            return lines
        last_index = len(lines) - 1
        converted: list[str] = []
        for idx, line in enumerate(lines):
            if not line:
                converted.append(line)
                continue
            if line.startswith("|"):
                converted.append(line.replace("|", "│"))
                continue
            if not line.startswith("+"):
                converted.append(line)
                continue
            fill_char = "=" if "=" in line else "-"
            if idx == 0:
                role = "top"
            elif idx == last_index:
                role = "bottom"
            elif fill_char == "=":
                role = "header"
            else:
                role = "middle"
            converted.append(cls._convert_border_line(line, role, fill_char))
        return converted

    @classmethod
    def _convert_border_line(cls, line: str, role: str, fill_char: str) -> str:
        left, mid, right = cls.UNICODE_BORDER_MAP.get(
            (role, fill_char),
            ("┼", "┼", "┼"),
        )
        horizontal = "═" if fill_char == "=" else "─"
        chars = list(line)
        plus_positions = [index for index, char in enumerate(chars) if char == "+"]
        for offset, position in enumerate(plus_positions):
            if offset == 0:
                chars[position] = left
            elif offset == len(plus_positions) - 1:
                chars[position] = right
            else:
                chars[position] = mid
        replacement_target = "=" if fill_char == "=" else "-"
        chars = [horizontal if char == replacement_target else char for char in chars]
        return "".join(chars)


class RandomIcon(ctk.CTkLabel):
    """Reusable dice-in-arrows overlay widget."""

    def __init__(
        self,
        master: tk.Misc | None = None,
        *,
        command: CallableNoArgs | None = None,
        height: int = 36,
        **kwargs: Any,
    ) -> None:
        """Create a themed overlay icon with an optional click callback."""
        self._command = command
        self._icon = self._build_random_icon(height)
        self._disabled_icon = self._build_random_icon(height, disabled=True)
        self._enabled = True
        kwargs.setdefault("text", "")
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("bg_color", "transparent")
        kwargs.setdefault("cursor", "hand2")
        super().__init__(master, image=self._icon, **kwargs)
        self.bind("<ButtonRelease-1>", self._handle_click)

    def _handle_click(self, event: Event) -> None:
        del event
        if not self._enabled:
            return
        if self._command is not None:
            self._command()

    def set_command(self, command: CallableNoArgs | None) -> None:
        """Update the callback invoked on click."""
        self._command = command

    def set_enabled(self, enabled: bool) -> None:
        """Toggle the icon's interactivity and appearance."""
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.configure(
            image=self._icon if enabled else self._disabled_icon,
            cursor="hand2" if enabled else "arrow",
        )

    @staticmethod
    @cache
    def _build_random_icon(height: int = 36, *, disabled: bool = False) -> ctk.CTkImage:
        """Return a CTkImage that layers a die inside the recycle glyph."""
        recycle_img = tkfa.icon_to_image(  # pyright: ignore[reportUnknownMemberType]
            "rotate",
            fill="black",
            scale_to_height=height,
        )
        dice_img = tkfa.icon_to_image(  # pyright: ignore[reportUnknownMemberType]
            "dice-three",
            fill="black",
            scale_to_height=max(height // 2, 6),
        )
        recycle_photo = cast(Any, recycle_img)
        dice_photo = cast(Any, dice_img)
        base = ImageTk.getimage(recycle_photo).copy().convert("RGBA")
        alpha = base.getchannel("A")
        eroded = alpha.filter(ImageFilter.MinFilter(size=3))
        thickness_delta = ImageChops.subtract(alpha, eroded)
        mask = thickness_delta.filter(ImageFilter.GaussianBlur(radius=1))
        mask = ImageOps.autocontrast(mask)
        adaptive_alpha = Image.composite(eroded, alpha, mask)
        edges = adaptive_alpha.filter(ImageFilter.FIND_EDGES)
        combined_alpha = ImageChops.lighter(adaptive_alpha, edges)
        combined_alpha = combined_alpha.filter(ImageFilter.MaxFilter(size=3))
        combined_alpha = combined_alpha.filter(ImageFilter.MinFilter(size=3))

        hard_edge_cutoff = 254

        def _hard_edge(alpha_value: int) -> int:
            return 255 if alpha_value > hard_edge_cutoff else 0

        combined_alpha = combined_alpha.point(_hard_edge)  # pyright: ignore[reportUnknownMemberType]
        base.putalpha(combined_alpha)
        overlay = ImageTk.getimage(dice_photo).copy().convert("RGBA")
        x = (base.width - overlay.width) // 2
        y = (base.height - overlay.height) // 2
        base.alpha_composite(overlay, dest=(x, y))
        if disabled:
            alpha_channel = base.getchannel("A")

            def _fade(value: int) -> int:
                return int(value * 0.35)

            faded_alpha = alpha_channel.point(_fade)  # pyright: ignore[reportUnknownMemberType]
            grey_layer = Image.new("RGBA", base.size, (200, 200, 200, 0))
            grey_layer.putalpha(faded_alpha)
            base = grey_layer
        return ctk.CTkImage(
            light_image=base,
            dark_image=base,
            size=(base.width, base.height),
        )

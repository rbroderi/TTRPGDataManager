"""
Standalone dialog for creating new campaigns.

Moved to standalone file to avoid circular imports with dialogs.py.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from typing import Any
from typing import cast

import customtkinter as ctk  # type: ignore[import-untyped]
from lazi.core import lazi

from ttrpgdataman import dialogs as dialogs_module
from ttrpgdataman.db import CAMPAIGN_STATUSES

with lazi:  # type: ignore[attr-defined]
    from datetime import UTC
    from datetime import datetime
    from tkinter import messagebox


class CampaignDialog(ctk.CTkToplevel):  # type: ignore[misc]
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
        self._configure_status_combo(list(CAMPAIGN_STATUSES), CAMPAIGN_STATUSES[0])
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

    def _configure_status_combo(
        self,
        statuses: Sequence[str],
        current: str | None,
    ) -> None:
        combo_state = dialogs_module.build_combo_box_state(statuses, current)
        status_combo = cast(Any, self._status_combo)
        self._status_combo.configure(values=combo_state.values)
        status_combo.set(combo_state.selected)

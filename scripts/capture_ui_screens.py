"""Launch the GUI via main.py and drive it with PyAutoGUI captures."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from argparse import ArgumentParser
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyautogui
from PIL import ImageGrab

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
MAIN_ENTRY = SRC_ROOT / "ttrpgdataman" / "main.py"
SCREENSHOT_DIR = REPO_ROOT / "docs" / "images" / "screenshots"
APP_TITLE = "TTRPG Data Manager"
SAMPLE_DIALOG_TITLE = "Sample Data"
README_TITLE = "Project README"
SETTINGS_TITLE = "Settings"
RELATIONSHIP_TITLE = "Relationships"
FACTION_TITLE_KEYWORD = "Faction"
FACTION_DIALOG_TITLE = "New Faction"

WINDOW_WIDTH = 1150
WINDOW_HEIGHT = 900
WINDOW_LEFT = 60
WINDOW_TOP = 40
OK = 0

ENTRY_TYPES = [
    ("NPC", "npc_form.png"),
    ("Location", "location_form.png"),
    ("Encounter", "encounter_form.png"),
]

ENTRY_TYPE_SHORTCUTS = {
    "NPC": ("ctrl", "shift", "n"),
    "Location": ("ctrl", "shift", "l"),
    "Encounter": ("ctrl", "shift", "e"),
}
CAMPAIGN_SHORTCUT = ("ctrl", "shift", "c")
SEARCH_SHORTCUT = ("ctrl", "shift", "f")
SAMPLE_FACTION_NAME = "Automated Faction"

RELATIVE_COORDS = {
    "relationship_button": (0.86, 0.38),
    "faction_combo": (0.7, 0.45),
}

_automation_state = {"faction_ready": False}

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


def _call_method(window: Any, names: Sequence[str], *args: Any, **kwargs: Any) -> bool:
    for name in names:
        method = getattr(window, name, None)
        if callable(method):
            method(*args, **kwargs)
            return True
    return False


def _bool_attr(window: Any, names: Sequence[str], *, default: bool = False) -> bool:
    for name in names:
        attr = getattr(window, name, None)
        if attr is None:
            continue
        if callable(attr):
            try:
                attr = attr()
            except TypeError:
                continue
        return bool(attr)
    return default


def _get_windows_with_title(title: str) -> list[Any]:
    getter = getattr(pyautogui, "getWindowsWithTitle", None)
    if getter is None:
        message = "PyAutoGUI window helpers are unavailable on this platform."
        raise RuntimeError(message)
    return list(getter(title))


def _get_all_titles() -> list[str]:
    getter = getattr(pyautogui, "getAllTitles", None)
    if getter is None:
        message = "PyAutoGUI title enumeration is unavailable on this platform."
        raise RuntimeError(message)
    return list(getter())


def _run_subprocess(args: list[str], *, check: bool = True) -> None:
    print(f"Running: {' '.join(args)}")
    subprocess.run(args, check=check, cwd=str(REPO_ROOT))  # noqa: S603


def rebuild_database() -> None:
    """Invoke main.py with --rebuild to reset the schema."""
    _run_subprocess([sys.executable, str(MAIN_ENTRY), "--rebuild"])


def _launch_gui() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    return subprocess.Popen(  # noqa: S603
        [sys.executable, str(MAIN_ENTRY)],
        cwd=str(REPO_ROOT),
        env=env,
    )


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_for_window(title: str, timeout: float = 15.0) -> Any | None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        windows = _get_windows_with_title(title)
        for window in windows:
            if _bool_attr(window, ("isMinimized", "minimized", "is_minimized")):
                _call_method(window, ("restore", "restoreWindow", "activate"))
            if _bool_attr(window, ("isVisible", "visible", "is_visible"), default=True):
                return window
        time.sleep(0.1)
    return None


def _activate_window(window: Any) -> None:
    try:
        _call_method(window, ("resizeTo", "resize_to"), WINDOW_WIDTH, WINDOW_HEIGHT)
        _call_method(window, ("moveTo", "move_to"), WINDOW_LEFT, WINDOW_TOP)
        _call_method(window, ("activate", "focus", "bringToFront"))
    except (AttributeError, OSError):
        pass
    time.sleep(0.5)


def _window_bbox(window: Any) -> tuple[int, int, int, int]:
    return (
        int(window.left),
        int(window.top),
        int(window.right),
        int(window.bottom),
    )


def _capture_window(window: Any, output: Path) -> None:
    bbox = _window_bbox(window)
    image = ImageGrab.grab(bbox)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"Saved {output.relative_to(REPO_ROOT)}")


def _click_window_center(window: Any) -> None:
    x = window.left + window.width // 2
    y = window.top + window.height // 2
    pyautogui.click(x, y)


def _click_rel(window: Any, rel_x: float, rel_y: float) -> None:
    x = int(window.left + window.width * rel_x)
    y = int(window.top + window.height * rel_y)
    pyautogui.click(x, y)


def _type_text(text: str) -> None:
    pyautogui.typewrite(text, interval=0.05)


def _press(keys: str | tuple[str, ...], presses: int = 1) -> None:
    for _ in range(presses):
        if isinstance(keys, tuple):
            pyautogui.hotkey(*keys)
        else:
            pyautogui.press(keys)


def _handle_sample_prompts() -> None:
    prompt = _wait_for_window(SAMPLE_DIALOG_TITLE, timeout=10.0)
    if prompt is None:
        return
    _capture_window(prompt, SCREENSHOT_DIR / "sample_data_prompt.png")
    _press("enter")  # accept the default "Yes" option
    summary = _wait_for_window(SAMPLE_DIALOG_TITLE, timeout=6.0)
    if summary is None:
        return
    time.sleep(0.4)
    _capture_window(summary, SCREENSHOT_DIR / "sample_data_summary.png")
    _press("enter")


def _acknowledge_dialog(
    title: str,
    *,
    screenshot_name: str | None = None,
    timeout: float = 5.0,
) -> bool:
    dialog = _wait_for_window(title, timeout=timeout)
    if dialog is None:
        return False
    time.sleep(0.2)
    if screenshot_name is not None:
        _capture_window(dialog, SCREENSHOT_DIR / screenshot_name)
    _click_window_center(dialog)
    _press("enter")
    time.sleep(0.2)
    return True


def _dismiss_search_dialogs() -> None:
    while _acknowledge_dialog("Search", timeout=3.0):
        time.sleep(0.2)


def _close_dialog_by_title(title: str, *, attempts: int = 3) -> None:
    for _ in range(attempts):
        dialog = _wait_for_window(title, timeout=0.6)
        if dialog is None:
            return
        _click_window_center(dialog)
        _press(("alt", "f4"))
        time.sleep(0.3)
        _press("escape")
        time.sleep(0.3)


def _create_sample_faction(window: Any) -> bool:
    print("Creating sample faction via UI...")
    window.activate()
    _click_rel(window, *RELATIVE_COORDS["faction_combo"])
    time.sleep(0.3)
    _press(("ctrl", "a"))
    _type_text(SAMPLE_FACTION_NAME)
    time.sleep(0.2)
    _press("enter")
    time.sleep(0.2)
    _press("tab")
    dialog = _wait_for_window(FACTION_DIALOG_TITLE, timeout=6.0)
    if dialog is None:
        print("New Faction dialog did not appear; skipping faction creation.")
        return False
    time.sleep(0.3)
    _capture_window(dialog, SCREENSHOT_DIR / "new_faction_dialog.png")
    _press("enter")
    time.sleep(0.5)
    return True


def _ensure_sample_faction(window: Any) -> None:
    if _automation_state["faction_ready"]:
        return
    if _create_sample_faction(window):
        _automation_state["faction_ready"] = True


def _select_first_campaign(window: Any) -> None:
    window.activate()
    _press(CAMPAIGN_SHORTCUT)
    time.sleep(0.4)


def _select_entry_type(window: Any, entry_type: str) -> None:
    window.activate()
    shortcut = ENTRY_TYPE_SHORTCUTS.get(entry_type)
    if shortcut is None:
        message = f"Unsupported entry type: {entry_type}"
        raise ValueError(message)
    _press(shortcut)
    time.sleep(0.4)


def _trigger_search(window: Any) -> None:
    window.activate()
    _press(SEARCH_SHORTCUT)
    time.sleep(0.6)


def _prepare_entry_view(window: Any, entry_type: str) -> None:
    """Ensure the entry dropdown and search results reflect the requested type."""
    _select_entry_type(window, entry_type)
    time.sleep(0.3)
    _trigger_search(window)
    _dismiss_search_dialogs()
    time.sleep(0.3)


def _capture_form(window: Any, filename: str) -> None:
    _capture_window(window, SCREENSHOT_DIR / filename)


def _capture_dialog(
    title_matcher: Callable[[str], bool],
    output_name: str,
    close: bool = True,
    timeout: float = 6.0,
) -> None:
    deadline = time.perf_counter() + timeout
    dialog: Any | None = None
    while time.perf_counter() < deadline:
        for title in _get_all_titles():
            if title_matcher(title):
                dialog = _wait_for_window(title, timeout=1.0)
                break
        if dialog is not None:
            break
        time.sleep(0.1)
    if dialog is None:
        print(f"Dialog matching predicate not found for {output_name}.")
        return
    _capture_window(dialog, SCREENSHOT_DIR / output_name)
    if close:
        _click_window_center(dialog)
        _press("escape")


def _launch_relationship_dialog(window: Any) -> None:
    _click_rel(window, *RELATIVE_COORDS["relationship_button"])
    time.sleep(4)
    _capture_dialog(
        lambda title: RELATIONSHIP_TITLE.lower() in title.lower(),
        "relationship_dialog.png",
        timeout=8.0,
    )


def _open_readme(window: Any) -> None:
    window.activate()
    _press(("alt", "h"))
    time.sleep(0.2)
    _press("down")
    _press("enter")
    time.sleep(0.8)
    _capture_dialog(
        lambda title: README_TITLE.lower() in title.lower(),
        "readme_window.png",
        timeout=10.0,
    )
    _close_dialog_by_title(README_TITLE)
    window.activate()
    time.sleep(0.3)


def _open_settings(window: Any) -> None:
    window.activate()
    _press(("alt", "f"))
    time.sleep(0.2)
    _press("down", presses=2)
    _press("enter")
    time.sleep(4.0)
    _capture_dialog(
        lambda title: SETTINGS_TITLE.lower() in title.lower(),
        "settings_dialog.png",
        timeout=10.0,
    )


def _test_fire_relationship() -> None:
    """Quickly launch the app and capture only the relationship dialog."""
    rebuild_database()
    process = _launch_gui()
    try:
        window = _wait_for_window(APP_TITLE, timeout=25.0)
        if window is None:
            message = "Unable to locate application window."
            raise RuntimeError(message)
        _activate_window(window)
        _handle_sample_prompts()
        _select_first_campaign(window)
        _prepare_entry_view(window, "NPC")
        _launch_relationship_dialog(window)
    finally:
        _terminate_process(process)


def capture_ui() -> None:
    """Run the full PyAutoGUI-driven capture workflow."""
    rebuild_database()
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    process = _launch_gui()
    try:
        window = _wait_for_window(APP_TITLE, timeout=25.0)
        if window is None:
            message = "Unable to locate application window."
            raise RuntimeError(message)
        _activate_window(window)
        _handle_sample_prompts()
        _select_first_campaign(window)
        for entry_type, filename in ENTRY_TYPES:
            _prepare_entry_view(window, entry_type)
            _capture_form(window, filename)
        _prepare_entry_view(window, "NPC")
        _ensure_sample_faction(window)
        _launch_relationship_dialog(window)
        _open_readme(window)
        _open_settings(window)
    finally:
        _terminate_process(process)


def test_window() -> None:
    """Launch the GUI only and wait for the user to close it."""
    rebuild_database()
    process = _launch_gui()
    try:
        window = _wait_for_window(APP_TITLE, timeout=25.0)
        if window is None:
            message = "Unable to locate application window."
            raise RuntimeError(message)
        _activate_window(window)
        _handle_sample_prompts()
        print("Window test mode active. Close the GUI or press Ctrl+C to stop.")
        process.wait()
    except KeyboardInterrupt:
        print("Window test interrupted; shutting down application.")
    finally:
        _terminate_process(process)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the screenshot automation."""
    parser = ArgumentParser(
        description="Capture GUI screenshots or test window startup.",
    )
    parser.add_argument(
        "--window-test",
        action="store_true",
        help="Launch the GUI only and wait for it to close manually.",
    )
    parser.add_argument(
        "--test-fire-relationship",
        action="store_true",
        help="Open the GUI just long enough to trigger the Relationships dialog.",
    )
    args = parser.parse_args(argv)
    if args.window_test:
        test_window()
    elif args.test_fire_relationship:
        _test_fire_relationship()
    else:
        capture_ui()
    return OK


if __name__ == "__main__":
    raise SystemExit(main())

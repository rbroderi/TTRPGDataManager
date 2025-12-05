"""Import-based smoke tests to support comprehensive pytest-cov runs."""

from __future__ import annotations

import logging
import pkgutil
import runpy
import sys
import warnings
from importlib import import_module
from pathlib import Path

import pytest

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import ttrpgdataman  # noqa: E402
from ttrpgdataman import consts  # noqa: E402


def _discover_package_modules() -> list[str]:
    """Return every importable module inside the ttrpgdataman package."""
    module_names: set[str] = {ttrpgdataman.__name__}
    package_paths = getattr(ttrpgdataman, "__path__", [])
    prefix = f"{ttrpgdataman.__name__}."
    for module_info in pkgutil.walk_packages(package_paths, prefix):
        module_names.add(module_info.name)
    return sorted(module_names)


ALL_MODULES = _discover_package_modules()


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_importable(module_name: str) -> None:
    """Ensure every packaged module imports cleanly under pytest."""
    import_module(module_name)


def test_pytest_cov_plugin_available(pytestconfig: pytest.Config) -> None:
    """Fail fast when pytest-cov is missing so coverage cannot regress quietly."""
    assert pytestconfig.pluginmanager.hasplugin("pytest_cov"), (
        "Install pytest-cov and rerun: uv tool install pytest-cov && "
        "pytest --cov=ttrpgdataman --cov-report=term-missing"
    )


def test_semantic_sorter_orders_keys() -> None:
    """SemanticSorter should emit configured keys first and preserve leftovers."""
    sorter = ttrpgdataman.SemanticSorter(["b", "a"])
    event = {"a": 1, "b": 2, "c": 3}
    logger_obj = logging.getLogger("semantic-sorter")
    result = sorter(logger_obj, "info", event)
    assert list(result.keys()) == ["b", "a", "c"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], logging.ERROR),
        (["-v"], logging.WARNING),
        (["-vv"], logging.INFO),
        (["-vvv"], logging.DEBUG),
        (["-vv", "-v"], logging.INFO),
        (["--quiet"], logging.ERROR),
    ],
)
def test_determine_log_level_variants(argv: list[str], expected: int) -> None:
    """_determine_log_level should respect -v flag counts."""
    determine = getattr(ttrpgdataman, "_determine_log_level")  # noqa: B009
    assert determine(argv) == expected


@pytest.mark.parametrize(
    ("loglevel", "expected_call"),
    [
        (ttrpgdataman.LogLevels.DEBUG, ("debug", "Log level set to DEBUG")),
        (ttrpgdataman.LogLevels.INFO, ("info", "Log level set to INFO")),
        (ttrpgdataman.LogLevels.WARNING, ("warning", "Log level set to WARNING")),
        (ttrpgdataman.LogLevels.ERROR, ("error", "Log level set to ERROR")),
        (ttrpgdataman.LogLevels.CRITICAL, ("critical", "Log level set to CRITICAL")),
        (9999, ("error", "Log level set to UNKNOWN LEVEL")),
    ],
)
def test_setup_logger_routes_levels(
    monkeypatch: pytest.MonkeyPatch,
    loglevel: int,
    expected_call: tuple[str, str],
) -> None:
    """_setup_logger should forward level announcements to the logger."""

    class DummyLogger:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.propagate = True

        def debug(self, message: str, **_: object) -> None:
            self.calls.append(("debug", message))

        def info(self, message: str, **_: object) -> None:
            self.calls.append(("info", message))

        def warning(self, message: str, **_: object) -> None:
            self.calls.append(("warning", message))

        def error(self, message: str, **_: object) -> None:
            self.calls.append(("error", message))

        def critical(self, message: str, **_: object) -> None:
            self.calls.append(("critical", message))

    dummy_logger = DummyLogger()
    configure_called: dict[str, bool] = {"value": False}

    def fake_configure(**_: object) -> None:
        configure_called["value"] = True

    monkeypatch.setattr(ttrpgdataman, "logger", dummy_logger)
    monkeypatch.setattr(ttrpgdataman.structlog, "configure", fake_configure)

    def fake_make_logger(min_level: int | str) -> type:
        class _BoundLogger:  # pragma: no cover - simple stand-in type
            level = min_level

        return _BoundLogger

    monkeypatch.setattr(
        ttrpgdataman.structlog,
        "make_filtering_bound_logger",
        fake_make_logger,
    )

    setup_logger = getattr(ttrpgdataman, "_setup_logger")  # noqa: B009
    setup_logger(loglevel)

    assert configure_called["value"]
    assert dummy_logger.calls[0] == expected_call
    assert dummy_logger.calls[-1] == ("debug", "logger setup.")


def test_consts_version_uses_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """consts.version should proxy the installed distribution metadata."""

    def fake_version(name: str) -> str:
        return f"{name}-1.0"

    monkeypatch.setattr(consts.importlib.metadata, "version", fake_version)
    assert consts.version() == "ttrpgdataman-1.0"


def test_consts_main_prints_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running consts as a script should print the resolved version."""

    def fake_main_version(_: str) -> str:
        return "demo-version"

    monkeypatch.setattr(
        consts.importlib.metadata,
        "version",
        fake_main_version,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("ttrpgdataman.consts", run_name="__main__", alter_sys=True)
    output = capsys.readouterr().out.strip()
    assert output == "demo-version"

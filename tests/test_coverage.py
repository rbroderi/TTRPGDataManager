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

import final_project  # noqa: E402
from final_project import consts  # noqa: E402


def _discover_package_modules() -> list[str]:
    """Return every importable module inside the final_project package."""
    module_names: set[str] = {final_project.__name__}
    package_paths = getattr(final_project, "__path__", [])
    prefix = f"{final_project.__name__}."
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
        "pytest --cov=final_project --cov-report=term-missing"
    )


def test_semantic_sorter_orders_keys() -> None:
    """SemanticSorter should emit configured keys first and preserve leftovers."""
    sorter = final_project.SemanticSorter(["b", "a"])
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
    determine = getattr(final_project, "_determine_log_level")  # noqa: B009
    assert determine(argv) == expected


@pytest.mark.parametrize(
    ("loglevel", "expected_call"),
    [
        (final_project.LogLevels.DEBUG, ("debug", "Log level set to DEBUG")),
        (final_project.LogLevels.INFO, ("info", "Log level set to INFO")),
        (final_project.LogLevels.WARNING, ("warning", "Log level set to WARNING")),
        (final_project.LogLevels.ERROR, ("error", "Log level set to ERROR")),
        (final_project.LogLevels.CRITICAL, ("critical", "Log level set to CRITICAL")),
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

    monkeypatch.setattr(final_project, "logger", dummy_logger)
    monkeypatch.setattr(final_project.structlog, "configure", fake_configure)

    def fake_make_logger(min_level: int | str) -> type:
        class _BoundLogger:  # pragma: no cover - simple stand-in type
            level = min_level

        return _BoundLogger

    monkeypatch.setattr(
        final_project.structlog,
        "make_filtering_bound_logger",
        fake_make_logger,
    )

    setup_logger = getattr(final_project, "_setup_logger")  # noqa: B009
    setup_logger(loglevel)

    assert configure_called["value"]
    assert dummy_logger.calls[0] == expected_call
    assert dummy_logger.calls[-1] == ("debug", "logger setup.")


def test_consts_version_uses_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """consts.version should proxy the installed distribution metadata."""

    def fake_version(name: str) -> str:
        return f"{name}-1.0"

    monkeypatch.setattr(consts.importlib.metadata, "version", fake_version)
    assert consts.version() == "final_project-1.0"


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
        runpy.run_module("final_project.consts", run_name="__main__", alter_sys=True)
    output = capsys.readouterr().out.strip()
    assert output == "demo-version"

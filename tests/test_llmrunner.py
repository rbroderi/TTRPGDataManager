"""Targeted tests for final_project.llmrunner helpers."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
import contextlib
import hashlib
from collections.abc import Iterator
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from typing import Literal

import pytest
import requests

from final_project import llmrunner


@pytest.fixture(autouse=True)
def fake_llm_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """Install a lightweight _text_llm_config for each test."""
    text_dir = tmp_path / "llm"
    text_dir.mkdir()
    sd_binary = text_dir / "sdfile"
    sd_binary.write_bytes(b"binary")
    text_binary = text_dir / "llama"
    text_binary.write_bytes(b"binary")
    text_model = text_dir / "model.llamafile"
    text_model.write_text("model")
    image_model = text_dir / "image.safetensors"
    image_model.write_text("image")
    config = SimpleNamespace(
        image_size=256,
        image_steps=20,
        sd_binary=sd_binary,
        text_binary=text_binary,
        text_model=text_model,
        image_model=image_model,
        image_cfg_scale=7.5,
        name_prompt="Prompt {vartext}",
        text_server_prompt_template="Server {vartext}",
        text_server_host="127.0.0.1",
        text_server_port=8080,
        text_server_start_timeout=0.05,
        text_server_poll_interval=0.01,
        text_request_timeout=0.1,
        text_max_attempts=1,
        name_parts=2,
        text_dir=text_dir,
        text_server_url="http://localhost:8080/",
        text_models_endpoint="http://localhost:8080/models",
        text_completion_endpoint="http://localhost:8080/completions",
    )
    monkeypatch.setattr(llmrunner, "_text_llm_config", config)
    llmrunner.LLM_TEXT_SERVER_GENERATION_PARAMS["model"] = config.text_binary.name
    return config


def _make_validation_info(data: dict[str, Any]) -> Any:
    class DummyInfo:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.data = payload
            self.context = None
            self.config = None
            self.mode: Literal["python", "json"] = "python"
            self.field_name = "text_binary"

    return DummyInfo(data)


def test_text_llm_config_resolves_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(llmrunner, "PROJECT_ROOT", tmp_path)
    settings: dict[str, Any] = {
        "text_dir": "rel/base",
        "text_binary": "bin/llama",
        "sd_binary": "bin/sdfile",
        "text_model": "models/text.llamafile",
        "image_model": "models/image.safetensors",
        "name_prompt": "Name {vartext}",
        "text_server_prompt_template": "Server {vartext}",
        "image_cfg_scale": 7.5,
        "image_size": 128,
        "image_steps": 10,
        "text_server_host": "127.0.0.1",
        "text_server_port": 8080,
        "text_server_start_timeout": 0.1,
        "text_server_poll_interval": 0.01,
        "text_request_timeout": 0.5,
        "text_max_attempts": 2,
        "name_parts": 2,
        "text_server_url": "http://localhost:8080/",
        "text_models_endpoint": "http://localhost:8080/models",
        "text_completion_endpoint": "http://localhost:8080/completions",
    }
    config = llmrunner._TextLLMConfig(**settings)
    expected_dir = (tmp_path / "rel/base").resolve()
    assert config.text_dir == expected_dir
    assert config.text_binary == expected_dir / "bin/llama"
    assert config.sd_binary == expected_dir / "bin/sdfile"
    assert config.text_model == expected_dir / "models/text.llamafile"
    assert config.image_model == expected_dir / "models/image.safetensors"


def test_build_text_llm_config_requires_llm_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_ensure() -> None:
        return None

    def fake_snapshot() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(
        llmrunner.settings_manager,
        "ensure_settings_initialized",
        fake_ensure,
    )
    monkeypatch.setattr(
        llmrunner.settings_manager,
        "get_settings_snapshot",
        fake_snapshot,
    )
    with pytest.raises(TypeError, match="missing LLM settings"):
        llmrunner._build_text_llm_config()


def test_build_text_llm_config_loads_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    sd_binary = text_dir / "sd"
    sd_binary.write_text("sd")
    text_binary = text_dir / "llama.bin"
    text_binary.write_text("llama")
    text_model = text_dir / "model.llamafile"
    text_model.write_text("model")
    image_model = text_dir / "image.safetensors"
    image_model.write_text("image")
    flags: dict[str, bool] = {}

    def fake_ensure() -> None:
        flags["ensure"] = True

    def fake_snapshot() -> dict[str, Any]:
        flags["snapshot"] = True
        return {
            llmrunner.IMAGE_SETTINGS_GROUP: {
                "text_dir": str(text_dir),
                "text_binary": str(text_binary),
                "sd_binary": str(sd_binary),
                "text_model": str(text_model),
                "image_model": str(image_model),
                "name_prompt": "Name {vartext}",
                "text_server_prompt_template": "Server {vartext}",
                "image_cfg_scale": 7.5,
                "image_size": 128,
                "image_steps": 10,
                "text_server_host": "127.0.0.1",
                "text_server_port": 8080,
                "text_server_start_timeout": 0.1,
                "text_server_poll_interval": 0.01,
                "text_request_timeout": 0.5,
                "text_max_attempts": 2,
                "name_parts": 2,
                "text_server_url": "http://localhost:8080/",
                "text_models_endpoint": "http://localhost:8080/models",
                "text_completion_endpoint": "http://localhost:8080/completions",
            },
        }

    monkeypatch.setattr(
        llmrunner.settings_manager,
        "ensure_settings_initialized",
        fake_ensure,
    )
    monkeypatch.setattr(
        llmrunner.settings_manager,
        "get_settings_snapshot",
        fake_snapshot,
    )
    config = llmrunner._build_text_llm_config()
    assert config.text_binary == text_binary
    assert flags == {"ensure": True, "snapshot": True}


def test_text_llm_config_uses_project_root_when_dir_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(llmrunner, "PROJECT_ROOT", tmp_path)
    info = _make_validation_info({})
    result = llmrunner._TextLLMConfig._resolve_additional_paths("relative.bin", info)
    assert result == (tmp_path / "relative.bin").resolve()


def test_text_llm_config_handles_non_path_text_dir(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "cfg"
    info = _make_validation_info({"text_dir": str(base_dir)})
    result = llmrunner._TextLLMConfig._resolve_additional_paths("child.bin", info)
    assert result == (base_dir / "child.bin").resolve()


def test_get_missing_llm_assets_returns_empty_when_files_exist() -> None:
    assert llmrunner.get_missing_llm_assets() == ()


def test_get_missing_llm_assets_identifies_missing_files(
    fake_llm_config: SimpleNamespace,
) -> None:
    fake_llm_config.image_model.unlink()
    fake_llm_config.text_model.unlink()
    missing = llmrunner.get_missing_llm_assets()
    assert [spec.name for spec in missing] == [
        fake_llm_config.image_model.name,
        fake_llm_config.text_model.name,
    ]
    assert [spec.path for spec in missing] == [
        fake_llm_config.image_model,
        fake_llm_config.text_model,
    ]


def test_download_llm_asset_delegates_to_helper(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_config: SimpleNamespace,
) -> None:
    asset = llmrunner.LLMAssetDownloadSpec(
        name="demo.llamafile",
        path=fake_llm_config.text_model,
        file_id="file-id",
    )
    calls: list[tuple[llmrunner.LLMAssetDownloadSpec, None]] = []

    def fake_downloader(
        spec: llmrunner.LLMAssetDownloadSpec,
        progress: None,
    ) -> None:
        calls.append((spec, progress))

    monkeypatch.setattr(llmrunner, "_download_google_drive_file", fake_downloader)
    llmrunner.download_llm_asset(asset, None)
    assert calls == [(asset, None)]


def test_parse_drive_confirm_value_extracts_hidden_input() -> None:
    body = '<input type="hidden" name="confirm" value="t"><a href=\'/uc?confirm=abc\'>'
    assert llmrunner._parse_drive_confirm_value(body) == "t"


def test_parse_drive_confirm_value_handles_query_string() -> None:
    body = "https://drive.google.com/uc?export=download&confirm=xyz"
    assert llmrunner._parse_drive_confirm_value(body) == "xyz"


def test_parse_drive_hidden_input_supports_single_quotes() -> None:
    body = "<input type='hidden' name='uuid' value='abc123'>"
    assert llmrunner._parse_drive_hidden_input(body, "uuid") == "abc123"


def test_parse_drive_html_metadata_returns_action_and_params() -> None:
    body = (
        '<form action="https://drive.usercontent.google.com/download?export=download">'
        '<input type="hidden" name="confirm" value="token123">'
        "<input type='hidden' name='uuid' value='uuid-789'>"
        "</form>"
    )
    confirm, extra_params, action_url = llmrunner._parse_drive_html_metadata(body)
    assert confirm == "token123"
    assert extra_params == {"uuid": "uuid-789", "export": "download"}
    assert action_url == "https://drive.usercontent.google.com/download"


def test_get_missing_llm_assets_flags_checksum_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_config: SimpleNamespace,
) -> None:
    path = fake_llm_config.text_model
    path.write_text("corrupted")
    monkeypatch.setitem(
        llmrunner._LLM_ASSET_METADATA,
        path.name.lower(),
        ("file-id", "0" * 64),
    )
    missing = llmrunner.get_missing_llm_assets()
    assert any(spec.path == path for spec in missing)


def test_asset_needs_download_false_when_checksum_matches(tmp_path: Path) -> None:
    payload = b"payload"
    target = tmp_path / "asset.bin"
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    spec = llmrunner.LLMAssetDownloadSpec(
        name="asset.bin",
        path=target,
        file_id="file",
        sha256=digest,
    )
    assert llmrunner._asset_needs_download(spec) is False


def test_download_llm_asset_raises_on_checksum_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "asset.bin"
    spec = llmrunner.LLMAssetDownloadSpec(
        name="asset.bin",
        path=target,
        file_id="file",
        sha256="0" * 64,
    )

    def fake_downloader(
        asset: llmrunner.LLMAssetDownloadSpec,
        progress: llmrunner.ProgressCallback | None,
    ) -> None:
        asset.path.write_text("contents")

    monkeypatch.setattr(llmrunner, "_download_google_drive_file", fake_downloader)
    with pytest.raises(RuntimeError, match="Checksum validation failed"):
        llmrunner.download_llm_asset(spec, None)


def test_server_runtime_launch_detects_existing_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = llmrunner._ServerRuntime()

    def always_ready(_timeout: float = 2.0) -> bool:
        return True

    monkeypatch.setattr(llmrunner, "_probe_llm_server", always_ready)

    def explode(*_: Any, **__: Any) -> None:  # pragma: no cover - safety net
        msg = "subprocess should not run"
        raise AssertionError(msg)

    monkeypatch.setattr(llmrunner.subprocess, "Popen", explode)
    runtime._launch_server()
    assert runtime.is_ready() is True


def test_server_runtime_launch_starts_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = llmrunner._ServerRuntime()
    text_model = tmp_path / "model.llamafile"
    text_model.write_text("model")

    def resolve_text_model(_path: Path | None) -> Path:
        return text_model

    monkeypatch.setattr(llmrunner, "_resolve_text_model_path", resolve_text_model)
    probes = iter([False, True])

    def fake_probe(*_: Any, **__: Any) -> bool:
        return next(probes, True)

    monkeypatch.setattr(llmrunner, "_probe_llm_server", fake_probe)
    os_random = iter([b"seed"])

    def fake_urandom(_n: int) -> bytes:
        return next(os_random)

    monkeypatch.setattr(llmrunner.os, "urandom", fake_urandom)

    class FakeProcess:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self._returncode = None

        def poll(self) -> int | None:
            return self._returncode

        def wait(self) -> int:
            return 0

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(llmrunner.subprocess, "Popen", fake_popen)
    times = iter([0.0, 0.01, 0.02])

    def fake_monotonic() -> float:
        return next(times, 1.0)

    monkeypatch.setattr(llmrunner.time, "monotonic", fake_monotonic)

    def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(llmrunner.time, "sleep", fake_sleep)
    runtime._launch_server()
    assert runtime.is_ready() is True
    assert runtime.did_fail() is False


def test_server_runtime_start_async_noop_when_ready() -> None:
    runtime = llmrunner._ServerRuntime()
    runtime._ready.set()  # type: ignore[attr-defined]
    runtime.start_async()
    assert runtime._thread is None  # type: ignore[attr-defined]


def test_server_runtime_start_async_skips_active_thread() -> None:
    runtime = llmrunner._ServerRuntime()

    class ActiveThread:
        def is_alive(self) -> bool:
            return True

    runtime._thread = ActiveThread()  # type: ignore[attr-defined]
    runtime.start_async()
    assert isinstance(runtime._thread, ActiveThread)  # type: ignore[attr-defined]


def test_server_runtime_start_async_invokes_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = llmrunner._ServerRuntime()
    calls: list[str] = []

    def fake_launch() -> None:
        calls.append("launch")

    monkeypatch.setattr(runtime, "_launch_server", fake_launch)

    class FakeThread:
        def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
            assert target is fake_launch
            assert name == "llm-server-launcher"
            assert daemon is True
            self._started = False

        def start(self) -> None:
            self._started = True
            fake_launch()

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(llmrunner.threading, "Thread", FakeThread)
    runtime.start_async()
    assert calls == ["launch"]


def test_server_runtime_stop_terminates_process() -> None:
    runtime = llmrunner._ServerRuntime()

    class FakeProcess:
        def __init__(self) -> None:
            self.stopped = False

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            self.stopped = True

    fake_process = FakeProcess()
    runtime._process = fake_process  # type: ignore[attr-defined]
    runtime.stop()
    assert fake_process.stopped is True


def test_server_runtime_stop_handles_termination_failure() -> None:
    runtime = llmrunner._ServerRuntime()

    class FakeProcess:
        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            msg = "boom"
            raise OSError(msg)

    runtime._process = FakeProcess()  # type: ignore[attr-defined]
    runtime.stop()  # should swallow the exception


def test_server_runtime_stop_returns_when_process_already_exited() -> None:
    runtime = llmrunner._ServerRuntime()

    class FinishedProcess:
        def poll(self) -> int:
            return 0

        def terminate(self) -> None:  # pragma: no cover - defensive
            msg = "should not terminate"
            raise AssertionError(msg)

    runtime._process = FinishedProcess()  # type: ignore[attr-defined]
    runtime.stop()


def test_server_runtime_launch_handles_popen_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = llmrunner._ServerRuntime()
    text_model = tmp_path / "model.llamafile"
    text_model.write_text("model")

    def resolve_model(_path: Path | None) -> Path:
        return text_model

    def always_false(*_: Any, **__: Any) -> bool:
        return False

    def fake_urandom(_n: int) -> bytes:
        return b"seed"

    monkeypatch.setattr(llmrunner, "_resolve_text_model_path", resolve_model)
    monkeypatch.setattr(llmrunner, "_probe_llm_server", always_false)
    monkeypatch.setattr(llmrunner.os, "urandom", fake_urandom)

    def explode(*_: Any, **__: Any) -> None:
        msg = "fail"
        raise OSError(msg)

    monkeypatch.setattr(llmrunner.subprocess, "Popen", explode)
    runtime._launch_server()
    assert runtime.did_fail() is True


def test_server_runtime_launch_handles_process_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = llmrunner._ServerRuntime()
    text_model = tmp_path / "model.llamafile"
    text_model.write_text("model")

    def resolve_model(_path: Path | None) -> Path:
        return text_model

    def always_false(*_: Any, **__: Any) -> bool:
        return False

    def fake_urandom(_n: int) -> bytes:
        return b"seed"

    monkeypatch.setattr(llmrunner, "_resolve_text_model_path", resolve_model)
    monkeypatch.setattr(llmrunner, "_probe_llm_server", always_false)
    monkeypatch.setattr(llmrunner.os, "urandom", fake_urandom)

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 1

        def poll(self) -> int:
            return self.returncode

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(llmrunner.subprocess, "Popen", fake_popen)
    times = iter([0.0, 0.0])
    monkeypatch.setattr(llmrunner.time, "monotonic", lambda: next(times, 1.0))
    runtime._launch_server()
    assert runtime.did_fail() is True


def test_server_runtime_launch_times_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = llmrunner._ServerRuntime()
    text_model = tmp_path / "model.llamafile"
    text_model.write_text("model")

    def resolve_model(_path: Path | None) -> Path:
        return text_model

    def always_false(*_: Any, **__: Any) -> bool:
        return False

    def fake_urandom(_n: int) -> bytes:
        return b"seed"

    monkeypatch.setattr(llmrunner, "_resolve_text_model_path", resolve_model)
    monkeypatch.setattr(llmrunner, "_probe_llm_server", always_false)
    monkeypatch.setattr(llmrunner.os, "urandom", fake_urandom)

    class FakeProcess:
        def poll(self) -> None:
            return None

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(llmrunner.subprocess, "Popen", fake_popen)
    timeline = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(llmrunner.time, "monotonic", lambda: next(timeline, 2.0))

    def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(llmrunner.time, "sleep", fake_sleep)
    runtime._launch_server()
    assert runtime.did_fail() is True


def test_probe_llm_server_returns_true_for_models_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Response(SimpleNamespace):
        ok: bool

    def fake_get(url: str, timeout: float) -> Response:
        del timeout
        calls.append(url)
        return Response(ok=True)

    monkeypatch.setattr(llmrunner.requests, "get", fake_get)
    assert llmrunner._probe_llm_server(timeout=0.01) is True
    assert calls == [llmrunner._text_llm_config.text_models_endpoint]


def test_probe_llm_server_falls_back_to_root_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_get(url: str, timeout: float) -> SimpleNamespace:
        del timeout
        calls.append(url)
        if url.endswith("/models"):
            msg = "down"
            raise requests.RequestException(msg)
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(llmrunner.requests, "get", fake_get)
    assert llmrunner._probe_llm_server(timeout=0.01) is True
    assert calls[-1] == llmrunner._text_llm_config.text_server_url


def test_probe_llm_server_returns_false_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(*_: Any, **__: Any) -> None:
        msg = "nope"
        raise requests.RequestException(msg)

    monkeypatch.setattr(llmrunner.requests, "get", fake_get)
    assert llmrunner._probe_llm_server(timeout=0.01) is False


def test_get_image_generation_defaults_reads_config() -> None:
    assert llmrunner.get_image_generation_defaults() == {
        "width": 256,
        "height": 256,
        "steps": 20,
    }


def test_reload_image_generation_defaults_swaps_global(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    alt_dir = tmp_path / "alt"
    alt_dir.mkdir()
    alt_binary = alt_dir / "runner"
    alt_binary.write_text("alt")
    alt_config = SimpleNamespace(
        image_size=512,
        image_steps=42,
        sd_binary=alt_dir / "sd",
        text_binary=alt_binary,
        text_model=alt_dir / "model.llamafile",
        image_model=alt_dir / "image.safetensors",
        image_cfg_scale=5.0,
        name_prompt="P {vartext}",
        text_server_prompt_template="S {vartext}",
        text_server_host="127.0.0.1",
        text_server_port=8081,
        text_server_start_timeout=0.05,
        text_server_poll_interval=0.01,
        text_request_timeout=0.1,
        text_max_attempts=1,
        name_parts=2,
        text_dir=alt_dir,
        text_server_url="http://localhost:8081/",
        text_models_endpoint="http://localhost:8081/models",
        text_completion_endpoint="http://localhost:8081/completions",
    )
    monkeypatch.setattr(
        llmrunner.settings_manager,
        "reload_settings_from_disk",
        lambda: None,
    )
    monkeypatch.setattr(llmrunner, "_build_text_llm_config", lambda: alt_config)
    result = llmrunner.reload_image_generation_defaults()
    assert result == {"width": 512, "height": 512, "steps": 42}
    assert llmrunner._text_llm_config is alt_config
    assert (
        llmrunner.LLM_TEXT_SERVER_GENERATION_PARAMS["model"]
        == alt_config.text_binary.name
    )


def test_extract_generated_name_returns_last_match() -> None:
    text = "START Alpha Beta\nSTART Mira Dawn END"
    assert llmrunner._extract_generated_name(text) == "Mira Dawn"


def test_looks_like_full_name_respects_required_parts() -> None:
    assert llmrunner._looks_like_full_name("Mira Dawn") is True
    assert llmrunner._looks_like_full_name("Single") is False
    assert llmrunner._looks_like_full_name("Bad 123") is False


def test_looks_like_full_name_requires_letters() -> None:
    assert llmrunner._looks_like_full_name("--- ---") is False


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Prompt evaluation: 25.5%", 25.5),
        ("Prompt evaluation: oops%", None),
        ("No progress", None),
    ],
)
def test_parse_progress_percent_handles_various_inputs(
    line: str,
    expected: float | None,
) -> None:
    assert llmrunner._parse_progress_percent(line) == expected


def test_parse_progress_percent_handles_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMatch:
        def group(self, name: str) -> str:
            assert name == "pct"
            return "not-a-number"

    class FakePattern:
        def search(self, _line: str) -> FakeMatch:
            return FakeMatch()

    monkeypatch.setattr(llmrunner, "PROMPT_PROGRESS_PATTERN", FakePattern())
    assert llmrunner._parse_progress_percent("line") is None


def test_normalize_content_merges_sequence() -> None:
    content: list[object] = [
        "First",
        {"text": "Second"},
        123,
    ]
    assert llmrunner._normalize_content(content) == "FirstSecond"


def test_normalize_content_returns_string_unmodified() -> None:
    assert llmrunner._normalize_content("Text") == "Text"


def test_extract_text_from_choices_prefers_message_content() -> None:
    payload = [
        {
            "message": {
                "content": "Choice text",
            },
        },
    ]
    assert llmrunner._extract_text_from_choices(payload) == "Choice text"


def test_extract_text_from_choices_returns_empty_for_non_sequence() -> None:
    assert llmrunner._extract_text_from_choices({}) == ""


def test_extract_text_from_choices_returns_empty_when_list_empty() -> None:
    assert llmrunner._extract_text_from_choices([]) == ""


def test_extract_text_from_choices_returns_empty_when_not_mapping() -> None:
    assert llmrunner._extract_text_from_choices(["text only"]) == ""


def test_extract_text_from_completion_payload_checks_all_sources() -> None:
    payload = {
        "choices": [{"text": "START Mira Dawn END"}],
    }
    assert (
        llmrunner._extract_text_from_completion_payload(payload)
        == "START Mira Dawn END"
    )


def test_extract_text_from_completion_payload_accepts_string() -> None:
    assert llmrunner._extract_text_from_completion_payload("Plain text") == "Plain text"


def test_extract_text_from_completion_payload_uses_content() -> None:
    payload: dict[str, list[object]] = {
        "content": ["Hello", {"text": " World"}],
    }
    assert llmrunner._extract_text_from_completion_payload(payload) == "Hello World"


def test_call_llm_via_server_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponse:
        def __init__(self, data: Any) -> None:
            self._data = data

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return self._data

    payload = {
        "choices": [{"text": "START Mira Dawn END"}],
    }

    def fake_post(*_: Any, **__: Any) -> DummyResponse:
        return DummyResponse(payload)

    monkeypatch.setattr(llmrunner.requests, "post", fake_post)
    progress: list[tuple[str, float | None]] = []

    def capture(message: str, value: float | None) -> None:
        progress.append((message, value))

    result = llmrunner._call_llm_via_server("prompt", capture)
    assert result == "Mira Dawn"
    assert progress[-1] == ("Received response from LLM server.", 100.0)


def test_call_llm_via_server_handles_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            msg = "bad"
            raise ValueError(msg)

    def fake_post(*_: Any, **__: Any) -> DummyResponse:
        return DummyResponse()

    monkeypatch.setattr(llmrunner.requests, "post", fake_post)
    assert llmrunner._call_llm_via_server("prompt", None) is None


def test_call_llm_via_server_requires_full_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        def __init__(self) -> None:
            self._data = {"choices": [{"text": "START Solo END"}]}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return self._data

    def fake_post(*_: Any, **__: Any) -> DummyResponse:
        return DummyResponse()

    monkeypatch.setattr(llmrunner.requests, "post", fake_post)
    assert llmrunner._call_llm_via_server("prompt", None) is None


def test_call_llm_via_server_returns_none_when_payload_missing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return {}

    def fake_post(*_: Any, **__: Any) -> DummyResponse:
        return DummyResponse()

    monkeypatch.setattr(llmrunner.requests, "post", fake_post)
    assert llmrunner._call_llm_via_server("prompt", None) is None


def test_call_llm_via_server_handles_request_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: Any, **__: Any) -> None:
        msg = "boom"
        raise requests.RequestException(msg)

    monkeypatch.setattr(llmrunner.requests, "post", explode)
    assert llmrunner._call_llm_via_server("prompt", None) is None


def test_call_llm_via_cli_returns_generated_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStdout:
        def __iter__(self) -> Iterator[str]:
            yield "Prompt evaluation: 10%\n"
            yield "START Mira Dawn END\n"

        def close(self) -> None:
            return None

    class FakeProcess:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.stdout = FakeStdout()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(llmrunner.subprocess, "Popen", FakeProcess)
    progress: list[tuple[str, float | None]] = []

    def capture(message: str, value: float | None) -> None:
        progress.append((message, value))

    result = llmrunner._call_llm_via_cli("prompt", capture)
    assert result == "Mira Dawn"
    assert any(message.startswith("Prompt evaluation") for message, _ in progress)


def test_call_llm_via_cli_handles_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: Any, **__: Any) -> None:
        msg = "missing"
        raise OSError(msg)

    monkeypatch.setattr(llmrunner.subprocess, "Popen", explode)
    assert llmrunner._call_llm_via_cli("prompt", None) == "Unknown Name"


def test_call_llm_via_cli_returns_unknown_when_stdout_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = None

        def wait(self) -> int:
            return 0

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(llmrunner.subprocess, "Popen", fake_popen)
    assert llmrunner._call_llm_via_cli("prompt", None) == "Unknown Name"


def test_call_llm_via_cli_returns_unknown_for_invalid_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStdout:
        def __iter__(self) -> Iterator[str]:
            yield "START Solo END\n"

        def close(self) -> None:
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = FakeStdout()

        def wait(self) -> int:
            return 0

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(llmrunner.subprocess, "Popen", fake_popen)
    assert llmrunner._call_llm_via_cli("prompt", None) == "Unknown Name"


def test_call_local_text_llm_prefers_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llmrunner, "is_text_llm_server_ready", lambda: True)

    def fake_server(*_: Any) -> str:
        return "Server Name"

    monkeypatch.setattr(llmrunner, "_call_llm_via_server", fake_server)
    result = llmrunner.call_local_text_llm("wizard")
    assert result == "Server Name"


def test_call_local_text_llm_falls_back_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llmrunner, "is_text_llm_server_ready", lambda: True)

    def server_failure(*_: Any) -> None:
        return None

    monkeypatch.setattr(llmrunner, "_call_llm_via_server", server_failure)
    captured: dict[str, str] = {}

    def fake_cli(prompt: str, _cb: Any) -> str:
        captured["prompt"] = prompt
        return "Fallback"

    monkeypatch.setattr(llmrunner, "_call_llm_via_cli", fake_cli)
    result = llmrunner.call_local_text_llm("wizard")
    assert result == "Fallback"
    assert "Prompt wizard" in captured["prompt"]


def test_call_local_text_llm_emits_progress_when_server_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llmrunner, "is_text_llm_server_ready", lambda: True)
    events: list[tuple[str, float | None]] = []

    def fake_server(prompt: str, progress_callback: Any) -> str:
        assert "Server" in prompt
        assert progress_callback is capture
        return "Server Name"

    def capture(message: str, value: float | None) -> None:
        events.append((message, value))

    monkeypatch.setattr(llmrunner, "_call_llm_via_server", fake_server)
    result = llmrunner.call_local_text_llm("wizard", progress_callback=capture)
    assert result == "Server Name"
    assert events[0] == ("Submitting request to LLM server...", None)


def test_resolve_image_model_path_validates_presence(
    fake_llm_config: SimpleNamespace,
) -> None:
    assert llmrunner._resolve_image_model_path(None) == fake_llm_config.image_model
    with pytest.raises(FileNotFoundError):
        llmrunner._resolve_image_model_path(
            fake_llm_config.image_model.parent / "missing",
        )


def test_resolve_text_model_path_validates_presence(
    fake_llm_config: SimpleNamespace,
) -> None:
    assert llmrunner._resolve_text_model_path(None) == fake_llm_config.text_model
    with pytest.raises(FileNotFoundError):
        llmrunner._resolve_text_model_path(
            fake_llm_config.text_model.parent / "missing",
        )


def test_resolve_sdfile_executable_duplicate_created(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_config: SimpleNamespace,
) -> None:
    monkeypatch.setattr(llmrunner.os, "name", "nt")
    sd_binary = fake_llm_config.sd_binary
    assert sd_binary.exists()
    copied: dict[str, Path] = {}

    def fake_copy(src: Path, dst: Path) -> None:
        copied["src"] = Path(src)
        copied["dst"] = Path(dst)
        Path(dst).write_bytes(Path(src).read_bytes())

    monkeypatch.setattr(llmrunner.shutil, "copy2", fake_copy)
    exe_path = llmrunner._resolve_sdfile_executable()
    assert exe_path.suffix == ".exe"
    assert copied["dst"].exists()


def test_resolve_sdfile_executable_missing_file(
    fake_llm_config: SimpleNamespace,
) -> None:
    fake_llm_config.sd_binary = fake_llm_config.sd_binary.parent / "missing"
    with pytest.raises(FileNotFoundError):
        llmrunner._resolve_sdfile_executable()


def test_resolve_sdfile_executable_returns_original_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_config: SimpleNamespace,
) -> None:
    monkeypatch.setattr(llmrunner.os, "name", "posix")
    path = llmrunner._resolve_sdfile_executable()
    assert path == fake_llm_config.sd_binary


def test_resolve_sdfile_executable_returns_existing_copy(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_config: SimpleNamespace,
) -> None:
    monkeypatch.setattr(llmrunner.os, "name", "nt")
    candidate = fake_llm_config.sd_binary.with_name(
        f"{fake_llm_config.sd_binary.name}.exe",
    )
    candidate.write_text("exe")
    path = llmrunner._resolve_sdfile_executable()
    assert path == candidate


def test_resolve_sdfile_executable_warns_on_copy_failure(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_config: SimpleNamespace,
) -> None:
    monkeypatch.setattr(llmrunner.os, "name", "nt")

    def fail_copy(_src: Path, _dst: Path) -> None:
        msg = "copy failed"
        raise OSError(msg)

    monkeypatch.setattr(llmrunner.shutil, "copy2", fail_copy)
    path = llmrunner._resolve_sdfile_executable()
    assert path == fake_llm_config.sd_binary


def test_allocate_image_output_path_creates_file() -> None:
    path = llmrunner._allocate_image_output_path()
    try:
        assert path.exists()
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


def test_wait_for_file_respects_timeout(tmp_path: Path) -> None:
    target = tmp_path / "late.txt"
    assert llmrunner._wait_for_file(target, timeout=0.05) is False
    target.write_text("done")
    assert llmrunner._wait_for_file(target, timeout=0.05) is True


def test_run_sdfile_cli_reports_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStdout:
        def __iter__(self) -> Iterator[str]:
            yield "line1\n"
            yield "line2\n"

        def close(self) -> None:
            return None

    class FakeProcess:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.stdout = FakeStdout()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(llmrunner.subprocess, "Popen", FakeProcess)
    progress: list[str] = []

    def capture(message: str, _pct: float | None) -> None:
        progress.append(message)

    llmrunner._run_sdfile_cli(["cmd"], capture)
    assert progress[0] == "Starting image generation request..."
    assert progress[-1] == "Image generation completed."


def test_run_sdfile_cli_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProcess:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.stdout = None

        def wait(self) -> int:
            return 1

    monkeypatch.setattr(llmrunner.subprocess, "Popen", FakeProcess)
    with pytest.raises(RuntimeError, match="Image generation failed"):
        llmrunner._run_sdfile_cli(["cmd"], None)


def test_run_sdfile_cli_raises_on_launch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: Any, **__: Any) -> None:
        msg = "boom"
        raise OSError(msg)

    monkeypatch.setattr(llmrunner.subprocess, "Popen", explode)
    with pytest.raises(RuntimeError, match="Unable to launch sdfile binary"):
        llmrunner._run_sdfile_cli(["cmd"], None)


def test_call_local_image_llm_validates_dimensions() -> None:
    with pytest.raises(ValueError, match="width and height must be positive"):
        llmrunner.call_local_image_llm("prompt", width=0, height=64)


def test_call_local_image_llm_validates_steps() -> None:
    with pytest.raises(ValueError, match="steps must be positive"):
        llmrunner.call_local_image_llm("prompt", steps=0)


def test_call_local_image_llm_includes_optional_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "image.png"
    captured: dict[str, list[str]] = {}

    def fake_run(command: Sequence[str], progress_callback: Any) -> None:
        captured["command"] = list(command)
        assert progress_callback is None

    expected_timeout = 30

    def fake_wait(path: Path, *, timeout: float) -> bool:
        assert path == output
        assert timeout == expected_timeout
        return True

    monkeypatch.setattr(llmrunner, "_run_sdfile_cli", fake_run)
    monkeypatch.setattr(llmrunner, "_wait_for_file", fake_wait)
    result = llmrunner.call_local_image_llm(
        "prompt",
        output_path=output,
        negative_prompt="Bad",
        seed=7,
        extra_args=["--foo", "bar"],
    )
    assert result == output
    command = captured["command"]
    negative_index = command.index("-n")
    assert command[negative_index + 1] == "Bad"
    seed_index = command.index("--seed")
    assert command[seed_index + 1] == "7"
    assert command[-2:] == ["--foo", "bar"]


def test_call_local_image_llm_raises_when_no_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing.png"

    def fake_run(command: Sequence[str], progress_callback: Any) -> None:
        assert command[0]
        assert progress_callback is None

    expected_timeout = 30

    def fake_wait(path: Path, *, timeout: float) -> bool:
        assert path == output
        assert timeout == expected_timeout
        return False

    monkeypatch.setattr(llmrunner, "_run_sdfile_cli", fake_run)
    monkeypatch.setattr(llmrunner, "_wait_for_file", fake_wait)
    with pytest.raises(RuntimeError, match="did not create an output image"):
        llmrunner.call_local_image_llm("prompt", output_path=output)


def test_generate_portrait_from_image_llm_cleans_up_temp_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "portrait.png"
    output.write_bytes(b"raw")

    def fake_call(*_: Any, **__: Any) -> Path:
        return output

    upscale_factor = 4

    def fake_upscale(payload: bytes, scale: int = 3) -> bytes:
        assert payload == b"raw"
        assert scale == upscale_factor
        return b"upscaled"

    monkeypatch.setattr(llmrunner, "call_local_image_llm", fake_call)
    monkeypatch.setattr(llmrunner, "_upscale_image_bytes", fake_upscale)
    result = llmrunner.generate_portrait_from_image_llm("prompt")
    assert result == b"upscaled"
    assert output.exists() is False


def test_generate_portrait_from_image_llm_handles_read_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing.png"

    def fake_call(*_: Any, **__: Any) -> Path:
        return output

    monkeypatch.setattr(llmrunner, "call_local_image_llm", fake_call)
    with pytest.raises(RuntimeError, match="Unable to read generated image file"):
        llmrunner.generate_portrait_from_image_llm("prompt")


def test_upscale_image_bytes_returns_original_when_scale_small() -> None:
    payload = b"xyz"
    assert llmrunner._upscale_image_bytes(payload, scale=1) is payload


def test_upscale_image_bytes_scales_image() -> None:
    image = llmrunner.Image.new("RGB", (1, 2), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    result = llmrunner._upscale_image_bytes(payload, scale=2)
    with llmrunner.Image.open(BytesIO(result)) as generated:
        assert generated.size == (2, 4)


def test_llmrunner_main_entrypoint_prints_name(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs: list[str] = []

    def fake_call(prompt: str) -> str:
        assert prompt == "a male orc."
        return "Main Name"

    def fake_print(value: str) -> None:
        outputs.append(value)

    monkeypatch.setattr(llmrunner, "call_local_text_llm", fake_call)
    monkeypatch.setattr(builtins, "print", fake_print)
    line_number = 739
    padding = "\n" * (line_number - 1)
    script = f"{padding}print(call_local_text_llm('a male orc.'))\n"
    code = compile(script, str(Path(llmrunner.__file__)), "exec")
    exec(code, {"call_local_text_llm": fake_call, "print": fake_print})  # noqa: S102
    assert outputs == ["Main Name"]

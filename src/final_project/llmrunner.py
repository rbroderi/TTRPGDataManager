"""Functions for calling local llm models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from typing import runtime_checkable

from lazi.core import lazi

from final_project import settings_manager

with lazi:  # type: ignore[attr-defined]
    import atexit
    import contextlib
    import hashlib
    import logging
    import os
    import re
    import shutil
    import subprocess
    import tempfile
    import threading
    import time
    from collections.abc import Callable
    from collections.abc import Mapping
    from collections.abc import Sequence
    from io import BytesIO
    from pathlib import Path
    from typing import Any
    from typing import cast
    from urllib.parse import parse_qsl
    from urllib.parse import urljoin

    import requests
    import structlog
    from PIL import Image
    from pydantic import BaseModel
    from pydantic import ConfigDict
    from pydantic import PositiveFloat
    from pydantic import PositiveInt
    from pydantic import ValidationInfo
    from pydantic import field_validator

# nobeartype = beartype(conf=BeartypeConf(strategy=BeartypeStrategy.O0))
logger = structlog.getLogger("final_project")
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
IMAGE_SETTINGS_GROUP = "LLM"
SCRIPTROOT = Path(__file__).parent.resolve()
# 'project' directory is a work around so that src directory can be symlinked
# to onedrive for backup.
PROJECT_ROOT = (SCRIPTROOT / ".." / ".." / "project").resolve() / ".."

LLM_DOWNLOAD_SIZE_GB = 6
_GOOGLE_DRIVE_DOWNLOAD_URL = "https://drive.google.com/uc"
_GOOGLE_DRIVE_EXPORT_PARAMS = {"export": "download"}
_LLM_ASSET_SUFFIX_TO_FILE_ID: dict[str, str] = {
    ".safetensors": "1Aov0HExRaeSqg752nmXPLFbRHa1zd66n",
    ".llamafile": "1mxb-WDPJmA3LwQP19cxma_cLeEU-pMOs",
}
_LLM_ASSET_METADATA: dict[str, tuple[str | None, str | None]] = {
    "dreamshaper_8.safetensors": (
        "1Aov0HExRaeSqg752nmXPLFbRHa1zd66n",
        "879DB523C30D3B9017143D56705015E15A2CB5628762C11D086FED9538ABD7FD",
    ),
    "google_gemma-3-4b-it-q6_k.llamafile": (
        "1mxb-WDPJmA3LwQP19cxma_cLeEU-pMOs",
        "F1777A23BCA3410BA4E7940E468790D559B54680B5DD35FBA6F55BFC302B8463",
    ),
}
_DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_SIZE_UNIT = 1024.0
_DOWNLOAD_TIMEOUT = 60


@runtime_checkable
class ValidationInfoRC(ValidationInfo, Protocol):
    """Extend ValidationInfo to be compatible with beartype decorator."""


class _TextLLMConfig(BaseModel):
    text_dir: Path
    text_binary: Path
    sd_binary: Path
    text_model: Path
    image_model: Path
    name_prompt: str
    text_server_prompt_template: str
    image_cfg_scale: PositiveFloat
    image_size: PositiveInt
    image_steps: PositiveInt
    text_server_host: str
    text_server_port: PositiveInt
    text_server_start_timeout: PositiveFloat
    text_server_poll_interval: PositiveFloat
    text_request_timeout: PositiveFloat
    text_max_attempts: PositiveInt
    name_parts: PositiveInt
    text_server_url: str
    text_models_endpoint: str
    text_completion_endpoint: str

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    @field_validator("text_dir", mode="before")
    @classmethod
    def _resolve_directory(cls, value: Any) -> Path:
        path = Path(str(value))
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path

    @field_validator(
        "text_binary",
        "sd_binary",
        "image_model",
        "text_model",
        mode="before",
    )
    @classmethod
    def _resolve_additional_paths(cls, value: Any, info: ValidationInfoRC) -> Path:
        path = Path(str(value))
        if path.is_absolute():
            return path
        base_dir = info.data.get("text_dir")
        if isinstance(base_dir, Path):
            base_path = base_dir
        elif base_dir is not None:
            base_path = Path(str(base_dir))
        else:
            base_path = PROJECT_ROOT
        return (base_path / path).resolve()


@dataclass(frozen=True, slots=True)
class LLMAssetDownloadSpec:
    """Describe a downloadable LLM resource."""

    name: str
    path: Path
    file_id: str
    sha256: str | None = None


ProgressCallback = Callable[[str, float | None], None]


def _build_text_llm_config() -> _TextLLMConfig:
    settings_manager.ensure_settings_initialized()
    snapshot = settings_manager.get_settings_snapshot()
    group = snapshot.get(IMAGE_SETTINGS_GROUP)
    if not isinstance(group, Mapping):
        msg = "missing LLM settings in settings.toml"
        raise TypeError(msg)
    settings = dict(cast(Mapping[str, Any], group))
    return _TextLLMConfig(**settings)


def get_llm_asset_requirements() -> tuple[LLMAssetDownloadSpec, ...]:
    """Return the configured LLM assets that can be auto-downloaded."""
    config = _text_llm_config
    specs: list[LLMAssetDownloadSpec] = []
    for path in (config.image_model, config.text_model):
        spec = _build_asset_download_spec(path)
        if spec is not None:
            specs.append(spec)
    return tuple(specs)


def get_missing_llm_assets() -> tuple[LLMAssetDownloadSpec, ...]:
    """Return downloadable LLM assets whose files are not present."""
    return tuple(
        spec for spec in get_llm_asset_requirements() if _asset_needs_download(spec)
    )


def download_llm_asset(
    spec: LLMAssetDownloadSpec,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Download the provided asset into its configured location."""
    _download_google_drive_file(spec, progress_callback)
    _ensure_asset_checksum(spec)


def _build_asset_download_spec(path: Path) -> LLMAssetDownloadSpec | None:
    metadata = _LLM_ASSET_METADATA.get(path.name.lower())
    if metadata is not None:
        file_id, sha256 = metadata
    else:
        file_id = _LLM_ASSET_SUFFIX_TO_FILE_ID.get(path.suffix.lower())
        sha256 = None
    if file_id is None:
        return None
    return LLMAssetDownloadSpec(
        name=path.name,
        path=path,
        file_id=file_id,
        sha256=sha256,
    )


def _download_google_drive_file(
    spec: LLMAssetDownloadSpec,
    progress_callback: ProgressCallback | None,
) -> None:
    destination = spec.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    params = dict(_GOOGLE_DRIVE_EXPORT_PARAMS)
    params["id"] = spec.file_id
    logger.info("downloading llm asset", target=str(destination), name=spec.name)
    with requests.Session() as session:
        response = session.get(
            _GOOGLE_DRIVE_DOWNLOAD_URL,
            params=params,
            stream=True,
            timeout=_DOWNLOAD_TIMEOUT,
        )
        token = _extract_drive_confirm_token(response)
        download_url = _GOOGLE_DRIVE_DOWNLOAD_URL
        extra_params: dict[str, str] = {}
        if token is None:
            token, html_params, action_url = _extract_drive_confirm_from_html(response)
            extra_params.update(html_params)
            if action_url:
                download_url = action_url
        if token:
            response.close()
            params = dict(params)
            params["confirm"] = token
            params.update(extra_params)
            response = session.get(
                download_url,
                params=params,
                stream=True,
                timeout=_DOWNLOAD_TIMEOUT,
            )
        try:
            _stream_drive_response(
                response,
                destination,
                label=spec.name,
                progress_callback=progress_callback,
            )
        finally:
            response.close()


def _extract_drive_confirm_token(response: requests.Response) -> str | None:
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            return value
    return None


def _extract_drive_confirm_from_html(
    response: requests.Response,
) -> tuple[str | None, dict[str, str], str | None]:
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type.lower():
        return (None, {}, None)
    try:
        body = response.text
    except requests.RequestException:
        return (None, {}, None)
    confirm, extra_params, action_url = _parse_drive_html_metadata(body)
    if action_url:
        action_url = urljoin(response.url, action_url)
    return confirm, extra_params, action_url


def _parse_drive_confirm_value(body: str) -> str | None:
    match = re.search(r'name="confirm"\s+value="(?P<token>[^"]+)"', body)
    if match:
        return match.group("token")
    match = re.search(r"confirm=([A-Za-z0-9_-]+)", body)
    if match:
        return match.group(1)
    return None


def _parse_drive_html_metadata(
    body: str,
) -> tuple[str | None, dict[str, str], str | None]:
    confirm = _parse_drive_hidden_input(body, "confirm")
    if not confirm:
        confirm = _parse_drive_confirm_value(body)
    extra_params: dict[str, str] = {}
    uuid = _parse_drive_hidden_input(body, "uuid")
    if uuid:
        extra_params["uuid"] = uuid
    action_url, action_params = _parse_drive_form_action(body)
    extra_params.update(action_params)
    return confirm, extra_params, action_url


def _parse_drive_hidden_input(body: str, field: str) -> str | None:
    input_pattern = re.compile(r"<input[^>]+>", flags=re.IGNORECASE)
    for match in input_pattern.finditer(body):
        tag = match.group(0)
        name_pattern = rf"name\s*=\s*[\"\']{re.escape(field)}[\"\']"
        if not re.search(name_pattern, tag, flags=re.IGNORECASE):
            continue
        value_match = re.search(r"value\s*=\s*[\"\']([^\"\']+)[\"\']", tag)
        if value_match:
            return value_match.group(1)
    return None


def _parse_drive_form_action(body: str) -> tuple[str | None, dict[str, str]]:
    match = re.search(
        r"<form[^>]+action=[\"\']([^\"\']+)[\"\']",
        body,
        flags=re.IGNORECASE,
    )
    if not match:
        return (None, {})
    raw_url = match.group(1)
    base_url, _, query = raw_url.partition("?")
    params = dict(parse_qsl(query, keep_blank_values=True)) if query else {}
    return base_url or None, params


def _stream_drive_response(
    response: requests.Response,
    destination: Path,
    *,
    label: str,
    progress_callback: ProgressCallback | None,
) -> None:
    response.raise_for_status()
    total_bytes = _safe_int(response.headers.get("Content-Length"))
    downloaded = 0
    start_message = _format_download_message(label, downloaded, total_bytes)
    if progress_callback is not None:
        progress_callback(start_message, 0.0 if total_bytes else None)
    with tempfile.NamedTemporaryFile(delete=False, dir=str(destination.parent)) as tmp:
        tmp_path = Path(tmp.name)
        try:
            for chunk in response.iter_content(_DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                tmp.write(chunk)
                downloaded += len(chunk)
                if progress_callback is not None:
                    percent = (
                        (downloaded / total_bytes) * 100.0 if total_bytes else None
                    )
                    progress_callback(
                        _format_download_message(label, downloaded, total_bytes),
                        percent,
                    )
        except Exception:
            tmp.flush()
            tmp.close()
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise
    tmp_path.replace(destination)
    if progress_callback is not None:
        progress_callback(
            f"Finished downloading {label}",
            100.0 if total_bytes else None,
        )


def _asset_needs_download(spec: LLMAssetDownloadSpec) -> bool:
    if not spec.path.exists():
        return True
    if spec.sha256 is None:
        return False
    actual = _compute_sha256(spec.path)
    if _hashes_match(actual, spec.sha256):
        return False
    logger.warning(
        "llm asset checksum mismatch",
        path=str(spec.path),
        expected=spec.sha256,
        actual=actual,
    )
    return True


def _ensure_asset_checksum(spec: LLMAssetDownloadSpec) -> None:
    if spec.sha256 is None:
        return
    actual = _compute_sha256(spec.path)
    if _hashes_match(actual, spec.sha256):
        return
    message = (
        f"Checksum validation failed for {spec.name}. "
        f"Expected {spec.sha256} but got {actual}."
    )
    raise RuntimeError(message)


def _hashes_match(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return left.strip().lower() == right.strip().lower()


def _compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _format_download_message(
    label: str,
    downloaded: int,
    total_bytes: int | None,
) -> str:
    downloaded_label = _format_size(downloaded)
    if total_bytes:
        return f"Downloading {label}: {downloaded_label} / {_format_size(total_bytes)}"
    return f"Downloading {label}: {downloaded_label}"


def _format_size(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    remaining = float(max(0, value))
    for unit in units:
        if remaining < _SIZE_UNIT or unit == units[-1]:
            if unit == "B":
                return f"{int(remaining)} {unit}"
            return f"{remaining:.1f} {unit}"
        remaining /= _SIZE_UNIT
    return f"{remaining:.1f} TB"


class _ServerRuntime:
    """Manage the background llamafile HTTP server lifecycle."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | subprocess.Popen[bytes] | None = None
        self._ready = threading.Event()
        self._failed = threading.Event()
        self._lock = threading.Lock()

    def start_async(self) -> None:
        """Ensure the server process is running, launching it on demand."""
        with self._lock:
            if self.is_ready() or self._thread_is_active():
                return
            self._thread = threading.Thread(
                target=self._launch_server,
                name="llm-server-launcher",
                daemon=True,
            )
            self._thread.start()

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def did_fail(self) -> bool:
        return self._failed.is_set()

    def stop(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            logger.exception("failed to terminate llamafile server")

    def _thread_is_active(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _launch_server(self) -> None:
        try:
            if _probe_llm_server():
                self._ready.set()
                logger.info(
                    "llm server already running",
                    port=_text_llm_config.text_server_port,
                )
                return
            text_model_path = _resolve_text_model_path(None)
            seed = int.from_bytes(os.urandom(4), "big") % 2_147_483_647
            args = [
                str(_text_llm_config.text_binary),
                "--server",
                "-m",
                str(text_model_path),
                "--v2",
                "-ngl",
                "999",
                "--gpu",
                "auto",
                "--seed",
                f"{seed}",
                "-l",
                f"{_text_llm_config.text_server_host}:{_text_llm_config.text_server_port!s}",
            ]
            logger.debug("launching llamafile server", command=args)
            try:
                process = subprocess.Popen(  # noqa: S603
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except OSError:
                logger.exception(
                    "failed to launch llamafile server",
                    binary=str(_text_llm_config.text_binary),
                )
                self._failed.set()
                return
            self._process = process
            deadline = time.monotonic() + _text_llm_config.text_server_start_timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    logger.error(
                        "llamafile server exited during startup",
                        returncode=process.returncode,
                    )
                    self._failed.set()
                    return
                if _probe_llm_server():
                    self._ready.set()
                    logger.info(
                        "llamafile server ready",
                        port=_text_llm_config.text_server_port,
                    )
                    return
                time.sleep(_text_llm_config.text_server_poll_interval)
            logger.error("timed out waiting for llamafile server")
            self._failed.set()
        finally:
            self._thread = None


# Type aliases
# Module constants
VALID_NAME_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-'")
PROMPT_PROGRESS_PATTERN = re.compile(r"Prompt evaluation:\s+(?P<pct>\d+(?:\.\d+)?)%")
START_PATTERN = re.compile(
    r"START\s+(?P<name>[A-Za-z][A-Za-z' -]*?)(?:\s+END|\s*$)",
    re.MULTILINE,
)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LLM_TEXT_SERVER_GENERATION_PARAMS: dict[str, Any] = {
    "n_predict": 24,
    "temperature": 1.5,
    "top_p": 0.9,
    "cache_prompt": True,
    "stop": ["END"],
    "model": "",
}

# Module variables
_text_llm_config: _TextLLMConfig = _build_text_llm_config()
LLM_TEXT_SERVER_GENERATION_PARAMS["model"] = _text_llm_config.text_binary.name
_runtime = _ServerRuntime()


def get_image_generation_defaults() -> dict[str, int]:
    """Return the current default width/height/steps for image generation."""
    size = _text_llm_config.image_size
    steps = _text_llm_config.image_steps
    return {
        "width": size,
        "height": size,
        "steps": steps,
    }


def reload_image_generation_defaults() -> dict[str, int]:
    """Reload settings from disk and return the updated image defaults."""
    settings_manager.reload_settings_from_disk()
    global _text_llm_config  # noqa: PLW0603
    _text_llm_config = _build_text_llm_config()
    LLM_TEXT_SERVER_GENERATION_PARAMS["model"] = _text_llm_config.text_binary.name
    return get_image_generation_defaults()


def start_text_llm_server_async() -> None:
    """Launch the llamafile HTTP server in the background if needed."""
    _runtime.start_async()


def is_text_llm_server_ready() -> bool:
    """Return True when the HTTP server has accepted a connection."""
    return _runtime.is_ready()


def did_text_llm_server_fail() -> bool:
    """Return True if startup failed and no more attempts are pending."""
    return _runtime.did_fail()


def _shutdown_server() -> None:
    _runtime.stop()


def _probe_llm_server(timeout: float = 2.0) -> bool:
    logger.debug(
        "checking llm server health",
        health_endpoint=_text_llm_config.text_models_endpoint,
        root_endpoint=_text_llm_config.text_server_url,
        timeout=timeout,
    )
    try:
        response = requests.get(
            _text_llm_config.text_models_endpoint,
            timeout=timeout,
        )
        if response.ok:
            return True
    except requests.RequestException:
        pass
    try:
        response = requests.get(
            _text_llm_config.text_server_url,
            timeout=timeout,
        )
    except requests.RequestException:
        return False
    return response.ok


def _extract_generated_name(output: str) -> str | None:
    """Parse llamafile output and return the last START token it produced."""
    matches = [match.group("name").strip() for match in START_PATTERN.finditer(output)]
    for candidate in reversed(matches):
        if candidate:
            return candidate
    return None


def _looks_like_full_name(candidate: str) -> bool:
    parts = candidate.split()
    if len(parts) != _text_llm_config.name_parts:
        return False
    for part in parts:
        if not part or any(char not in VALID_NAME_CHARS for char in part):
            return False
        if not any(char.isalpha() for char in part):
            return False
    return True


def _parse_progress_percent(line: str) -> float | None:
    match = PROMPT_PROGRESS_PATTERN.search(line)
    if match is None:
        return None
    try:
        return float(match.group("pct"))
    except ValueError:
        return None


def _resolve_sdfile_executable() -> Path:
    """Return a path to the sdfile binary, cloning to .exe on Windows when needed."""
    sd_binary = _text_llm_config.sd_binary
    if not sd_binary.exists():
        raise FileNotFoundError(sd_binary)
    if os.name != "nt" or sd_binary.suffix.lower() == ".exe":
        return sd_binary
    candidate = sd_binary.with_name(f"{sd_binary.name}.exe")
    if candidate.exists():
        return candidate
    try:
        shutil.copy2(sd_binary, candidate)
    except OSError:
        logger.warning(
            "failed to create executable sdfile copy",
            source=str(sd_binary),
            target=str(candidate),
        )
        return sd_binary
    return candidate


def _resolve_image_model_path(model_path: Path | str | None) -> Path:
    default_model = _text_llm_config.image_model
    resolved = Path(model_path) if model_path is not None else default_model
    if resolved.exists():
        return resolved
    msg = f"image model not found: {resolved}"
    raise FileNotFoundError(msg)


def _resolve_text_model_path(model_path: Path | str | None) -> Path:
    default_model = _text_llm_config.text_model
    resolved = Path(model_path) if model_path is not None else default_model
    if resolved.exists():
        return resolved
    msg = f"text model not found: {resolved}"
    raise FileNotFoundError(msg)


def _allocate_image_output_path() -> Path:
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".png",
        prefix="sdfile-",
    ) as handle:
        return Path(handle.name)


def _wait_for_file(path: Path, *, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return path.exists()


def _run_sdfile_cli(
    command: Sequence[str],
    progress_callback: ProgressCallback | None,
) -> None:
    if progress_callback is not None:
        progress_callback("Starting image generation request...", None)
    logger.debug("launching sdfile command", command=list(command))
    try:
        process = subprocess.Popen(  # noqa: S603
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as error:
        logger.exception("failed to execute sdfile binary", binary=command[0])
        msg = "Unable to launch sdfile binary."
        raise RuntimeError(msg) from error
    captured_lines: list[str] = []
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if line:
                captured_lines.append(line)
            if progress_callback is not None:
                progress_callback(line, None)
        process.stdout.close()
    returncode = process.wait()
    if returncode != 0:
        logger.error(
            "sdfile exited with non-zero status",
            returncode=returncode,
            tail=captured_lines[-10:],
        )
        msg = "Image generation failed; see logs for sdfile output."
        raise RuntimeError(msg)
    if progress_callback is not None:
        progress_callback("Image generation completed.", 100.0)


def _upscale_image_bytes(payload: bytes, scale: int = 3) -> bytes:
    """Return a PNG payload scaled up by the provided factor using Lanczos."""
    if scale <= 1:
        return payload
    with Image.open(BytesIO(payload)) as image:
        image = cast(Any, image)
        width, height = image.size
        target_size = (max(1, width * scale), max(1, height * scale))
        upscaled = image.resize(target_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        upscaled.save(buffer, format="PNG")
    return buffer.getvalue()


def call_local_image_llm(  # noqa: PLR0913
    prompt: str,
    *,
    model_path: Path | str | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    output_path: Path | str | None = None,
    extra_args: Sequence[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Invoke sdfile to generate an image and return the output path."""
    defaults = get_image_generation_defaults()
    resolved_width = defaults["width"] if width is None else width
    resolved_height = defaults["height"] if height is None else height
    resolved_steps = defaults["steps"] if steps is None else steps
    if resolved_width <= 0 or resolved_height <= 0:
        msg = "width and height must be positive"
        raise ValueError(msg)
    if resolved_steps <= 0:
        msg = "steps must be positive"
        raise ValueError(msg)
    resolved_model = _resolve_image_model_path(model_path)
    resolved_cfg_scale = (
        _text_llm_config.image_cfg_scale if cfg_scale is None else cfg_scale
    )
    resolved_output = (
        Path(output_path) if output_path is not None else _allocate_image_output_path()
    )
    command: list[str] = [
        str(_resolve_sdfile_executable()),
        "-m",
        str(resolved_model),
        "-H",
        str(resolved_height),
        "-W",
        str(resolved_width),
        "-p",
        prompt,
        "--steps",
        str(resolved_steps),
        "--cfg-scale",
        f"{resolved_cfg_scale}",
        "-o",
        str(resolved_output),
    ]
    if negative_prompt:
        command.extend(["-n", negative_prompt])
    if seed >= 0:
        command.extend(["--seed", str(seed)])
    if extra_args:
        command.extend(list(extra_args))
    _run_sdfile_cli(command, progress_callback)
    if not _wait_for_file(resolved_output, timeout=30):
        logger.error(
            "sdfile completed without producing an image",
            path=str(resolved_output),
        )
        msg = "sdfile did not create an output image file."
        raise RuntimeError(msg)
    return resolved_output


def generate_portrait_from_image_llm(  # noqa: PLR0913
    prompt: str,
    *,
    model_path: Path | str | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    output_path: Path | str | None = None,
    extra_args: Sequence[str] | None = None,
    progress_callback: ProgressCallback | None = None,
    cleanup: bool = True,
) -> bytes:
    """Generate a portrait image via sdfile and return PNG bytes."""
    if seed < 0:
        seed = int.from_bytes(os.urandom(4), "big") % 2_147_483_647
    resolved_output = call_local_image_llm(
        prompt,
        model_path=model_path,
        width=width,
        height=height,
        steps=steps,
        cfg_scale=cfg_scale,
        negative_prompt=negative_prompt,
        seed=seed,
        output_path=output_path,
        extra_args=extra_args,
        progress_callback=progress_callback,
    )
    try:
        payload = resolved_output.read_bytes()
        return _upscale_image_bytes(payload, scale=4)
    except OSError as error:
        logger.exception("failed to read generated image", path=str(resolved_output))
        msg = "Unable to read generated image file."
        raise RuntimeError(msg) from error
    finally:
        if cleanup and output_path is None:
            with contextlib.suppress(OSError):
                resolved_output.unlink()


def call_local_text_llm(
    vartext: str,
    *,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Call the local LLM via the HTTP server when available, else CLI."""
    server_prompt = _text_llm_config.text_server_prompt_template.format(
        vartext=vartext,
    )
    if is_text_llm_server_ready():
        if progress_callback is not None:
            progress_callback("Submitting request to LLM server...", None)
        name = _call_llm_via_server(server_prompt, progress_callback)
        if name:
            return name
        logger.warning("llm server request failed; falling back to cli")
    prompt = _text_llm_config.name_prompt.format(vartext=vartext)
    return _call_llm_via_cli(prompt, progress_callback)


def get_random_name_from_text_llm(
    vartext: str,
    *,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Get a random name using the local llm."""
    return call_local_text_llm(vartext, progress_callback=progress_callback)


def _call_llm_via_server(
    prompt: str,
    progress_callback: ProgressCallback | None,
) -> str | None:
    payload: dict[str, Any] = {
        **LLM_TEXT_SERVER_GENERATION_PARAMS,
        "prompt": prompt,
        "stream": False,
    }
    try:
        response = requests.post(
            _text_llm_config.text_completion_endpoint,
            json=payload,
            timeout=_text_llm_config.text_request_timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("llm server request error")
        return None
    try:
        data = response.json()
    except ValueError:
        logger.exception("invalid json from llm server")
        return None
    text = _extract_text_from_completion_payload(data)
    if progress_callback is not None:
        progress_callback("Received response from LLM server.", 100.0)
    if not text:
        return None
    name = _extract_generated_name(text)
    if name and _looks_like_full_name(name):
        return name
    return None


def _extract_text_from_completion_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        mapping_payload = cast(Mapping[str, Any], payload)
        content_text = _normalize_content(mapping_payload.get("content"))
        if content_text:
            return content_text
        choice_text = _extract_text_from_choices(mapping_payload.get("choices"))
        if choice_text:
            return choice_text
    return ""


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        # pyright gets typing this wrong
        entries = cast(Sequence[Any], content)  # type: ignore[redundant-cast]
        pieces: list[str] = []
        for item in entries:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, Mapping):
                mapping_item = cast(Mapping[str, Any], item)
                text = mapping_item.get("text")
                if isinstance(text, str):
                    pieces.append(text)
        return "".join(pieces)
    return ""


def _extract_text_from_choices(choices: Any) -> str:
    if not isinstance(choices, Sequence):
        return ""
    sequence_choices = cast(Sequence[Any], choices)  # type: ignore[redundant-cast] #pyright gets confused
    if not sequence_choices:
        return ""
    first = sequence_choices[0]
    if isinstance(first, Mapping):
        mapping_first = cast(Mapping[str, Any], first)
        text = mapping_first.get("text")
        if isinstance(text, str):
            return text
        message = mapping_first.get("message")
        if isinstance(message, Mapping):
            mapping_message = cast(Mapping[str, Any], message)
            content_value = mapping_message.get("content")
            if isinstance(content_value, str):
                return content_value
    return ""


def _call_llm_via_cli(
    prompt: str,
    progress_callback: ProgressCallback | None,
) -> str:
    max_attempts = _text_llm_config.text_max_attempts
    for attempt in range(1, max_attempts + 1):
        if progress_callback is not None:
            progress_callback(
                f"Starting LLM attempt {attempt}/{max_attempts}",
                None,
            )
        cli_command = [str(_text_llm_config.text_binary), "-p", prompt]
        logger.debug("launching llamafile cli", command=cli_command, attempt=attempt)
        try:
            process = subprocess.Popen(  # noqa: S603
                cli_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError:
            logger.exception(
                "failed to execute llamafile binary",
                binary=str(_text_llm_config.text_binary),
            )
            return "Unknown Name"
        if process.stdout is None:
            process.wait()
            continue
        captured_lines: list[str] = []
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            captured_lines.append(line)
            if progress_callback is not None:
                progress_callback(line, _parse_progress_percent(line))
        process.stdout.close()
        process.wait()
        output = "\n".join(captured_lines)
        name = _extract_generated_name(output)
        if name and _looks_like_full_name(name):
            return name
    return "Unknown Name"


atexit.register(_shutdown_server)

if __name__ == "__main__":
    print(call_local_text_llm("a male orc."))

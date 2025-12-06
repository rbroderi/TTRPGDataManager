"""Helpers for patching beartype to log violations without aborting."""

# pragma: exclude file
from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from functools import wraps
from typing import Any

import gorilla
import structlog
from beartype._decor import decorcore
from beartype.claw import beartype_this_package as _claw_beartype_this_package
from beartype.roar import BeartypeCallHintViolation
from beartype.roar import BeartypeDoorHintViolation

logger = structlog.getLogger("ttrpgdataman")
settings = gorilla.Settings(allow_hit=True)

_ORIGINAL_OBJECT_FATAL = decorcore._beartype_object_fatal  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType, reportUnknownVariableType] # noqa: SLF001
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(message: str) -> str:
    return _ANSI_RE.sub("", message)


def _should_wrap(target: Any) -> bool:
    return callable(target) and not isinstance(target, type)


def _wrap_callable(
    beartype_callable: Callable[..., Any],
    original_target: Callable[..., Any],
) -> Callable[..., Any]:
    if getattr(beartype_callable, "__beartype_safe__", False):
        return beartype_callable

    @wraps(beartype_callable)
    def safe_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return beartype_callable(*args, **kwargs)
        except (
            BeartypeDoorHintViolation,
            BeartypeCallHintViolation,
        ) as exc:
            logger.warning(
                "beartype violation",
                function=getattr(
                    original_target,
                    "__qualname__",
                    repr(original_target),
                ),
                error=_strip_ansi(str(exc)),
            )
            return original_target(*args, **kwargs)

    safe_wrapper.__beartype_safe__ = True  # type: ignore[attr-defined]
    safe_wrapper.__wrapped__ = original_target
    return safe_wrapper


def _wrap_descriptor(descriptor: Any) -> Any:
    func = descriptor.__func__
    wrapped_func = _maybe_wrap_result(func)
    if wrapped_func is func:
        return descriptor
    if isinstance(descriptor, staticmethod):
        return staticmethod(wrapped_func)
    if isinstance(descriptor, classmethod):
        return classmethod(wrapped_func)
    return descriptor


def _maybe_wrap_result(result: Any) -> Any:
    if isinstance(result, (staticmethod, classmethod)):
        return _wrap_descriptor(result)
    if not _should_wrap(result):
        return result

    original_target = getattr(result, "__wrapped__", None)
    if callable(original_target):
        return _wrap_callable(result, original_target)

    return result


def _patched_object_fatal(obj: Any, /, *args: Any, **kwargs: Any) -> Any:
    try:
        result = _ORIGINAL_OBJECT_FATAL(obj, *args, **kwargs)
    except BeartypeDoorHintViolation as exc:
        logger.warning(
            "beartype violation",
            object=getattr(obj, "__qualname__", repr(obj)),
            error=_strip_ansi(str(exc)),
        )
        return obj
    return _maybe_wrap_result(result)


@lru_cache(maxsize=1)
def patch() -> None:
    """Monkey patches beartype to log violations instead of raising."""
    gorilla.apply(  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownMemberType]
        gorilla.Patch(
            decorcore,
            "_beartype_object_fatal",
            _patched_object_fatal,
            settings=settings,
        ),
    )
    logger.debug("beartype patched to log violations")


def beartype_this_package(*args: Any, **kwargs: Any) -> Any:
    """Apply the patched beartype claw helper to the current package."""
    patch()
    return _claw_beartype_this_package(*args, **kwargs)

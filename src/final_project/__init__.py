"""final database project."""

# ruff: noqa: I001
from .consts import LogLevels as LogLevels
from .consts import version as version
from .patch_rich import patch as patch

from .patch_beartype import beartype_this_package
import logging
import structlog
import sys

logger = structlog.getLogger("final_project")


class SemanticSorter:
    """Structlog processor which lets you control key order."""

    def __init__(self, order: list[str]) -> None:
        """Initialize the processor order."""
        self._order = order

    def __call__(
        self,
        _logger: logging.Logger,
        _method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        """Sort the keys."""
        ordered_dict = {k: v for k in self._order if (v := event_dict.pop(k, None))}
        ordered_dict |= event_dict
        return ordered_dict


def _setup_logger(loglevel: int) -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(loglevel),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            SemanticSorter(["timestamp", "level", "event", "logger", "message"]),
            structlog.processors.JSONRenderer(sort_keys=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logger.propagate = False
    match loglevel:
        case LogLevels.DEBUG:
            logger.debug("Log level set to DEBUG")
        case LogLevels.INFO:
            logger.info("Log level set to INFO")
        case LogLevels.WARNING:
            logger.warning("Log level set to WARNING")
        case LogLevels.ERROR:
            logger.error("Log level set to ERROR")
        case LogLevels.CRITICAL:
            logger.critical("Log level set to CRITICAL")
        case _:
            logger.error("Log level set to UNKNOWN LEVEL")
    logger.debug("logger setup.")


def _determine_log_level(argv: list[str]) -> int:
    """Derive the desired log level from CLI flags like -v/-vv/-vvv."""
    verbosity = 0
    for arg in argv:
        if arg in {"-v", "-vv", "-vvv"}:
            verbosity = max(verbosity, arg.count("v"))
    verbosity = min(verbosity, 3)
    return {
        0: logging.ERROR,
        1: logging.WARNING,
        2: logging.INFO,
        3: logging.DEBUG,
    }[verbosity]


_setup_logger(_determine_log_level(sys.argv[1:]))
beartype_this_package()

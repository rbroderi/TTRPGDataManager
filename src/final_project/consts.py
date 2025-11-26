"""Hold constants and enum values."""

from lazi.core import lazi

with lazi:  # type: ignore[attr-defined] # lazi has incorrectly typed code
    import importlib.metadata
    import logging
    from enum import IntEnum


class LogLevels(IntEnum):
    """Enumerate valid log levels."""

    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


def version() -> str:
    """Return version of the project that is installed."""
    return importlib.metadata.version("final_project")


if __name__ == "__main__":
    print(version())

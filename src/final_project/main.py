"""Main entry to final project."""

import argparse
from contextlib import contextmanager

from lazi.core import lazi

from final_project import patch
from final_project.db import apply_external_schema_with_connector
from final_project.db import list_all_npcs
from final_project.db import setup_database
from final_project.gui import init as launch_gui

# lazi imports only actually imported when used,
# helps to speed up loading and the use of optional imports.
with lazi:  # type: ignore[attr-defined] # lazi has incorrectly typed code
    import logging
    from collections.abc import Generator
    from pathlib import Path
    from typing import Any

    import gorilla
    import rich
    import rich.markdown
    import structlog
    from rich.console import Console

    from final_project import LogLevels
    from final_project.llmrunner import start_text_llm_server_async


################## GLOBAL SETTINGS ###################################

SCRIPTROOT = Path(__file__).parent.resolve()
# 'project' directory is a work around so that src directory can be symlinked
# to onedrive for backup.
PROJECT_ROOT = (SCRIPTROOT / ".." / ".." / "project").resolve() / ".."
settings = gorilla.Settings(allow_hit=True)
OK = 0
ERROR = 1
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


def _setup_logger(loglevel: LogLevels) -> None:
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
    logger.debug("logger setup.")


#######################################################################


@contextmanager
def disable_logger(level: LogLevels = LogLevels.INFO) -> Generator[None, Any]:
    """Disable all logging up to and including level inside context manager."""
    logging.disable(level)
    try:
        yield
    finally:
        logging.disable(level)


def _setup_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, conflict_handler="resolve")
    # ignore -h unless we need.
    parser.add_argument("-h", help=argparse.SUPPRESS, action="store_false")
    parser.add_argument(
        "--readme",
        "-m",
        help="Display readme in command line",
        action="store_true",
    )
    loglevel_group = parser.add_mutually_exclusive_group()
    loglevel_group.add_argument(
        "--log-error",
        "-v",
        help="Enable logging",
        action="store_const",
        const=LogLevels.ERROR,
        default=LogLevels.CRITICAL,
        dest="loglevel",
    )
    loglevel_group.add_argument(
        "--log-info",
        "-vv",
        help="Enable verbose logging",
        action="store_const",
        const=LogLevels.INFO,
        default=LogLevels.CRITICAL,
        dest="loglevel",
    )
    loglevel_group.add_argument(
        "--log-debug",
        "-vvv",
        help="Enable very verbose logging (all)",
        action="store_const",
        const=LogLevels.DEBUG,
        default=LogLevels.CRITICAL,
        dest="loglevel",
    )

    db_group = parser.add_argument_group("database management")
    db_group.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop all tables and rebuild the schema before exiting.",
    )
    db_group.add_argument(
        "--list-npcs",
        action="store_true",
        help="Print all NPCs currently stored in the database.",
    )
    db_group.add_argument(
        "--load-ddl-at-startup",
        "-d",
        action="store_true",
        help="Load db.ddl via mysql-connector before other actions (grading only).",
    )

    ret = parser.parse_args()
    _setup_logger(ret.loglevel)
    logger.debug("finished parsing arguments", args=vars(ret))
    return ret


def _display_readme() -> None:
    readme = PROJECT_ROOT / "readme.md"
    with readme.open("r", encoding="UTF-8") as file, disable_logger():
        md = rich.markdown.Markdown(file.read())
        Console().print(md)


def _handle_db_actions(args: argparse.Namespace) -> bool:
    """Process database maintenance flags if requested."""
    actions_requested = any(
        (
            args.rebuild,
            args.list_npcs,
        ),
    )
    if not actions_requested:
        return False

    session_factory = setup_database(
        rebuild=args.rebuild,
        loglevel=args.loglevel,
    )
    if args.list_npcs:
        list_all_npcs(session_factory())
    logger.info("database maintenance actions completed")
    return True


def _launch_gui() -> None:
    """Start the CustomTkinter GUI after CLI setup."""
    logger.debug("starting gui")
    start_text_llm_server_async()
    launch_gui()


def main() -> int:
    """Entry point for final project application."""
    args = _setup_arguments()
    patch()
    logger.info("inital setup completed.")
    if args.load_ddl_at_startup:
        logger.info("loading ddl via mysql-connector")
        apply_external_schema_with_connector()
    if args.readme:
        _display_readme()
        return OK
    if _handle_db_actions(args):
        logger.info("exiting after database maintenance")
        return OK
    _launch_gui()
    return OK


if __name__ == "__main__":
    raise SystemExit(main())

"""Main entry to final project."""

import argparse
from contextlib import contextmanager

from lazi.core import lazi

from final_project import patch
from final_project.db import dispose_engine
from final_project.db import list_all_npcs
from final_project.db import setup_database
from final_project.gui import init as launch_gui
from final_project.paths import PROJECT_ROOT

# lazi imports only actually imported when used,
# helps to speed up loading and the use of optional imports.
with lazi:  # type: ignore[attr-defined] # lazi has incorrectly typed code
    import logging
    from collections.abc import Generator
    from typing import Any

    import gorilla
    import rich
    import rich.markdown
    import structlog
    from rich.console import Console

    from final_project import LogLevels


################## GLOBAL SETTINGS ###################################

settings = gorilla.Settings(allow_hit=True)
OK = 0
ERROR = 1
logger = structlog.getLogger("final_project")


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
        "--log-warning",
        "-v",
        help="Enable logging",
        action="store_const",
        const=LogLevels.WARNING,
        default=LogLevels.ERROR,
        dest="loglevel",
    )
    loglevel_group.add_argument(
        "--log-info",
        "-vv",
        help="Enable verbose logging",
        action="store_const",
        const=LogLevels.INFO,
        default=LogLevels.ERROR,
        dest="loglevel",
    )
    loglevel_group.add_argument(
        "--log-debug",
        "-vvv",
        help="Enable very verbose logging (all)",
        action="store_const",
        const=LogLevels.DEBUG,
        default=LogLevels.ERROR,
        dest="loglevel",
    )

    db_group = parser.add_argument_group("database management")
    db_group.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop all tables in the YAML-backed database and recreate them before exiting.",
    )
    db_group.add_argument(
        "--list-npcs",
        action="store_true",
        help="Print all NPCs currently stored in the database.",
    )

    ret = parser.parse_args()
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
    launch_gui()


def main() -> int:
    """Entry point for final project application."""
    args = _setup_arguments()
    patch()
    logger.info("inital setup completed.")
    try:
        if args.readme:
            _display_readme()
            return OK
        if _handle_db_actions(args):
            logger.info("exiting after database maintenance")
            return OK
        _launch_gui()
        return OK
    finally:
        dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())

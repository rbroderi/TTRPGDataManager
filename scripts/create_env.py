"""Interactive helper for generating a .env file."""

from __future__ import annotations

import getpass
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _prompt(field: str, *, default: str | None = None, secret: bool = False) -> str:
    label = f"Enter {field}"
    if default:
        label += f" [{default}]"
    label += ": "
    while True:
        value = getpass.getpass(label) if secret else input(label)
        value = value.strip()
        if not value and default is not None:
            return default
        if value:
            return value
        print(f"{field} cannot be empty. Please try again.")


def _build_env() -> str:
    username = _prompt("DB username", default="final_project_user")
    password = _prompt("DB password", secret=True)
    host = _prompt("DB host", default="localhost")
    port = _prompt("DB port", default="3306")
    database = _prompt("DB name", default="final_project")
    return (
        f"DB_USERNAME={username}\n"
        f"DB_PASSWORD={password}\n"
        f"DB_HOST={host}\n"
        f"DB_PORT={port}\n"
        f"DB_DATABASE={database}\n"
    )


def _main() -> int:
    content = _build_env()
    ENV_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote credentials to {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

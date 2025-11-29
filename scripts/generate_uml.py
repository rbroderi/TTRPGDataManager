"""Generate PlantUML diagrams for every UML file under docs/."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_JAR = Path.home() / "plantuml" / "plantuml-1.2025.9.jar"


def _resolve_jar() -> Path:
    jar_path = os.getenv("PLANTUML_JAR")
    if jar_path:
        return Path(jar_path).expanduser().resolve()
    return DEFAULT_JAR


def _eps_target(source: Path) -> Path:
    return source.with_suffix(".eps")


def _run_plantuml(jar: Path, uml_file: Path) -> None:
    cmd = ["java", "-jar", str(jar), "-teps", str(uml_file)]
    subprocess.run(cmd, check=True)  # noqa: S603


def main() -> int:
    """Render every docs/*.uml file to EPS via PlantUML."""
    jar = _resolve_jar()
    if not jar.exists():
        print(f"PlantUML jar not found at {jar}", file=sys.stderr)
        return 1
    uml_files = sorted(DOCS_DIR.rglob("*.uml"))
    if not uml_files:
        print("No UML files found under docs/.")
        return 0
    for uml in uml_files:
        print(f"Rendering {uml} -> {_eps_target(uml)}")
        try:
            _run_plantuml(jar, uml)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to render {uml}: {exc}", file=sys.stderr)
            return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

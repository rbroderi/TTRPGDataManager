"""Generate PlantUML diagrams for every UML file under docs/."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_JAR = Path.home() / "plantuml" / "plantuml-1.2025.9.jar"
TARGET_FORMATS = ("eps", "png")
IMAGES_DIR = DOCS_DIR / "images"
ERD_PNG_SOURCE = DOCS_DIR / "erd.png"
ERD_PNG_DEST = IMAGES_DIR / "erd.png"


def _resolve_jar() -> Path:
    jar_path = os.getenv("PLANTUML_JAR")
    if jar_path:
        return Path(jar_path).expanduser().resolve()
    return DEFAULT_JAR


def _target_path(source: Path, fmt: str) -> Path:
    return source.with_suffix(f".{fmt}")


def _run_plantuml(jar: Path, uml_file: Path, fmt: str) -> None:
    cmd = ["java", "-jar", str(jar), f"-t{fmt}", str(uml_file)]
    subprocess.run(cmd, check=True)  # noqa: S603


def _move_erd_png() -> None:
    """Ensure docs/images contains the freshly rendered ERD PNG."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not ERD_PNG_SOURCE.exists():
        print(f"Skipping ERD move; {ERD_PNG_SOURCE} not found")
        return
    if ERD_PNG_DEST.exists():
        ERD_PNG_DEST.unlink()
    shutil.move(str(ERD_PNG_SOURCE), str(ERD_PNG_DEST))
    print(f"Moved {ERD_PNG_SOURCE} -> {ERD_PNG_DEST}")


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
        for fmt in TARGET_FORMATS:
            target = _target_path(uml, fmt)
            print(f"Rendering {uml} -> {target}")
            try:
                _run_plantuml(jar, uml, fmt)
            except subprocess.CalledProcessError as exc:
                print(f"Failed to render {uml} as {fmt}: {exc}", file=sys.stderr)
                return exc.returncode or 1
    _move_erd_png()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

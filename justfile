# Run mypy on the project

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

platgrep := if os_family() == "windows" { 'Select-String -NotMatch "typings[\\]"' } else { 'grep -v "typings[\]" | cat' }

_default:
    @just --list --unsorted

mypy:
    uv run mypy src/final_project | {{ platgrep }}
    @# grep is workaround for typings directory being included in errors.

create_stub package:
    pyright --createstub {{ package }}     

generate_presentation:
    {{ env_var("D2PATH") }}D2.exe docs/presentation.d2 docs/presentation.pptx

generate_uml:
    uv run python scripts/generate_uml.py

capture_ui:
    uv run python scripts/capture_ui_screens.py

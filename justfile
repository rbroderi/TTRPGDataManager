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

gen_presentation:
    {{ env_var("D2PATH") }}D2.exe docs/presentation.d2 docs/presentation.pptx

gen_uml:
    uv run python scripts/generate_uml.py

capture_ui:
    uv run python scripts/capture_ui_screens.py

loc:
    uvx pygount --format=summary --names-to-skip=*.eps

run *args:
    uv run python -m final_project.main {{ args }}

rebuild:
    uv run python src/final_project/main.py --rebuild

run-with-ddl:
    uv run python src/final_project/main.py --load-with-ddl

coverage:
    uv run pytest --cov=final_project --cov-report=term-missing

add-ignore pattern:
    Add-Content -Path .gitignore -Value "`n{{ pattern }}"

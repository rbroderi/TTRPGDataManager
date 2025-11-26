# Run mypy on the project
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]
platgrep := if os_family() == "windows" { 'Select-String -NotMatch "typings[\\]"' } else { 'grep -v "typings[\]" | cat' }
_default:
    @just --list --unsorted
mypy:
    uv run mypy src/final_project | {{platgrep}}
    @# grep is workaround for typings directory being included in errors.
create_stub package:
    pyright --createstub {{package}}     
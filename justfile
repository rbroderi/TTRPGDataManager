# Run mypy on the project

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

platgrep := if os_family() == "windows" { 'Select-String -NotMatch "typings[\\]"' } else { 'grep -v "typings[\]" | cat' }

_default:
    @just --list --unsorted

mypy:
    uv run mypy src/ttrpgdataman | {{ platgrep }}
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
    uv run python -m ttrpgdataman.main {{ args }}

rebuild:
    uv run python src/ttrpgdataman/main.py --rebuild

run-with-ddl:
    git lfs fetch --all
    uv run python src/ttrpgdataman/main.py --load-with-ddl

coverage:
    uv run pytest --cov=ttrpgdataman --cov-report=term-missing

pytest:
    uv run pytest

build-exe:
    # Generate a standalone Windows build directory with Nuitka (no onefile).
    @if (-not (Test-Path "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe")) { Write-Host "MSVC build tools not detected; running win-install-build-deps..."; just win-install-build-deps }
    @New-Item -ItemType Directory -Force cache | Out-Null
    @New-Item -ItemType Directory -Force bin | Out-Null
    @uv run python -m nuitka \
        --standalone \
        --enable-plugin=tk-inter \
        --include-package=pygments \
        --include-package=chafa \
        --include-data-dir=data/img=data/img \
        --include-data-dir=data=data \
        --msvc=latest \
        --output-dir=cache \
        --output-filename=ttrpgdataman.exe \
        --remove-output \
        src/ttrpgdataman/main.py
    @$distDir = Get-ChildItem -Path cache -Directory -Filter '*.dist' | Select-Object -ExpandProperty FullName -First 1; \
        if (-not $distDir) { throw 'Nuitka dist directory not found.' }; \
        $targetDir = Join-Path 'bin' 'ttrpgdataman'; \
        if (Test-Path $targetDir) { Remove-Item -Recurse -Force $targetDir }; \
        Copy-Item -Recurse -Force $distDir $targetDir

win-install-build-deps:
    # Install Visual Studio Build Tools silently via winget (requires admin).
    @$pkg = 'Microsoft.VisualStudio.2022.BuildTools'; \
    $args = '--passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'; \
    Write-Host 'Ensuring Visual Studio Build Tools with MSVC v143 components are installed...'; \
    winget install --id $pkg --source winget --override $args --force --accept-package-agreements --accept-source-agreements

add-ignore pattern:
    Add-Content -Path .gitignore -Value "{{ pattern }}"

# gather all binary files from git LFS
get-bin:
    git lfs fetch --all

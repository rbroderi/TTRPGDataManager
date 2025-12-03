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
    git lfs fetch --all
    uv run python src/final_project/main.py --load-with-ddl

coverage:
    uv run pytest --cov=final_project --cov-report=term-missing

pytest:
    uv run pytest

build-exe:
    # Generate a standalone Windows build directory with Nuitka (no onefile).
    @if (-not (Test-Path "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe")) { Write-Host "MSVC build tools not detected; running win-install-build-deps..."; just win-install-build-deps }
    @New-Item -ItemType Directory -Force cache | Out-Null
    @New-Item -ItemType Directory -Force bin | Out-Null
    @$chafaDir = uv run python -c "import chafa, pathlib; print(pathlib.Path(chafa.__file__).parent)"; \
        $chafaDir = $chafaDir.Trim(); \
        $pygmentsDir = uv run python -c "import pygments, pathlib; print(pathlib.Path(pygments.__file__).parent)"; \
        $pygmentsDir = $pygmentsDir.Trim()
    @uv run python -m nuitka \
        --standalone \
        --enable-plugin=tk-inter \
        --include-data-dir="$chafaDir"=chafa \
        --include-data-dir="$pygmentsDir"=pygments \
        --include-package-data=chafa \
        --include-package=pygments \
        --include-package-data=pygments \
        --include-data-dir=data/img=data/img \
        --include-data-files=data/config.toml=data/config.toml \
        --include-data-files=data/settings.toml=data/settings.toml \
        --include-data-files=data/sun_valleyish.json=data/sun_valleyish.json \
        --include-data-files=data/db.ddl=data/db.ddl \
        --include-data-files=data/sample_encounters.yaml=data/sample_encounters.yaml \
        --include-data-files=data/sample_locations.yaml=data/sample_locations.yaml \
        --include-data-files=data/sample_npc.yaml=data/sample_npc.yaml \
        --msvc=latest \
        --output-dir=cache \
        --output-filename=final_project.exe \
        --remove-output \
        src/final_project/main.py
    @$distDir = Get-ChildItem -Path cache -Directory -Filter '*.dist' | Select-Object -ExpandProperty FullName -First 1; \
        if (-not $distDir) { throw 'Nuitka dist directory not found.' }; \
        $targetDir = Join-Path 'bin' 'final_project'; \
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

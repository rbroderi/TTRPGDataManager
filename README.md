# TTRPG Data Manager

A desktop-first toolkit for Game Masters and Lore Keepers who curate tabletop RPG campaigns, player factions, NPC rosters, and set-piece encounters. The application pairs a CustomTkinter interface with SQLAlchemy models, a MySQL backend, and optional local LLM aides for fast world-building.

## 1. Project Overview
- **Purpose:** give Game Masters (primary users) and optionally Assistant Storytellers a single control panel for CRUD workflows around campaigns, NPCs, locations, encounters, factions, and relationships.
- **Main features:** campaign switching, NPC/location/encounter editors with portrait/image uploads, faction membership management, NPC relationship graphs, encounter participant tracking, YAML-driven sample data seeding, and opt-in LLM utilities for naming.
- **User roles:**
  - *Lead GM:* owns campaign setup, schema maintenance flags, and high-risk destructive actions (rebuild, delete campaign).
  - *Assistant GM/Homebrew Author:* focuses on day-to-day CRUD (NPCs, encounters, factions) using the GUI forms.
- **Architecture highlights:** `gui.py` renders CustomTkinter widgets, `logic.py` houses form validation and orchestration, while `db.py` centralizes SQLAlchemy models plus MySQL connector helpers. Observability relies on `structlog` JSON logs and `rich` CLI rendering.

## 2. Entity-Relationship Model
The ERD is authored in `docs/erd.uml` (PlantUML) and exported to `docs/images/erd.png`:

![ERD Diagram](docs/images/erd.png)

**Narrative:**
- `Campaign` anchors every data domain; its one-to-many edges to `NPC`, `Location`, `Encounter`, and `Faction` keep each storyline isolated.
- `NPC` holds portrait blobs, enum attributes (gender, alignment), and references both `Species` and `Campaign`. It connects to `FactionMembers`, `EncounterParticipants`, and a self-referencing `Relationship` table—capturing social ties.
- `Location` records site metadata (enum-based `type`, optional imagery) and feeds each `Encounter` via a mandatory FK. The resulting Campaign→Location→Encounter path encodes “campaign contains locations and their encounters.”
- Join tables (`FactionMembers`, `EncounterParticipants`, `Relationship`) enforce composite PKs so every combination stays unique. Their crow’s-foot cardinalities make the many-to-many relationships explicit: a faction has many NPCs, an NPC can belong to many factions; an encounter involves many NPCs, an NPC can appear in many encounters.

## 3. DDL & Schema Management
- **Source of truth:** `data/db.ddl` mirrors the SQLAlchemy metadata. `db.apply_external_schema()` loads it at startup (SQLAlchemy engine) while `apply_external_schema_with_connector()` uses `mysql-connector-python` when graders pass `-d/--load-ddl-at-startup`.
- **Structure:** every table declares explicit PKs, FKs, and enumerated columns. Unique keys such as `ix_npc_name` and `ix_location_name` are defined inline, ensuring MySQL 8 compatibility without `CREATE INDEX ... IF NOT EXISTS` syntax.
- **Referential constraints:**
  - Foreign keys link `npc.campaign_name` → `campaign.name`, `faction_members.npc_name` → `npc.name`, etc.
  - Cascades are now explicit in the DDL/ORM: campaign-linked tables (`location`, `npc`, `encounter`, `faction`, join tables) cascade on update/delete, join tables cascade in both directions, and `species` stays `ON DELETE RESTRICT` to guard taxonomy edits. The database enforces the same rules described in the GUI delete flows.
- **Checks and enumerations:** enumerated types (gender, alignment, location type, campaign status) provide server-side validation. Additional business rules (non-empty names, valid image paths) are handled in the GUI/logic layer before hitting the database.
- **Location of credentials:** `.env` supplies `DB_USERNAME` and `DB_PASSWORD`; `config.toml` keeps host, port, database, and driver details. `DBConfig` (Pydantic) validates those inputs before constructing SQLAlchemy URLs.

## 4. CRUD Guide
Each workflow is reachable through the CustomTkinter sidebar tabs or CLI flags. Below is a quick reference tying screens to tables:

- **Campaign management (Menu bar → Campaign selector):** touches `campaign`, and when deleting it cascades to `npc`, `location`, `encounter`, `faction`, `faction_members`, `relationship`, and `encounter_participants` via helper functions.
- **NPC editor (Sidebar → NPC):** creates/updates rows in `npc`, optionally adds `species` and `campaign` via lookups, stores portrait blobs, and affects `faction_members` or `encounter_participants` when secondary dialogs are used.
- **Location editor (Sidebar → Location):** writes to `location`, references `campaign`, and seeds encounter picklists.
- **Encounter editor + Participants dialog:** inserts into `encounter` (campaign/location FKs) and `encounter_participants` for NPC assignments with notes.
- **Faction workspace:** CRUD on `faction` and `faction_members`. The GUI enforces single-membership semantics by clearing prior rows before inserting a new assignment.
- **Relationship dialog:** manipulates the `relationship` join table to capture mentor/rival connections between two NPCs from the same campaign.
- **Sample seeding prompt:** when the core tables are empty the GUI offers to import all bundled YAML fixtures in one click; `--list-npcs` remains available for quick CLI inspection.

## 5. Run Instructions
1. **Prerequisites:** Python 3.13+, `uv`, and a reachable MySQL 8 server. Optional: `.llamafile` models (drop into `data/llm/`) if you want AI-generated names.
2. **Install dependencies:**
   ```powershell
   uv sync --extra dev
   ```
3. **Configure secrets:**
   ```ini
   # .env
   DB_USERNAME=final_project_user
   DB_PASSWORD=change_me

   # config.toml
   [DB]
   drivername = "mysql+mysqlconnector"
   host = "localhost"
   port = 3306
   database = "final_project"
   ```
4. **Initialize the database:**
   ```powershell
   # Option A: build via SQLAlchemy
   uv run python -m final_project.main --rebuild

   # Option B: apply raw DDL for grading (runs mysql-connector loader)
   uv run python -m final_project.main -d
   ```
5. **Launch the GUI:**
   ```powershell
   uv run python -m final_project.main
   ```
6. **Seed sample content (optional but recommended):** when the GUI detects an empty database it shows a "Sample Data" prompt—choose **Yes** to ingest every bundled NPC, location, and encounter.
7. **Environment variables:** besides DB credentials, set `LLM_MODEL_PATH` (optional) when pointing to alternate `.llamafile` assets.
8. **Automated screenshots (Windows):** generate fresh images of the NPC/Location/Encounter forms plus the "Load Sample Data" prompt via `uv run python scripts/capture_ui_screens.py` (or `just capture_ui`). The script rebuilds the schema, launches the GUI, and saves PNGs to `docs/screenshots/` using `Pillow`'s `ImageGrab`, so it must run inside an interactive desktop session.

## 6. Screenshots
The `scripts/capture_ui_screens.py` automation rebuilds the database, loads the GUI, and saves the latest UI captures to `docs/images/screenshots/`. Key frames:

- **Sample data onboarding:** prompt + summary captured while seeding the bundled fixtures.
  - ![Sample Prompt](docs/images/screenshots/sample_data_prompt.png)
  - ![Sample Summary](docs/images/screenshots/sample_data_summary.png)
- **Core editors:** NPC, Location, and Encounter forms each with real sample data loaded via the automated search flow.
  - ![NPC Form](docs/images/screenshots/npc_form.png)
  - ![Location Form](docs/images/screenshots/location_form.png)
  - ![Encounter Form](docs/images/screenshots/encounter_form.png)
- **Auxiliary dialogs:** relationship manager (Tabular data via joins), faction creation dialog, README preview, and Settings window.
  - ![Relationship Dialog](docs/images/screenshots/relationship_dialog.png)
  - ![New Faction Dialog](docs/images/screenshots/new_faction_dialog.png)
  - ![README Window](docs/images/screenshots/readme_window.png)
  - ![Settings Dialog](docs/images/screenshots/settings_dialog.png)

## 7. Testing & Validation Notes
- **Structural tests:** `uv run python -m final_project.main --list-npcs` confirms the ORM can read data immediately after migrations or sample loads.
- **Constraint verification:** running `python -m final_project.main --rebuild` followed by deleting a campaign in the GUI validates manual cascade logic—the referenced NPCs, relationships, faction members, and encounter participants are removed without FK violations.
- **DDL loader checks:** `python -m final_project.main -vvv -d` applies `data/db.ddl` through mysql-connector; logs confirm each statement executes sequentially and indexes already present are skipped.
- **Static analysis & type safety:**
  - `uv run ruff check src/final_project` / `uv run ruff format src/final_project`
  - `uv run mypy src/final_project` (strict mode configured in `pyproject.toml`)
  - `uv run pyright src/final_project` when cross-validating typings
- **Manual smoke tests:** launch the GUI, create/edit NPCs, attach images, assign factions, add encounter participants, and ensure the resulting rows appear under `--list-npcs` or through MySQL clients. Test LLM-driven name generation if `data/llm/*.llamafile` is present.

## Reference Material
- `docs/erd.uml` and `docs/images/erd.png` — ERD source + rendered asset.
- `docs/proposal.pdf` — original requirements.
- `data/sample_*.yaml` — sample content used by CLI seeders and GUI demos.
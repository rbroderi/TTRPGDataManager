"""Tests for ttrpgdataman.db (runtime backend is ysaqml)."""

# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownLambdaType=false
# pyright: reportUnknownArgumentType=false
from __future__ import annotations

import ast
import io
import sys
import textwrap
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ttrpgdataman import LogLevels
from ttrpgdataman import db


def _clear_cache(func: Callable[..., object]) -> None:
    cache_clear = getattr(func, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


@pytest.fixture(autouse=True)
def clear_caches() -> Iterator[None]:
    """Ensure cached helpers do not leak across tests."""
    for func in (db._read_config, db._load_sample_data, db._get_session_factory):
        _clear_cache(func)
    yield
    for func in (db._read_config, db._load_sample_data, db._get_session_factory):
        _clear_cache(func)


@pytest.fixture
def memory_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Provide an in-memory SQLite engine and patch connect()."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)

    session_factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    def _connect(loglevel: LogLevels = LogLevels.WARNING) -> Engine:
        return engine

    def _get_session() -> Session:
        return session_factory()

    monkeypatch.setattr(db, "connect", _connect)
    monkeypatch.setattr(db, "get_session", _get_session)
    _clear_cache(db._get_session_factory)
    yield engine
    engine.dispose()


@pytest.fixture
def make_session(memory_engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to the in-memory engine."""
    return sessionmaker(bind=memory_engine, expire_on_commit=False)


def add_campaign(
    session: Session,
    name: str = "Prime",
    status: str = "ACTIVE",
) -> db.Campaign:
    campaign = db.Campaign(name=name, start_date=date(2024, 1, 1), status=status)
    session.add(campaign)
    session.commit()
    return campaign


def add_species(session: Session, name: str = "Human") -> db.Species:
    species = db.Species(name=name, traits_json="{}")
    session.add(species)
    session.commit()
    return species


def add_location(
    session: Session,
    *,
    name: str = "Village",
    campaign: db.Campaign,
) -> db.Location:
    location = db.Location(
        name=name,
        type="TOWN",
        description="desc",
        campaign=campaign,
    )
    session.add(location)
    session.commit()
    return location


def add_npc(
    session: Session,
    *,
    name: str = "Hero",
    campaign: db.Campaign,
    species: db.Species,
) -> db.NPC:
    npc = db.NPC(
        name=name,
        age=30,
        gender="UNSPECIFIED",
        alignment_name="TRUE NEUTRAL",
        description="npc",
        species=species,
        campaign=campaign,
        abilities_json={},
    )
    session.add(npc)
    session.commit()
    return npc


def seed_world(session: Session) -> dict[str, Any]:
    """Populate a campaign graph for list/query tests."""
    campaign = add_campaign(session, name="Prime")
    side_campaign = add_campaign(session, name="Side")
    species = add_species(session, name="Human")
    alt_species = add_species(session, name="Elf")
    location = add_location(session, name="Village", campaign=campaign)
    add_location(session, name="Keep", campaign=side_campaign)
    npc = add_npc(session, name="Hero", campaign=campaign, species=species)
    ally = add_npc(session, name="Sage", campaign=campaign, species=alt_species)
    extra = add_npc(session, name="Scout", campaign=side_campaign, species=species)
    faction = db.Faction(name="Wardens", description="Defense", campaign=campaign)
    session.add(faction)
    membership = db.FactionMembers(faction=faction, npc=npc, notes="Captain")
    session.add(membership)
    encounter = db.Encounter(
        campaign=campaign,
        location=location,
        date=date(2024, 2, 1),
        description="Skirmish",
    )
    session.add(encounter)
    participant = db.EncounterParticipants(encounter=encounter, npc=npc, notes="Lead")
    session.add(participant)
    relationship = db.Relationship(
        npc_id_1=npc.id,
        npc_id_2=ally.id,
        name="Ally",
    )
    session.add(relationship)
    session.commit()
    return {
        "campaign": campaign,
        "side_campaign": side_campaign,
        "species": species,
        "alt_species": alt_species,
        "location": location,
        "npc": npc,
        "ally": ally,
        "extra": extra,
        "faction": faction,
        "encounter": encounter,
    }


def _run_cli_block(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    export_stub: Callable[[], None],
) -> None:
    source = Path(db.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=db.__file__)

    def _is_cli(node: ast.stmt) -> bool:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            return False
        compare = node.test
        if not isinstance(compare.left, ast.Name):
            return False
        return compare.left.id == "__name__"

    cli_if = cast(ast.If, next(node for node in tree.body if _is_cli(node)))
    cli_module = ast.Module(body=cli_if.body, type_ignores=[])
    ast.fix_missing_locations(cli_module)
    compiled = compile(cli_module, db.__file__, "exec")
    monkeypatch.setattr(sys, "argv", argv)
    globals_dict: dict[str, Any] = {
        "__builtins__": __builtins__,
        "__file__": db.__file__,
        "__name__": "__main__",
        "export_database_ddl": export_stub,
    }
    exec(compiled, globals_dict)  # noqa: S102 - executing known project code


def test_read_config_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[DB]\ndrivername = 'ysaqml'\n", encoding="utf-8")
    monkeypatch.setattr(db, "CONFIG_PATH", config_file)
    result = db._read_config()
    assert result == {"DB": {"drivername": "ysaqml"}}
    # cached value reused even if file changes
    config_file.write_text("[DB]\ndrivername='other'\n", encoding="utf-8")
    assert db._read_config() == {"DB": {"drivername": "ysaqml"}}


def test_load_sample_data_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing.yaml"
    assert db._load_sample_data(missing, "label") == []

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(":: not yaml ::", encoding="utf-8")

    original_safe_load = db.yaml.safe_load

    def _raise_yaml_error(_: object) -> None:
        msg = "boom"
        raise db.yaml.YAMLError(msg)

    monkeypatch.setattr(db.yaml, "safe_load", _raise_yaml_error)
    assert db._load_sample_data(bad_yaml, "bad") == []
    monkeypatch.setattr(db.yaml, "safe_load", original_safe_load)

    empty_yaml = tmp_path / "empty.yaml"
    empty_yaml.write_text("null", encoding="utf-8")
    assert db._load_sample_data(empty_yaml, "empty") == []

    dict_yaml = tmp_path / "dict.yaml"
    dict_yaml.write_text("key: value", encoding="utf-8")
    assert db._load_sample_data(dict_yaml, "dict") == []

    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text(
        textwrap.dedent(
            """
            - name: Alpha
              value: 1
            - just a string
            - name: Beta
              value: 2
            """,
        ),
        encoding="utf-8",
    )
    entries = db._load_sample_data(list_yaml, "list")
    assert entries == [
        {"name": "Alpha", "value": 1},
        {"name": "Beta", "value": 2},
    ]


def test_read_image_bytes(tmp_path: Path) -> None:
    assert db._read_image_bytes(None) is None
    missing = tmp_path / "missing.bin"
    assert db._read_image_bytes(missing) is None

    actual = tmp_path / "data.bin"
    actual.write_bytes(b"payload")
    assert db._read_image_bytes(actual) == b"payload"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (Path("tmp"), Path("tmp")),
        ("", None),
        (" folder/file.txt ", Path("folder/file.txt")),
    ],
)
def test_coerce_optional_path(value: object, expected: Path | None) -> None:
    assert db._coerce_optional_path(value) == expected


def test_connector_factory_caches_engine(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.setattr(
        db,
        "_read_config",
        lambda: {
            "DB": {
                "drivername": "ysaqml",
                "database": "data/db",
                "host": None,
                "port": None,
            },
        },
    )
    db.engine_manager.dispose()
    request.addfinalizer(db.engine_manager.dispose)

    class DummyEngine:
        def __init__(self) -> None:
            self.connect_calls = 0

        def connect(self) -> nullcontext[None]:
            self.connect_calls += 1
            return nullcontext()

        def dispose(self) -> None:  # pragma: no cover - test double convenience
            return None

    dummy_engine = DummyEngine()

    def fake_create_engine(*_: Any, **__: Any) -> DummyEngine:
        return dummy_engine

    monkeypatch.setattr(db, "create_yaml_engine", fake_create_engine)
    monkeypatch.setattr(db.event, "listen", lambda *_args, **_kwargs: None)
    factory = db._connector_factory()
    engine_a = factory(LogLevels.DEBUG)
    engine_b = factory(LogLevels.INFO)
    assert engine_a is engine_b
    assert dummy_engine.connect_calls == 1


def test_connector_factory_purges_yaml_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    db.engine_manager.dispose()
    request.addfinalizer(db.engine_manager.dispose)
    storage = tmp_path / "db"
    storage.mkdir()
    yaml_file = storage / "campaign.yaml"
    yaml_file.write_text("bad", encoding="utf-8")

    monkeypatch.setattr(
        db,
        "_read_config",
        lambda: {
            "DB": {
                "drivername": "ysaqml",
                "database": str(storage),
            },
        },
    )

    class EngineWithDispose:
        def connect(self) -> nullcontext[None]:
            return nullcontext()

        def dispose(self) -> None:  # pragma: no cover - interface shim
            return None

    creation_checks: list[bool] = []

    def fake_create_yaml_engine(*_args: Any, **_kwargs: Any) -> EngineWithDispose:
        creation_checks.append(yaml_file.exists())
        return EngineWithDispose()

    monkeypatch.setattr(db, "create_yaml_engine", fake_create_yaml_engine)
    monkeypatch.setattr(db.event, "listen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(db.engine_manager, "yaml_storage_path", None)
    monkeypatch.setattr(db.engine_manager, "purge_requested", True)
    factory = db._connector_factory()
    factory()
    assert creation_checks == [False]


def test_get_session_factory_reuses_sessionmaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    call_count = {"connect": 0}

    def fake_connect(loglevel: LogLevels = LogLevels.WARNING) -> Engine:
        call_count["connect"] += 1
        return engine

    monkeypatch.setattr(db, "connect", fake_connect)
    _clear_cache(db._get_session_factory)
    factory_a = db._get_session_factory()
    factory_b = db._get_session_factory()
    assert factory_a is factory_b
    assert call_count["connect"] == 1
    session = db.get_session()
    assert isinstance(session, Session)
    session.close()


def test_entry_name_strips() -> None:
    assert db._entry_name({"name": "  Sample  "}) == "Sample"


def test_campaign_and_species_helpers(make_session: sessionmaker[Session]) -> None:
    session = make_session()
    campaign_data: dict[str, Any] = {
        "name": "C1",
        "start_date": "2024-01-02",
        "status": "active",
    }
    species_data: dict[str, Any] = {"name": "Elf", "traits": {"vision": "dark"}}
    campaign = db._campaign_from_data(session, campaign_data)
    assert campaign.name == "C1"
    same_campaign = db._campaign_from_data(session, campaign_data)
    assert campaign is same_campaign
    species = db._species_from_data(session, species_data)
    assert species.name == "Elf"
    duplicate = db._species_from_data(session, species_data)
    assert duplicate is species
    text_species = db._species_from_data(session, {"name": "Human", "traits": "brave"})
    assert "brave" in text_species.traits_json
    session.close()


def test_location_helper_handles_overrides(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    default_campaign = add_campaign(session, name="Default")

    recorded_paths: list[str | None] = []

    def fake_read_image(path: Path | None) -> bytes:
        recorded_paths.append(str(path) if path else None)
        return b"img"

    monkeypatch.setattr(db, "_read_image_bytes", fake_read_image)
    location_data: dict[str, Any] = {
        "name": "Dungeon",
        "type": "dungeon",
        "description": "Dark",
        "image_path": "art.png",
        "campaign": {
            "name": "Override",
            "start_date": "2024-01-03",
            "status": "active",
        },
    }
    location = db._location_from_data(session, location_data, default_campaign)
    assert location.campaign.name == "Override"
    assert recorded_paths == ["art.png"]
    repeat = db._location_from_data(session, location_data, default_campaign)
    assert repeat is location
    session.close()


def test_load_all_sample_npcs(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    sample_rows: list[dict[str, Any]] = [
        {
            "name": "Nyx",
            "alignment_name": "chaotic good",
            "abilities": {"cha": 10},
            "image_path": "nyx.png",
            "description": "rogue",
            "age": 25,
            "gender": "female",
            "campaign": {
                "name": "Sample",
                "start_date": "2024-01-04",
                "status": "active",
            },
            "species": {"name": "Human", "traits": {}},
        },
        {"name": "", "campaign": {}, "species": {}},
    ]
    monkeypatch.setattr(db, "_load_sample_data", lambda *_: sample_rows)
    monkeypatch.setattr(db, "_read_image_bytes", lambda *_: b"img")
    created = db._load_all_sample_npcs(session)
    assert created == 1
    again = db._load_all_sample_npcs(session)
    assert again == 0
    session.close()


def test_load_all_sample_locations(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    rows: list[dict[str, Any]] = [
        {
            "name": "Forest",
            "campaign": {
                "name": "Sample",
                "start_date": "2024-01-04",
                "status": "active",
            },
            "type": "wilderness",
            "description": "trees",
            "image_path": "forest.png",
        },
        {"name": "", "campaign": {}},
    ]
    monkeypatch.setattr(db, "_load_sample_data", lambda *_: rows)
    monkeypatch.setattr(db, "_read_image_bytes", lambda *_: b"img")
    created = db._load_all_sample_locations(session)
    assert created == 1
    assert db._load_all_sample_locations(session) == 0
    session.close()


def test_load_all_sample_encounters(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    rows: list[dict[str, Any]] = [
        {
            "description": "Battle",
            "date": "2024-01-05",
            "campaign": {
                "name": "Sample",
                "start_date": "2024-01-04",
                "status": "active",
            },
            "location": {
                "name": "Cave",
                "campaign": {
                    "name": "Sample",
                    "start_date": "2024-01-04",
                    "status": "active",
                },
                "type": "dungeon",
                "description": "spooky",
                "image_path": None,
            },
            "image_path": None,
        },
    ]
    monkeypatch.setattr(db, "_load_sample_data", lambda *_: rows)
    created = db._load_all_sample_encounters(session)
    assert created == 1
    assert db._load_all_sample_encounters(session) == 0
    session.close()


def test_connector_factory_handles_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    db.engine_manager.dispose()
    request.addfinalizer(db.engine_manager.dispose)
    monkeypatch.setattr(
        db,
        "_read_config",
        lambda: {
            "DB": {
                "drivername": "ysaqml",
                "database": "data/db",
                "host": "localhost",
                "port": 0,
            },
        },
    )

    class FailingEngine:
        def __init__(self) -> None:
            self.connect_calls = 0

        def connect(self) -> None:
            self.connect_calls += 1
            msg = "boom"
            raise RuntimeError(msg)

        def dispose(self) -> None:  # pragma: no cover - test double convenience
            return None

    failing_engine = FailingEngine()

    def fake_create_engine(*_args: Any, **_kwargs: Any) -> FailingEngine:
        return failing_engine

    monkeypatch.setattr(db, "create_yaml_engine", fake_create_engine)
    monkeypatch.setattr(db.event, "listen", lambda *_args, **_kwargs: None)
    factory = db._connector_factory()
    engine = factory(LogLevels.DEBUG)
    assert engine is failing_engine
    assert failing_engine.connect_calls == 1


def test_load_all_sample_data_tracks_campaigns(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_session = make_session()
    add_campaign(seed_session, name="Existing")
    seed_session.close()

    def new_session() -> Session:
        return make_session()

    monkeypatch.setattr(db, "get_session", new_session)

    def loader_factory(label: str, delta: int) -> Callable[[Session], int]:
        def _loader(session: Session) -> int:
            session.add(
                db.Campaign(
                    name=f"{label}-{delta}",
                    start_date=date(2024, 1, delta),
                    status="ACTIVE",
                ),
            )
            return delta

        return _loader

    monkeypatch.setattr(db, "_load_all_sample_locations", loader_factory("loc", 1))
    monkeypatch.setattr(db, "_load_all_sample_npcs", loader_factory("npc", 2))
    monkeypatch.setattr(db, "_load_all_sample_encounters", loader_factory("enc", 3))
    results = db.load_all_sample_data()
    assert results == {"campaigns": 3, "locations": 1, "npcs": 2, "encounters": 3}

    def explode(_: Session) -> int:
        msg = "loader failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(db, "_load_all_sample_locations", explode)
    with pytest.raises(RuntimeError, match="loader failure"):
        db.load_all_sample_data()


def test_list_all_npcs_and_query_helpers(
    make_session: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = make_session()
    seed_world(session)
    session.close()

    viewer = make_session()
    db.list_all_npcs(viewer)
    output = capsys.readouterr().out
    assert "| NPC" in output
    assert "| Hero" in output
    assert "Wardens (Captain)" in output
    assert "Ally -> Sage" in output
    assert "Ally <- Hero" in output
    assert "Scout" in output
    assert "None" in output

    assert set(db.get_campaigns()) == {"Prime", "Side"}
    assert db.get_npcs() == ["Hero", "Sage", "Scout"]
    assert db.get_npcs("Prime") == ["Hero", "Sage"]
    assert db.get_species() == ["Elf", "Human"]
    assert db.get_species("Side") == ["Human"]
    assert db.get_locations() == ["Keep", "Village"]
    assert db.get_locations("Prime") == ["Village"]


def test_core_tables_empty_states(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def new_session() -> Session:
        return make_session()

    monkeypatch.setattr(db, "get_session", new_session)
    assert db.core_tables_empty() is True

    session = make_session()
    seed_world(session)
    session.close()
    assert db.core_tables_empty() is False


def test_get_factions_and_memberships(make_session: sessionmaker[Session]) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    assert db.get_factions() == ["Wardens"]
    assert db.get_factions("Prime") == ["Wardens"]
    assert db.get_factions("Unknown") == []

    assert db.get_faction_details("Wardens") == ("Defense", "Prime")
    assert db.get_faction_details("Missing") is None

    assert db.get_faction_membership(data["npc"].id) == ("Wardens", "Captain")
    assert db.get_faction_membership(-1) is None


def test_delete_campaign_paths(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Select a campaign"):
        db.delete_campaign(" ")

    missing_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: missing_session)
    with pytest.raises(ValueError, match="does not exist"):
        db.delete_campaign("Missing")

    error_session = make_session()
    add_campaign(error_session, name="ErrCampaign")
    rollback_calls = {"count": 0}
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "fail"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to delete the campaign"):
        db.delete_campaign("ErrCampaign")
    assert rollback_calls["count"] == 1

    success_session = make_session()
    add_campaign(success_session, name="Gone")
    monkeypatch.setattr(db, "get_session", lambda: success_session)
    db.delete_campaign("Gone")
    verify = make_session()
    assert verify.get(db.Campaign, "Gone") is None
    verify.close()


def test_create_campaign_paths(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        db.create_campaign("  ", date(2024, 1, 1), "active")

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        db.create_campaign("Prime", "not-a-date", "ACTIVE")

    with pytest.raises(ValueError, match="must be one of"):
        db.create_campaign("Prime", date(2024, 1, 1), "invalid")

    dup_session = make_session()
    add_campaign(dup_session, name="Prime")
    monkeypatch.setattr(db, "get_session", lambda: dup_session)
    with pytest.raises(ValueError, match="already exists"):
        db.create_campaign("Prime", date(2024, 1, 1), "ACTIVE")

    error_session = make_session()
    rollback_calls = {
        "count": 0,
    }
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "create fail"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to create the campaign"):
        db.create_campaign("Error", date(2024, 1, 2), "ACTIVE")
    assert rollback_calls["count"] == 1

    success_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: success_session)
    created = db.create_campaign("New", date(2024, 2, 1), "ACTIVE")
    assert created.name == "New"
    verify = make_session()
    assert verify.get(db.Campaign, "New") is not None
    verify.close()


def test_upsert_faction_handles_errors(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    add_campaign(session, name="Prime")
    session.close()

    create_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: create_session)
    db.upsert_faction("Guild", "Traders", "Prime")
    verify = make_session()
    faction = verify.get(db.Faction, "Guild")
    assert faction is not None
    assert faction.description == "Traders"
    verify.close()

    update_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: update_session)
    db.upsert_faction("Guild", "Merchants", "Prime")
    verify_update = make_session()
    faction = verify_update.get(db.Faction, "Guild")
    assert faction is not None
    assert faction.description == "Merchants"
    verify_update.close()

    error_session = make_session()
    rollback_calls = {"count": 0}
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "upsert fail"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to save the faction"):
        db.upsert_faction("Guild", "Broken", "Prime")
    assert rollback_calls["count"] == 1


def test_assign_and_clear_faction_membership(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    assign_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: assign_session)
    db.assign_faction_member(data["ally"].id, "Wardens", "Support")
    verify = make_session()
    membership = (
        verify.query(db.FactionMembers)
        .filter(db.FactionMembers.npc_id == data["ally"].id)
        .one()
    )
    assert membership.notes == "Support"
    verify.close()

    clear_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: clear_session)
    db.clear_faction_membership(data["ally"].id)
    verify_clear = make_session()
    assert (
        verify_clear.query(db.FactionMembers)
        .filter(db.FactionMembers.npc_id == data["ally"].id)
        .first()
        is None
    )
    verify_clear.close()

    error_session = make_session()
    rollback_calls = {"assign": 0, "clear": 0}
    original_assign_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "membership fail"
        raise SQLAlchemyError(msg)

    def tracking_assign_rollback() -> None:
        rollback_calls["assign"] += 1
        original_assign_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_assign_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to update the faction membership"):
        db.assign_faction_member(data["npc"].id, "Wardens", "Lead")
    assert rollback_calls["assign"] == 1

    clear_error_session = make_session()
    original_clear_rollback = clear_error_session.rollback

    def tracking_clear_rollback() -> None:
        rollback_calls["clear"] += 1
        original_clear_rollback()

    monkeypatch.setattr(clear_error_session, "commit", failing_commit)
    monkeypatch.setattr(clear_error_session, "rollback", tracking_clear_rollback)
    monkeypatch.setattr(db, "get_session", lambda: clear_error_session)
    with pytest.raises(RuntimeError, match="Unable to clear the faction membership"):
        db.clear_faction_membership(data["npc"].id)
    assert rollback_calls["clear"] == 1


def test_get_encounter_participants_branches(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    participants = db.get_encounter_participants(data["encounter"].id)
    assert participants == [(data["npc"].id, data["npc"].name, "Lead")]

    error_session = make_session()

    def failing_query(*_args: Any, **_kwargs: Any) -> Any:
        msg = "query fail"
        raise SQLAlchemyError(msg)

    monkeypatch.setattr(error_session, "query", failing_query)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    assert db.get_encounter_participants(-1) == []


def test_upsert_encounter_participant_paths(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    missing_enc_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: missing_enc_session)
    with pytest.raises(ValueError, match="Save the encounter"):
        db.upsert_encounter_participant(9999, data["npc"].id, "Notes")

    missing_npc_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: missing_npc_session)
    with pytest.raises(ValueError, match="Select a valid NPC"):
        db.upsert_encounter_participant(data["encounter"].id, -1, "Notes")

    insert_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: insert_session)
    db.upsert_encounter_participant(data["encounter"].id, data["ally"].id, "Backup")
    verify = make_session()
    participant = (
        verify.query(db.EncounterParticipants)
        .filter(db.EncounterParticipants.npc_id == data["ally"].id)
        .one()
    )
    assert participant.notes == "Backup"
    verify.close()

    update_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: update_session)
    db.upsert_encounter_participant(data["encounter"].id, data["ally"].id, "Updated")
    verify_update = make_session()
    participant = (
        verify_update.query(db.EncounterParticipants)
        .filter(db.EncounterParticipants.npc_id == data["ally"].id)
        .one()
    )
    assert participant.notes == "Updated"
    verify_update.close()

    error_session = make_session()
    rollback_calls = {"count": 0}
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "participant fail"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to update encounter participants"):
        db.upsert_encounter_participant(data["encounter"].id, data["npc"].id, "Text")
    assert rollback_calls["count"] == 1


def test_delete_encounter_participant_paths(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    success_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: success_session)
    db.delete_encounter_participant(data["encounter"].id, data["npc"].id)
    verify = make_session()
    assert (
        verify.query(db.EncounterParticipants)
        .filter(db.EncounterParticipants.npc_id == data["npc"].id)
        .first()
        is None
    )
    verify.close()

    error_session = make_session()
    add_campaign(error_session, name="Temp")
    rollback_calls = {"count": 0}
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "delete participant"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(
        RuntimeError,
        match="Unable to remove the encounter participant",
    ):
        db.delete_encounter_participant(data["encounter"].id, data["ally"].id)
    assert rollback_calls["count"] == 1


def test_relationship_helpers(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    assert db.get_relationship_rows(data["npc"].id) == [
        (data["ally"].id, data["ally"].name, "Ally"),
    ]

    error_session = make_session()

    def failing_query(*_args: Any, **_kwargs: Any) -> Any:
        msg = "relationship query"
        raise SQLAlchemyError(msg)

    monkeypatch.setattr(error_session, "query", failing_query)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    assert db.get_relationship_rows(-1) == []

    # Restore the default session factory before exercising other code paths.
    monkeypatch.setattr(db, "get_session", lambda: make_session())

    with pytest.raises(ValueError, match="Select a different NPC"):
        db.save_relationship(data["npc"].id, data["npc"].id, "Self")

    with pytest.raises(ValueError, match="Save the NPC before adding relationships"):
        db.save_relationship(-1, data["ally"].id, "Test")

    with pytest.raises(ValueError, match="Select a valid related NPC"):
        db.save_relationship(data["npc"].id, -1, "Test")

    insert_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: insert_session)
    db.save_relationship(data["ally"].id, data["extra"].id, "Friend")
    verify = make_session()
    relation = (
        verify.query(db.Relationship)
        .filter(
            db.Relationship.npc_id_1 == data["ally"].id,
            db.Relationship.npc_id_2 == data["extra"].id,
        )
        .one()
    )
    assert relation.name == "Friend"
    verify.close()

    update_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: update_session)
    db.save_relationship(data["npc"].id, data["ally"].id, "Partner")
    verify_update = make_session()
    relation = (
        verify_update.query(db.Relationship)
        .filter(
            db.Relationship.npc_id_1 == data["npc"].id,
            db.Relationship.npc_id_2 == data["ally"].id,
        )
        .one()
    )
    assert relation.name == "Partner"
    verify_update.close()

    error_session = make_session()
    rollback_calls = {"count": 0}
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "relationship save"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to save the relationship"):
        db.save_relationship(data["npc"].id, data["extra"].id, "Allies")
    assert rollback_calls["count"] == 1

    assert db.is_text_column(db.NPC.description) is True
    assert db.is_text_column(db.NPC.age) is False


def test_delete_relationship_paths(
    make_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    data = seed_world(session)
    session.close()

    db.delete_relationship(-1, -1)
    verify_none = make_session()
    assert verify_none.query(db.Relationship).count() == 1
    verify_none.close()

    success_session = make_session()
    monkeypatch.setattr(db, "get_session", lambda: success_session)
    db.delete_relationship(data["npc"].id, data["ally"].id)
    verify = make_session()
    assert (
        verify.query(db.Relationship)
        .filter(
            db.Relationship.npc_id_1 == data["npc"].id,
            db.Relationship.npc_id_2 == data["ally"].id,
        )
        .first()
        is None
    )
    verify.close()

    # Create another relationship entry so the failure path exercises commit/rollback.
    reseed_session = make_session()
    reseed_session.add(
        db.Relationship(
            npc_id_1=data["ally"].id,
            npc_id_2=data["extra"].id,
            name="Friend",
        ),
    )
    reseed_session.commit()
    reseed_session.close()

    error_session = make_session()
    rollback_calls = {"count": 0}
    original_rollback = error_session.rollback

    def failing_commit() -> None:
        msg = "relationship delete"
        raise SQLAlchemyError(msg)

    def tracking_rollback() -> None:
        rollback_calls["count"] += 1
        original_rollback()

    monkeypatch.setattr(error_session, "commit", failing_commit)
    monkeypatch.setattr(error_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db, "get_session", lambda: error_session)
    with pytest.raises(RuntimeError, match="Unable to delete the relationship"):
        db.delete_relationship(data["ally"].id, data["extra"].id)
    assert rollback_calls["count"] == 1


def test_get_types_returns_expected() -> None:
    assert db.get_types() == ["NPC", "Location", "Encounter"]


def test_setup_database_rebuild(
    memory_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    drop_calls: list[Engine] = []
    create_calls: list[Engine] = []

    def fake_drop(engine: Engine) -> None:
        drop_calls.append(engine)

    def fake_create(engine: Engine) -> None:
        create_calls.append(engine)

    storage_dir = tmp_path / "db"
    storage_dir.mkdir()
    yaml_file = storage_dir / "campaign.yaml"
    yaml_file.write_text("junk", encoding="utf-8")

    monkeypatch.setattr(db.Base.metadata, "drop_all", fake_drop)
    monkeypatch.setattr(db.Base.metadata, "create_all", fake_create)
    monkeypatch.setattr(db.engine_manager, "yaml_storage_path", storage_dir)
    factory = db.setup_database(rebuild=True, loglevel=LogLevels.DEBUG)
    assert drop_calls == [memory_engine]
    assert create_calls == [memory_engine]
    assert not yaml_file.exists()
    session = factory()
    session.close()


def test_export_database_ddl_outputs_schema(
    memory_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert memory_engine is not None
    buffer = io.StringIO()
    db.export_database_ddl(buffer)
    ddl_text = buffer.getvalue()
    assert "-- Generated schema --" in ddl_text
    assert "CREATE TABLE" in ddl_text


def test_export_database_ddl_handles_empty_schema(
    memory_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert memory_engine is not None
    buffer = io.StringIO()
    monkeypatch.setattr(db, "_read_config", lambda: {"DB": {"database": "demo"}})
    empty_metadata = SimpleNamespace(sorted_tables=())
    monkeypatch.setattr(db.Base, "metadata", empty_metadata)
    db.export_database_ddl(buffer)
    assert buffer.getvalue() == "-- No tables defined.\n"


def test_cli_prints_help(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_export() -> None:
        calls["count"] += 1

    _run_cli_block(monkeypatch, ["db.py"], fake_export)
    assert calls["count"] == 0


def test_cli_runs_export(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_export() -> None:
        calls["count"] += 1

    _run_cli_block(monkeypatch, ["db.py", "--export-ddl"], fake_export)
    assert calls["count"] == 1

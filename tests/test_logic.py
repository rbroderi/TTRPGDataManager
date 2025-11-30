# pyright: reportGeneralTypeIssues=false

"""Unit tests for final_project.logic."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from final_project import logic
from final_project.logic import DataLogic
from final_project.logic import DuplicateRecordError
from final_project.logic import FieldSpec
from final_project.logic import PersistenceResult


class ColumnCollection:
    def __init__(self, columns: dict[str, FakeColumn]) -> None:
        self._columns = columns

    def __iter__(self) -> Iterator[FakeColumn]:  # pragma: no cover - simple container
        return iter(self._columns.values())

    def __getitem__(self, key: str) -> FakeColumn:  # pragma: no cover - helper
        return self._columns[key]

    def get(self, key: str, default: FakeColumn | None = None) -> FakeColumn | None:
        return self._columns.get(key, default)


class RaisingType:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    @property
    def python_type(self) -> Any:  # pragma: no cover - used for error branch
        raise self._exc


class FakeColumn:
    def __init__(
        self,
        key: str,
        *,
        nullable: bool = False,
        primary_key: bool = False,
        python_type: type | Exception = str,
        enums: tuple[str, ...] | None = None,
    ) -> None:
        self.key = key
        self.nullable = nullable
        self.primary_key = primary_key
        if isinstance(python_type, Exception):
            self.type = RaisingType(python_type)
        else:
            self.type = SimpleNamespace(python_type=python_type, enums=enums)


def make_model(columns: list[FakeColumn]) -> type:
    table = SimpleNamespace(
        columns=ColumnCollection({column.key: column for column in columns}),
    )
    return type("MockModel", (), {"__table__": table})


class DummyQuery:
    def __init__(self, session: DummySession) -> None:
        self.session = session
        self.filters: list[Any] = []

    def filter(self, criterion: Any) -> DummyQuery:
        self.filters.append(criterion)
        return self

    def one_or_none(self) -> Any:
        return self.session.to_return

    def all(self) -> list[Any]:
        return ["row", *self.filters]


class DummySession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.to_return: Any = None

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True

    def query(self, model: Any) -> DummyQuery:
        return DummyQuery(self)

    def get(self, model: Any, pk: Any) -> Any:
        return self.to_return


def make_session() -> DummySession:
    return DummySession()


@pytest.fixture
def data_logic() -> DataLogic:
    return DataLogic()


def test_model_for_returns_mapping_and_none(data_logic: DataLogic) -> None:
    assert data_logic.model_for("NPC") is not None
    assert data_logic.model_for("Unknown") is None


def test_build_form_field_map_uses_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    sample_spec = (FieldSpec(label="Name", key="name"),)

    def fake_get(self: DataLogic, *_args: Any, **_kwargs: Any) -> tuple[FieldSpec, ...]:
        return sample_spec

    def fake_order(
        self: DataLogic,
        specs: tuple[FieldSpec, ...],
    ) -> tuple[FieldSpec, ...]:
        return tuple(reversed(specs))

    monkeypatch.setattr(DataLogic, "_get_field_specs", fake_get)
    monkeypatch.setattr(DataLogic, "_order_npc_specs", fake_order)
    result = logic_obj.build_form_field_map()
    assert result["NPC"][0].key == "name"
    assert result["Location"] == sample_spec


@pytest.mark.parametrize(
    ("method_name", "target"),
    [
        ("list_species", "get_species"),
        ("list_locations", "get_locations"),
        ("list_factions", "get_factions"),
    ],
)
def test_list_helpers_call_db(
    data_logic: DataLogic,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    target: str,
) -> None:
    calls: list[tuple[str | None]] = []

    def fake_fetch(campaign: str | None) -> list[str]:
        calls.append((campaign,))
        return ["value"]

    monkeypatch.setattr(logic, target, fake_fetch)
    method = getattr(data_logic, method_name)
    assert method("camp") == ["value"]
    assert calls == [("camp",)]


def test_seed_and_sample_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logic, "core_tables_empty", lambda: True)
    monkeypatch.setattr(logic, "load_all_sample_data", lambda: {"NPC": 2})
    assert DataLogic.should_seed_sample_data() is True
    assert DataLogic.load_sample_data() == {"NPC": 2}


def test_relationship_helpers_call_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logic, "get_npcs", lambda campaign=None: ["A", "B"])
    logic_obj = DataLogic()
    assert logic_obj.relationship_targets_for_campaign("camp", exclude=["B"]) == ["A"]
    called: list[tuple[str, str, str]] = []

    def fake_save(source: str, target: str, relation: str) -> None:
        called.append((source, target, relation))

    monkeypatch.setattr(logic, "save_relationship", fake_save)
    logic_obj.upsert_relationship("s", "t", "ally")
    assert called == [("s", "t", "ally")]
    deleted: list[tuple[str, str]] = []

    def fake_delete(source: str, target: str) -> None:
        deleted.append((source, target))

    monkeypatch.setattr(logic, "delete_relationship", fake_delete)
    logic_obj.delete_relationship("s", "t")
    assert deleted[-1] == ("s", "t")


def test_relationship_targets_without_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logic, "get_npcs", lambda campaign=None: ["A", "B"])
    assert DataLogic().relationship_targets_for_campaign("camp") == ["A", "B"]


def test_fetch_relationship_rows_and_members(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logic, "get_relationship_rows", lambda name: [(name, "ally")])
    assert DataLogic.fetch_relationship_rows("npc") == [("npc", "ally")]
    monkeypatch.setattr(logic, "get_encounter_participants", lambda enc: [(enc, "npc")])
    assert DataLogic.fetch_encounter_members(1) == [(1, "npc")]
    assert DataLogic.fetch_encounter_members(0) == []


def test_add_and_remove_encounter_member(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    with pytest.raises(ValueError, match="Save the encounter"):
        logic_obj.add_encounter_member(0, "npc", "note")
    with pytest.raises(ValueError, match="Select an NPC"):
        logic_obj.add_encounter_member(1, "   ", "note")
    captured: list[tuple[int, str, str]] = []

    def fake_upsert(enc_id: int, name: str, notes: str) -> None:
        captured.append((enc_id, name, notes))

    monkeypatch.setattr(logic, "upsert_encounter_participant", fake_upsert)
    logic_obj.add_encounter_member(2, "  Mira  ", "  note  ")
    assert captured == [(2, "Mira", "note")]
    removed: list[tuple[int, str]] = []

    def fake_delete_participant(enc_id: int, name: str) -> None:
        removed.append((enc_id, name))

    monkeypatch.setattr(logic, "delete_encounter_participant", fake_delete_participant)
    logic_obj.remove_encounter_member(0, "npc")
    assert not removed
    logic_obj.remove_encounter_member(2, "  Mira  ")
    assert removed == [(2, "Mira")]


def test_faction_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    with pytest.raises(ValueError, match="Faction name cannot"):
        logic_obj.ensure_faction("  ", "desc", "camp")
    with pytest.raises(ValueError, match="Select a campaign"):
        logic_obj.ensure_faction("Name", "desc", "")
    captured: list[tuple[str, str, str]] = []

    def fake_faction(name: str, description: str, campaign: str) -> None:
        captured.append((name, description, campaign))

    monkeypatch.setattr(logic, "upsert_faction", fake_faction)
    logic_obj.ensure_faction("  Name  ", " Desc ", "Camp")
    assert captured == [("Name", "Desc", "Camp")]
    monkeypatch.setattr(logic, "get_faction_membership", lambda name: (name, "notes"))
    assert DataLogic.fetch_faction_membership("") is None
    assert DataLogic.fetch_faction_membership("npc") == ("npc", "notes")
    monkeypatch.setattr(logic, "get_faction_details", lambda name: ("desc", name))
    assert DataLogic.fetch_faction_details("") is None
    assert DataLogic.fetch_faction_details("guild") == ("desc", "guild")


def test_assign_and_clear_faction_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="NPC name is required"):
        DataLogic.assign_faction_to_npc("", "faction", "")
    cleared: list[str] = []
    monkeypatch.setattr(logic, "db_clear_faction_membership", cleared.append)
    DataLogic.assign_faction_to_npc("npc", "", "secret")
    assert cleared == ["npc"]
    assigned: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        logic,
        "assign_faction_member",
        lambda npc, faction, notes: assigned.append((npc, faction, notes)),
    )
    DataLogic.assign_faction_to_npc("npc", "guild", "  notes  ")
    assert assigned == [("npc", "guild", "notes")]
    DataLogic.clear_faction_membership("npc")
    assert cleared[-1] == "npc"


def test_validate_required_fields_detects_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gender_column = FakeColumn("gender", nullable=False)
    desc_column = FakeColumn("description", nullable=False)
    model = make_model([gender_column, desc_column])
    spec_map = {
        "description": FieldSpec(label="Bio", key="description"),
    }
    values = {"gender": " f "}
    DataLogic().validate_required_fields(model, values, spec_map)
    assert values["gender"] == "F"
    values["description"] = " "
    with pytest.raises(ValueError, match="Bio"):
        DataLogic().validate_required_fields(model, values, spec_map)


def test_validate_required_fields_handles_special_columns_and_gender_numbers() -> None:
    model = make_model(
        [
            FakeColumn("campaign_name", nullable=False),
            FakeColumn("image_blob", nullable=False),
            FakeColumn("id", nullable=False),
            FakeColumn("gender", nullable=False),
            FakeColumn("overview", nullable=False),
        ],
    )
    values = {"overview": "Story", "gender": 7}
    spec_map = {"overview": FieldSpec("Overview", "overview")}
    DataLogic().validate_required_fields(model, values, spec_map)
    assert values["gender"] == "7"


def test_validate_required_fields_skips_nullable_columns() -> None:
    model = make_model([FakeColumn("notes", nullable=True)])
    DataLogic().validate_required_fields(model, {}, {})


def test_create_entry_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    monkeypatch.setattr(
        logic_obj,
        "_ensure_unique_name",
        lambda *args, **kwargs: None,
    )
    payload = {"name": "Ada"}
    monkeypatch.setattr(
        logic_obj,
        "_build_new_record_payload",
        lambda *a, **k: payload,
    )
    instance = logic_obj.create_entry(
        "NPC",
        SimpleNamespace,
        {"name": "Ada"},
        "Camp",
        None,
        {},
    )
    assert session.added[0] is instance
    assert session.committed is True
    assert session.closed is True

    def raise_duplicate(*_args: Any, **_kwargs: Any) -> None:
        message = "dup"
        raise DuplicateRecordError(message)

    monkeypatch.setattr(logic_obj, "_ensure_unique_name", raise_duplicate)
    with pytest.raises(DuplicateRecordError):
        logic_obj.create_entry(
            "NPC",
            SimpleNamespace,
            {"name": "Ada"},
            "Camp",
            None,
            {},
        )
    assert session.rolled_back is True


def test_create_entry_rolls_back_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    monkeypatch.setattr(logic_obj, "_ensure_unique_name", lambda *_a, **_k: None)

    def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        message = "boom"
        raise RuntimeError(message)

    monkeypatch.setattr(logic_obj, "_build_new_record_payload", boom)
    with pytest.raises(RuntimeError, match="boom"):
        logic_obj.create_entry(
            "NPC",
            SimpleNamespace,
            {"name": "Ada"},
            "Camp",
            None,
            {},
        )
    assert session.rolled_back is True
    assert session.closed is True


def test_create_entry_rolls_back_when_model_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    monkeypatch.setattr(logic_obj, "_ensure_unique_name", lambda *_a, **_k: None)
    monkeypatch.setattr(
        logic_obj,
        "_build_new_record_payload",
        lambda *_a, **_k: {"name": "Ada"},
    )

    class BadModel:
        def __init__(self, **_kwargs: Any) -> None:
            message = "fail"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="fail"):
        logic_obj.create_entry("NPC", BadModel, {"name": "Ada"}, "Camp", None, {})
    assert session.rolled_back is True


def test_create_entry_rolls_back_when_session_add_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()

    def broken_add(_instance: Any) -> None:
        message = "session add failed"
        raise RuntimeError(message)

    session.add = broken_add  # type: ignore[method-assign]
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    monkeypatch.setattr(logic_obj, "_ensure_unique_name", lambda *_a, **_k: None)
    monkeypatch.setattr(
        logic_obj,
        "_build_new_record_payload",
        lambda *_a, **_k: {"name": "Ada"},
    )
    with pytest.raises(RuntimeError, match="session add failed"):
        logic_obj.create_entry(
            "NPC",
            SimpleNamespace,
            {"name": "Ada"},
            "Camp",
            None,
            {},
        )
    assert session.rolled_back is True
    assert session.closed is True


def test_delete_entry_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    with pytest.raises(ValueError, match="Unsupported entry type"):
        logic_obj.delete_entry("Bad", "id")
    with pytest.raises(ValueError, match="Select a npc"):
        logic_obj.delete_entry("NPC", " ")
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    monkeypatch.setattr(logic_obj, "_fetch_instance", lambda *a, **k: None)
    assert logic_obj.delete_entry("NPC", "Alice") is False
    instance = SimpleNamespace()
    monkeypatch.setattr(logic_obj, "_fetch_instance", lambda *a, **k: instance)
    assert logic_obj.delete_entry("NPC", "Alice") is True
    assert session.deleted[-1] is instance


def test_delete_entry_rolls_back_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    session = make_session()

    def bad_delete(_instance: Any) -> None:
        message = "delete failed"
        raise RuntimeError(message)

    session.delete = bad_delete  # type: ignore[method-assign]
    monkeypatch.setattr(logic, "get_session", lambda: session)
    monkeypatch.setattr(
        logic_obj,
        "_fetch_instance",
        lambda *_a, **_k: SimpleNamespace(),
    )
    with pytest.raises(RuntimeError, match="delete failed"):
        logic_obj.delete_entry("NPC", "Alice")
    assert session.rolled_back is True
    assert session.closed is True


def test_search_entries_partial_and_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()

    class ColumnStub:
        def __init__(self, key: str) -> None:
            self.key = key

        def ilike(self, pattern: str) -> tuple[str, str]:
            return (self.key, pattern)

        def __eq__(self, other: object) -> Any:  # type: ignore[override]
            return (self.key, other)

        def __hash__(self) -> int:  # pragma: no cover - deterministic
            return hash(self.key)

    class Model:
        name = ColumnStub("name")
        age = ColumnStub("age")

    filters = [
        ("name", "Ada", None),
        ("age", 30, FieldSpec("Age", "age", enum_values=("30",))),
    ]
    results = logic_obj.search_entries(Model, filters)
    assert ("name", "%Ada%") in results
    assert ("age", 30) in results


def test_persist_pending_records_handles_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    pending_changes = {
        ("NPC", "Ada"): {"name": "Ada"},
        ("Unknown", "x"): {"foo": "bar"},
    }
    pending_images = {
        ("NPC", "Ada"): b"img",
        ("NPC", "B"): b"img",
    }
    instances = {"Ada": SimpleNamespace(name="Ada"), "B": None}

    def fake_fetch(_session: Any, entry_type: str, _model: Any, identifier: str) -> Any:
        return instances.get(identifier)

    monkeypatch.setattr(logic_obj, "_fetch_instance", fake_fetch)

    def fake_apply(*_args: Any, **_kwargs: Any) -> tuple[bool, str | None]:
        identifier = _kwargs.get("field_values", {}).get("name")
        return True, identifier

    monkeypatch.setattr(logic_obj, "_apply_pending_to_instance", fake_apply)
    spec_map = {"name": FieldSpec("Name", "name")}
    result = logic_obj.persist_pending_records(
        pending_changes,
        pending_images,
        lambda _entry: spec_map,
    )
    assert isinstance(result, PersistenceResult)
    assert result.updated == 1
    assert session.committed is True
    empty_result = logic_obj.persist_pending_records({}, {}, lambda _: {})
    assert empty_result.updated == 0


def test_persist_pending_records_ignores_unknown_entry_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    result = logic_obj.persist_pending_records(
        {("Mystery", "X"): {"name": "X"}},
        {},
        lambda _: {},
    )
    assert result.updated == 0
    assert result.applied_keys == set()
    assert result.renamed_keys == {}


def test_persist_pending_records_tracks_renamed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    model = make_model([FakeColumn("name"), FakeColumn("age")])
    model.name = "name"
    logic_obj._model_map["NPC"] = model
    instance = SimpleNamespace(name="Old", age=1, image_blob=None)
    session.to_return = instance
    field_values = {"name": "New", "unused": "value"}
    pending_changes = {("NPC", "Old"): field_values}
    pending_images = {("NPC", "Old"): b"img"}
    result = logic_obj.persist_pending_records(
        pending_changes,
        pending_images,
        lambda _entry: {"name": FieldSpec("Name", "name")},
    )
    assert result.updated == 1
    assert result.applied_keys == {("NPC", "Old")}
    assert result.renamed_keys[("NPC", "Old")] == ("NPC", "New")
    assert instance.name == "New"
    assert instance.image_blob == b"img"


def test_persist_pending_records_rolls_back_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    logic_obj._model_map["NPC"] = make_model([FakeColumn("name")])

    def boom(*_args: Any, **_kwargs: Any) -> None:
        message = "fail"
        raise RuntimeError(message)

    monkeypatch.setattr(logic_obj, "_fetch_instance", boom)
    with pytest.raises(RuntimeError, match="fail"):
        logic_obj.persist_pending_records(
            {("NPC", "Ada"): {"name": "Ada"}},
            {},
            lambda _entry: {},
        )
    assert session.rolled_back is True


def test_persist_pending_records_skips_when_no_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    monkeypatch.setattr(logic, "get_session", lambda: session)
    logic_obj = DataLogic()
    logic_obj._model_map["NPC"] = make_model([FakeColumn("name")])
    instance = SimpleNamespace(name="Ada")
    monkeypatch.setattr(logic_obj, "_fetch_instance", lambda *_a, **_k: instance)
    monkeypatch.setattr(
        logic_obj,
        "_apply_pending_to_instance",
        lambda *_a, **_k: (False, None),
    )
    result = logic_obj.persist_pending_records(
        {("NPC", "Ada"): {"name": "Ada"}},
        {},
        lambda _entry: {},
    )
    assert result.updated == 0
    assert session.committed is True


def test_coerce_value_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    monkeypatch.setattr(logic_obj, "_coerce_value", lambda *_: "coerced")
    assert logic_obj.coerce_value(SimpleNamespace(), "5") == "coerced"


def test_get_field_specs_builds_expected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        logic,
        "is_text_column",
        lambda column: column.key == "description",
    )
    monkeypatch.setattr(logic, "get_species", lambda campaign=None: ("Elf",))
    monkeypatch.setattr(logic, "get_locations", lambda campaign=None: ("City",))
    text_col = FakeColumn("description", python_type=str)
    species_col = FakeColumn("species_name", python_type=str)
    location_col = FakeColumn("location_name", python_type=str)
    json_col = FakeColumn("abilities_json", python_type=str)
    enum_col = FakeColumn("alignment_name", python_type=str, enums=("LG", "CG"))
    model = make_model(
        [FakeColumn("id"), text_col, species_col, location_col, json_col, enum_col],
    )
    specs = DataLogic()._get_field_specs(model, ignore=("Id",))
    assert any(
        spec.key == "species_name" and spec.preset_values == ("Elf",) for spec in specs
    )
    assert any(
        spec.key == "location_name" and spec.preset_values == ("City",)
        for spec in specs
    )
    assert any(spec.key == "abilities_json" and spec.is_json for spec in specs)


def test_get_field_specs_honors_ignore_labels() -> None:
    model = make_model([FakeColumn("secret_code"), FakeColumn("title")])
    specs = DataLogic()._get_field_specs(model, ignore=("Secret Code",))
    assert all(spec.key != "secret_code" for spec in specs)
    assert any(spec.key == "title" for spec in specs)


def test_get_field_specs_handles_problem_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logic, "is_text_column", lambda _column: False)

    class NullKeyColumn:
        def __init__(self) -> None:
            self.key = None
            self.nullable = True
            self.primary_key = False
            self.type = SimpleNamespace(python_type=str)

    columns = [
        NullKeyColumn(),
        FakeColumn("blob", python_type=bytes),
        FakeColumn("tricky", python_type=ValueError("bad")),
        FakeColumn("title"),
    ]
    model = make_model(columns)
    specs = DataLogic()._get_field_specs(model)
    assert any(spec.key == "title" for spec in specs)
    assert all(spec.key != "blob" for spec in specs)


def test_order_npc_specs_respects_priority() -> None:
    specs = [
        FieldSpec("Gender", "gender"),
        FieldSpec("Name", "name"),
        FieldSpec("Other", "other"),
    ]
    ordered = DataLogic._order_npc_specs(specs)
    assert ordered[0].key == "name"
    assert ordered[-1].key == "other"


def test_build_new_record_payload_validations(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    model = make_model(
        [
            FakeColumn("campaign_name"),
            FakeColumn("image_blob"),
            FakeColumn("name", primary_key=True),
        ],
    )
    with pytest.raises(ValueError, match="Select a campaign"):
        logic_obj._build_new_record_payload("NPC", model, {}, "", None, {})
    spec_map = {"name": FieldSpec("Name", "name")}
    with pytest.raises(ValueError, match="required"):
        logic_obj._build_new_record_payload(
            "NPC",
            model,
            {"name": ""},
            "Camp",
            None,
            spec_map,
        )


def test_build_new_record_payload_includes_campaign_and_image() -> None:
    logic_obj = DataLogic()
    model = make_model(
        [
            FakeColumn("campaign_name"),
            FakeColumn("image_blob"),
            FakeColumn("name", primary_key=True),
        ],
    )
    payload = logic_obj._build_new_record_payload(
        "NPC",
        model,
        {"name": "Ada"},
        "Camp",
        b"img",
        {"name": FieldSpec("Name", "name")},
    )
    assert payload["campaign_name"] == "Camp"
    assert payload["image_blob"] == b"img"
    assert payload["name"] == "Ada"


def test_build_new_record_payload_skips_non_applicable_columns() -> None:
    logic_obj = DataLogic()

    class NullKeyColumn(FakeColumn):
        def __init__(self) -> None:
            super().__init__("temp")
            self.key = None

    model = make_model(
        [
            NullKeyColumn(),
            FakeColumn("campaign_name"),
            FakeColumn("image_blob"),
            FakeColumn("id", primary_key=True),
            FakeColumn("unused"),
            FakeColumn("name", primary_key=True),
        ],
    )
    payload = logic_obj._build_new_record_payload(
        "Encounter",
        model,
        {"name": "Ada"},
        "Quest",
        b"img",
        {"name": FieldSpec("Name", "name")},
    )
    assert None not in payload
    assert "id" not in payload
    assert "unused" not in payload


def test_ensure_unique_name_handles_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    session = make_session()

    class Model:
        name = "name"

    model = Model
    session.to_return = None
    logic_obj._ensure_unique_name(session, "NPC", model, "Alice")
    session.to_return = object()
    with pytest.raises(DuplicateRecordError):
        logic_obj._ensure_unique_name(session, "NPC", model, "Alice")


def test_ensure_unique_name_early_return_paths() -> None:
    logic_obj = DataLogic()
    session = make_session()
    logic_obj._ensure_unique_name(
        session,
        "Encounter",
        type("Encounter", (), {}),
        "Ada",
    )

    class Nameless:
        pass

    logic_obj._ensure_unique_name(session, "NPC", Nameless, "Ada")
    logic_obj._ensure_unique_name(
        session,
        "NPC",
        type("Model", (), {"name": "name"}),
        "",
    )


def test_prepare_value_json_and_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    logic_obj = DataLogic()
    gender_column = FakeColumn("gender")
    assert logic_obj._prepare_value(gender_column, " f ", None) == (True, "F")
    json_column = FakeColumn("abilities_json")
    spec = FieldSpec("Abilities", "abilities_json", is_json=True)
    assert logic_obj._prepare_value(json_column, "", spec) == (True, {})
    assert logic_obj._prepare_value(json_column, '{"a": 1}', spec)[1] == {"a": 1}
    with pytest.raises(ValueError, match="Invalid JSON"):
        logic_obj._prepare_value(json_column, "{\n", spec)
    int_column = FakeColumn("score", python_type=int)
    expected_score = 5
    test_score_input = "5"
    assert (
        logic_obj._prepare_value(int_column, test_score_input, None)[1]
        == expected_score
    )


def test_prepare_value_handles_bad_column_type_and_non_string_input() -> None:
    logic_obj = DataLogic()
    bad_column = FakeColumn("note", python_type=ValueError("boom"))
    assert logic_obj._prepare_value(bad_column, " text ", None)[1] == " text "
    int_column = FakeColumn("score", python_type=int)
    raw_value = 7
    assert (
        logic_obj._prepare_value(int_column, raw_value, FieldSpec("Score", "score"))[1]
        == raw_value
    )


def test_prepare_value_handles_empty_non_nullable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logic_obj = DataLogic()
    non_nullable = FakeColumn("age", nullable=False, python_type=int)
    spec = FieldSpec("Age", "age")
    with pytest.raises(ValueError, match="Age cannot"):
        logic_obj._prepare_value(non_nullable, "", spec)
    nullable = FakeColumn("note", nullable=True, python_type=int)
    assert logic_obj._prepare_value(nullable, "", FieldSpec("Note", "note"))[1] is None


def test_coerce_value_types() -> None:
    expected = 5
    logic_obj = DataLogic()

    class DateType:
        python_type = date

    assert (
        logic_obj._coerce_value(
            SimpleNamespace(type=SimpleNamespace(python_type=int)),
            "5",
        )
        == expected
    )
    assert logic_obj._coerce_value(
        SimpleNamespace(type=SimpleNamespace(python_type=float)),
        "5.1",
    ) == pytest.approx(5.1)
    assert logic_obj._coerce_value(
        SimpleNamespace(type=SimpleNamespace(python_type=date)),
        "2024-01-01",
    ) == date(2024, 1, 1)
    assert (
        logic_obj._coerce_value(
            SimpleNamespace(type=SimpleNamespace(python_type=str)),
            "x",
        )
        == "x"
    )


def test_coerce_value_falls_back_to_string() -> None:
    logic_obj = DataLogic()
    bad_column = FakeColumn("note", python_type=ValueError("bad"))
    assert logic_obj._coerce_value(bad_column, "value") == "value"


def test_apply_pending_to_instance_updates_and_images() -> None:
    model = make_model([FakeColumn("name"), FakeColumn("age")])
    instance = SimpleNamespace(name="Ada", age=20, image_blob=None)
    logic_obj = DataLogic()
    field_values = {"name": "Ada", "age": "30", "unknown": "value"}
    changed, identifier = logic_obj._apply_pending_to_instance(
        "NPC",
        model,
        instance,
        field_values,
        {"name": FieldSpec("Name", "name"), "age": FieldSpec("Age", "age")},
        b"img",
    )
    assert changed is True
    assert identifier == "Ada"
    assert instance.image_blob == b"img"
    unchanged = logic_obj._apply_pending_to_instance(
        "NPC",
        model,
        instance,
        {},
        {},
        None,
    )
    assert unchanged == (False, None)


def test_apply_pending_skips_fields_when_prepare_value_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = make_model([FakeColumn("skip"), FakeColumn("name")])
    instance = SimpleNamespace(name="Ada", skip="keep", image_blob=None)
    logic_obj = DataLogic()

    def fake_prepare(
        column: Any,
        raw_value: Any,
        spec: FieldSpec | None,
    ) -> tuple[bool, Any]:
        if column.key == "skip":
            return False, None
        return True, raw_value

    monkeypatch.setattr(logic_obj, "_prepare_value", fake_prepare)
    changed, identifier = logic_obj._apply_pending_to_instance(
        "NPC",
        model,
        instance,
        {"skip": "new", "name": "Ada"},
        {"name": FieldSpec("Name", "name"), "skip": FieldSpec("Skip", "skip")},
        None,
    )
    assert changed is True
    assert identifier == "Ada"
    assert instance.skip == "keep"


def test_fetch_instance_rejects_bad_encounter_identifier() -> None:
    session = make_session()
    assert (
        DataLogic._fetch_instance(
            session,
            "Encounter",
            type("Encounter", (), {}),
            "abc",
        )
        is None
    )


def test_fetch_instance_returns_none_without_name_column() -> None:
    session = make_session()
    assert (
        DataLogic._fetch_instance(
            session,
            "NPC",
            type("Nameless", (), {}),
            "Ada",
        )
        is None
    )


def test_extract_instance_identifier() -> None:
    assert (
        DataLogic._extract_instance_identifier("Encounter", SimpleNamespace(id=5))
        == "5"
    )
    assert (
        DataLogic._extract_instance_identifier("NPC", SimpleNamespace(name="Ada"))
        == "Ada"
    )
    assert (
        DataLogic._extract_instance_identifier("NPC", SimpleNamespace(name="")) is None
    )


def test_fetch_instance_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session()
    session.to_return = SimpleNamespace()
    encounter = DataLogic._fetch_instance(
        session,
        "Encounter",
        type("Encounter", (), {}),
        "bad",
    )
    assert encounter is None
    session.to_return = SimpleNamespace(id=1)
    encounter = DataLogic._fetch_instance(
        session,
        "Encounter",
        type("Encounter", (), {}),
        "1",
    )
    assert encounter is session.to_return
    model = type("NPCModel", (), {"name": "name"})
    session.to_return = SimpleNamespace(name="Ada")
    result = DataLogic._fetch_instance(session, "NPC", model, "Ada")
    assert result is session.to_return
    session.to_return = SimpleNamespace(id=2)
    assert (
        DataLogic._fetch_instance(session, "Other", type("Other", (), {}), "2")
        is session.to_return
    )


def test_use_partial_match_behavior() -> None:
    assert DataLogic._use_partial_match(None) is True
    spec = FieldSpec("Choice", "choice", enum_values=("A",))
    assert DataLogic._use_partial_match(spec) is False

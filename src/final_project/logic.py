"""Business logic layer that mediates between the GUI and the database."""

# ruff: noqa: I001

from __future__ import annotations
from lazi.core import lazi

with lazi:  # type: ignore[attr-defined]
    import json
    from collections.abc import Callable, Iterable, Sequence
    from dataclasses import dataclass
    from datetime import date as dtdate
    from typing import Any, cast

    import structlog

from final_project.db import Encounter
from final_project.db import ImageStore
from final_project.db import Location
from final_project.db import NPC
from final_project.db import assign_faction_member
from final_project.db import clear_faction_membership as db_clear_faction_membership
from final_project.db import core_tables_empty
from final_project.db import delete_encounter_participant
from final_project.db import delete_relationship
from final_project.db import get_encounter_participants
from final_project.db import get_faction_details
from final_project.db import get_faction_membership
from final_project.db import get_factions
from final_project.db import get_locations
from final_project.db import get_npcs
from final_project.db import get_relationship_rows
from final_project.db import get_session
from final_project.db import get_species
from final_project.db import is_text_column
from final_project.db import load_all_sample_data
from final_project.db import save_relationship
from final_project.db import upsert_encounter_participant
from final_project.db import upsert_faction

logger = structlog.getLogger("final_project")


@dataclass(slots=True)
class FieldSpec:
    """Describe how a form field should render."""

    label: str
    key: str
    enum_values: tuple[str, ...] | None = None
    multiline: bool = False
    is_json: bool = False
    preset_values: tuple[str, ...] | None = None


class DuplicateRecordError(ValueError):
    """Raised when attempting to create a record that already exists."""


@dataclass(slots=True)
class PersistenceResult:
    """Return data from a persistence attempt."""

    updated: int
    applied_keys: set[tuple[str, str]]
    renamed_keys: dict[tuple[str, str], tuple[str, str]]


class DataLogic:
    """Encapsulate all non-UI logic for the data manager."""

    def __init__(self) -> None:
        """Initialize the logic layer with model mappings."""
        self._model_map: dict[str, type] = {
            "NPC": NPC,
            "Location": Location,
            "Encounter": Encounter,
        }

    def model_for(self, entry_type: str) -> type | None:
        """Return the ORM model for the provided entry type."""
        return self._model_map.get(entry_type)

    def build_form_field_map(self) -> dict[str, tuple[FieldSpec, ...]]:
        """Generate ordered form field specifications for each entry type."""
        npc_specs = self._order_npc_specs(
            self._get_field_specs(NPC, ["Campaign Name"]),
        )
        return {
            "NPC": npc_specs,
            "Location": self._get_field_specs(Location, ["Campaign Name"]),
            "Encounter": self._get_field_specs(Encounter, ["Campaign Name"]),
        }

    def list_species(self, campaign: str | None) -> Sequence[str]:
        """Fetch species choices for a campaign."""
        return list(get_species(campaign))

    def list_locations(self, campaign: str | None) -> Sequence[str]:
        """Fetch location choices for a campaign."""
        return list(get_locations(campaign))

    def list_factions(self, campaign: str | None) -> Sequence[str]:
        """Fetch faction choices for a campaign."""
        return list(get_factions(campaign))

    @staticmethod
    def should_seed_sample_data() -> bool:
        """Return True when the core tables are empty and need sample data."""
        return core_tables_empty()

    @staticmethod
    def load_sample_data() -> dict[str, int]:
        """Load all bundled sample data into the database."""
        return load_all_sample_data()

    def relationship_targets_for_campaign(
        self,
        campaign: str | None,
        *,
        exclude: Sequence[str] | None = None,
    ) -> list[str]:
        """Return available NPC names for relationship dropdowns."""
        names = list(get_npcs(campaign))
        if not exclude:
            return names
        exclusions = set(exclude)
        return [name for name in names if name not in exclusions]

    @staticmethod
    def fetch_relationship_rows(source_name: str) -> list[tuple[str, str]]:
        """Fetch persisted relationships for display in the dialog."""
        return get_relationship_rows(source_name)

    @staticmethod
    def upsert_relationship(
        source_name: str,
        target_name: str,
        relation_name: str,
    ) -> None:
        """Create or update the relationship between two NPCs."""
        save_relationship(source_name, target_name, relation_name)

    @staticmethod
    def delete_relationship(source_name: str, target_name: str) -> None:
        """Delete an existing relationship between two NPCs."""
        delete_relationship(source_name, target_name)

    @staticmethod
    def fetch_encounter_members(encounter_id: int) -> list[tuple[str, str]]:
        """Return the participants for a persisted encounter."""
        if not encounter_id:
            return []
        return get_encounter_participants(encounter_id)

    @staticmethod
    def add_encounter_member(encounter_id: int, npc_name: str, notes: str) -> None:
        """Assign an NPC to an encounter with optional notes."""
        if not encounter_id:
            msg = "Save the encounter before editing participants."
            raise ValueError(msg)
        cleaned_name = npc_name.strip()
        if not cleaned_name:
            msg = "Select an NPC to add to the encounter."
            raise ValueError(msg)
        upsert_encounter_participant(encounter_id, cleaned_name, notes.strip())

    @staticmethod
    def remove_encounter_member(encounter_id: int, npc_name: str) -> None:
        """Remove an NPC from a stored encounter."""
        if not encounter_id or not npc_name.strip():
            return
        delete_encounter_participant(encounter_id, npc_name.strip())

    def ensure_faction(self, name: str, description: str, campaign_name: str) -> None:
        """Create or update a faction definition."""
        if not name.strip():
            msg = "Faction name cannot be empty."
            raise ValueError(msg)
        if not campaign_name:
            msg = "Select a campaign before creating factions."
            raise ValueError(msg)
        upsert_faction(name.strip(), description.strip(), campaign_name)

    @staticmethod
    def fetch_faction_membership(npc_name: str) -> tuple[str, str] | None:
        """Return the first faction membership for an NPC."""
        if not npc_name:
            return None
        return get_faction_membership(npc_name)

    @staticmethod
    def fetch_faction_details(name: str) -> tuple[str, str] | None:
        """Return description and campaign for the faction."""
        if not name:
            return None
        return get_faction_details(name)

    @staticmethod
    def assign_faction_to_npc(npc_name: str, faction_name: str, notes: str) -> None:
        """Assign or update an NPC's faction membership."""
        if not npc_name:
            msg = "NPC name is required for faction assignment."
            raise ValueError(msg)
        if not faction_name:
            db_clear_faction_membership(npc_name)
            return
        assign_faction_member(npc_name, faction_name, notes.strip())

    @staticmethod
    def clear_faction_membership(npc_name: str) -> None:
        """Remove all faction memberships for an NPC."""
        db_clear_faction_membership(npc_name)

    def validate_required_fields(
        self,
        model_cls: type,
        field_values: dict[str, Any],
        spec_map: dict[str, FieldSpec],
    ) -> None:
        """Ensure a payload provides all required database columns."""
        columns = cast(
            "Iterable[Any]",
            model_cls.__table__.columns,  # type: ignore[attr-defined]
        )
        missing: list[str] = []
        for column in columns:
            column_key = getattr(column, "key", None)
            if not column_key or column.nullable:
                continue
            if column_key in {"id", "campaign_name"}:
                continue
            if column_key not in field_values:
                continue
            raw_value = field_values[column_key]
            if column_key == "gender":
                if isinstance(raw_value, str):
                    normalized_gender = raw_value.strip().upper()
                else:
                    normalized_gender = str(raw_value).strip().upper()
                field_values[column_key] = normalized_gender or "UNSPECIFIED"
                continue
            normalized: Any = (
                raw_value.strip() if isinstance(raw_value, str) else raw_value
            )
            if normalized in {None, ""}:
                spec = spec_map.get(column_key)
                label = spec.label if spec else column_key.replace("_", " ").title()
                missing.append(label)
        if missing:
            labels = ", ".join(missing)
            msg = f"The following field(s) cannot be empty: {labels}."
            raise ValueError(msg)

    def create_entry(  # noqa: PLR0913
        self,
        entry_type: str,
        model_cls: type,
        field_values: dict[str, Any],
        campaign_name: str,
        image_payload: bytes | None,
        spec_map: dict[str, FieldSpec],
    ) -> Any:
        """Create and persist a new record."""
        session = get_session()
        try:
            name_value = field_values.get("name", "").strip()
            self._ensure_unique_name(session, entry_type, model_cls, name_value)
            payload = self._build_new_record_payload(
                entry_type,
                model_cls,
                field_values,
                campaign_name,
                spec_map,
            )
            instance = model_cls(**payload)
            self._apply_image_payload(instance, image_payload)
            session.add(instance)
            session.commit()
        except Exception:
            session.rollback()
            raise
        else:
            return instance
        finally:
            session.close()

    def delete_entry(self, entry_type: str, identifier: str) -> bool:
        """Delete a persisted entry for the provided type and identifier."""
        model_cls = self.model_for(entry_type)
        if model_cls is None:
            msg = f"Unsupported entry type: {entry_type}"
            raise ValueError(msg)
        normalized_id = str(identifier).strip()
        if not normalized_id:
            msg = f"Select a {entry_type.lower()} before deleting it."
            raise ValueError(msg)
        session = get_session()
        try:
            instance = self._fetch_instance(
                session,
                entry_type,
                model_cls,
                normalized_id,
            )
            if instance is None:
                return False
            session.delete(instance)
            session.commit()
        except Exception:
            session.rollback()
            raise
        else:
            return True
        finally:
            session.close()

    def search_entries(
        self,
        model_cls: type,
        filters: list[tuple[str, Any, FieldSpec | None]],
    ) -> list[Any]:
        """Execute a query for the given model using the provided filters."""
        session = get_session()
        try:
            query = cast(Any, session.query(model_cls))
            for key, value, spec in filters:
                column = getattr(model_cls, key)
                if isinstance(value, str) and value and self._use_partial_match(spec):
                    query = query.filter(column.ilike(f"%{value}%"))
                else:
                    query = query.filter(column == value)
            return cast(list[Any], query.all())
        finally:
            session.close()

    def persist_pending_records(
        self,
        pending_changes: dict[tuple[str, str], dict[str, Any]],
        pending_images: dict[tuple[str, str], bytes],
        spec_provider: Callable[[str], dict[str, FieldSpec]],
    ) -> PersistenceResult:
        """Persist any pending changes and return a summary of the work."""
        keys = set(pending_changes) | set(pending_images)
        if not keys:
            return PersistenceResult(0, set(), {})
        session = get_session()
        updated = 0
        applied_keys: set[tuple[str, str]] = set()
        renamed: dict[tuple[str, str], tuple[str, str]] = {}
        try:
            for key in keys:
                entry_type, identifier = key
                model_cls = self.model_for(entry_type)
                if model_cls is None:
                    logger.warning("unknown entry type '%s'", entry_type)
                    continue
                instance = self._fetch_instance(
                    session,
                    entry_type,
                    model_cls,
                    identifier,
                )
                if instance is None:
                    logger.warning(
                        "unable to locate %s '%s' for saving",
                        entry_type,
                        identifier,
                    )
                    continue
                spec_map = spec_provider(entry_type)
                field_values = pending_changes.get(key, {})
                override = pending_images.get(key)
                changed, new_identifier = self._apply_pending_to_instance(
                    entry_type,
                    model_cls,
                    instance,
                    field_values,
                    spec_map,
                    override,
                )
                if not changed:
                    continue
                updated += 1
                applied_keys.add(key)
                if new_identifier and new_identifier != identifier:
                    renamed[key] = (entry_type, new_identifier)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return PersistenceResult(updated, applied_keys, renamed)

    def coerce_value(self, column: Any, raw_value: str) -> Any:
        """Convert a string into the python type declared by a column."""
        return self._coerce_value(column, raw_value)

    def _get_field_specs(  # noqa: C901
        self,
        model_cls: type,
        ignore: Sequence[str] | None = None,
    ) -> tuple[FieldSpec, ...]:
        if ignore is None:
            ignore = ()
        columns = cast(
            "Iterable[Any]",
            model_cls.__table__.columns,  # type: ignore[attr-defined]
        )
        specs: list[FieldSpec] = []
        for column in columns:
            column_key = getattr(column, "key", None)
            lowered_key = str(column_key).lower()
            if lowered_key == "id":
                continue
            try:
                python_type = column.type.python_type
            except Exception:  # noqa: BLE001
                python_type = None
            if python_type is bytes:
                continue
            column_key = getattr(column, "key", None)
            if not column_key:
                continue
            label = str(column_key).replace("_", " ").title()
            if label in ignore:
                continue
            enums = getattr(column.type, "enums", None)
            enum_values = tuple(str(value) for value in enums) if enums else None
            multiline = is_text_column(column)
            is_json = str(column_key).lower().endswith("_json")
            multiline = multiline or is_json
            preset_values: tuple[str, ...] | None = None
            if "_name" in lowered_key:
                label = label.replace("Name", "").strip()
            if lowered_key == "species_name":
                preset_values = tuple(get_species())
            elif lowered_key == "location_name":
                preset_values = tuple(get_locations())
                label = "Location"
            specs.append(
                FieldSpec(
                    label=label,
                    key=lowered_key,
                    enum_values=enum_values,
                    multiline=multiline,
                    is_json=is_json,
                    preset_values=preset_values,
                ),
            )
        return tuple(specs)

    @staticmethod
    def _order_npc_specs(specs: Sequence[FieldSpec]) -> tuple[FieldSpec, ...]:
        desired_order = (
            "name",
            "gender",
            "age",
            "alignment_name",
            "species_name",
            "description",
            "abilities_json",
        )
        remaining = list(specs)
        ordered: list[FieldSpec] = []

        def _pop_key(target: str) -> None:
            for idx, spec in enumerate(list(remaining)):
                if spec.key == target:
                    ordered.append(remaining.pop(idx))
                    break

        for key in desired_order:
            _pop_key(key)

        ordered.extend(remaining)
        return tuple(ordered)

    def _build_new_record_payload(
        self,
        entry_type: str,
        model_cls: type,
        field_values: dict[str, Any],
        campaign_name: str,
        spec_map: dict[str, FieldSpec],
    ) -> dict[str, Any]:
        if not campaign_name:
            msg = "Select a campaign before creating entries."
            raise ValueError(msg)
        payload: dict[str, Any] = {}
        columns = cast(
            "Iterable[Any]",
            model_cls.__table__.columns,  # type: ignore[attr-defined]
        )
        for column in columns:
            column_key = getattr(column, "key", None)
            if not column_key:
                continue
            if column_key == "campaign_name":
                payload[column_key] = campaign_name
                continue
            if column_key == "id" and entry_type == "Encounter":
                continue
            if column_key not in field_values:
                continue
            raw_value = field_values[column_key]
            normalized = raw_value.strip() if isinstance(raw_value, str) else raw_value
            spec = spec_map.get(column_key)
            if column.primary_key and (normalized is None or normalized == ""):
                label = spec.label if spec else column_key.replace("_", " ").title()
                msg = f"{label} is required."
                raise ValueError(msg)
            should_set, converted = self._prepare_value(column, raw_value, spec)
            if should_set:
                payload[column_key] = converted
        return payload

    def _ensure_unique_name(
        self,
        session: Any,
        entry_type: str,
        model_cls: type,
        name_value: str,
    ) -> None:
        if entry_type not in {"NPC", "Location"}:
            return
        name_column = getattr(model_cls, "name", None)
        if name_column is None:
            return
        if not name_value:
            return
        existing = (
            session.query(model_cls).filter(name_column == name_value).one_or_none()
        )
        if existing is None:
            return
        msg = f"A {entry_type.lower()} named '{name_value}' already exists."
        raise DuplicateRecordError(msg)

    def _prepare_value(
        self,
        column: Any,
        raw_value: Any,
        spec: FieldSpec | None,
    ) -> tuple[bool, Any]:
        column_key = getattr(column, "key", "")
        if column_key == "gender":
            text = str(raw_value).strip().upper()
            return True, text or "UNSPECIFIED"
        if spec and spec.is_json:
            text = str(raw_value).strip()
            if not text:
                return True, {}
            try:
                return True, json.loads(text)
            except json.JSONDecodeError as exc:
                label = spec.label if spec else getattr(column, "key", "field")
                msg = f"Invalid JSON for {label}."
                raise ValueError(msg) from exc
        try:
            python_type = column.type.python_type
        except Exception:  # noqa: BLE001
            python_type = str
        if python_type is str:
            return True, raw_value
        if not isinstance(raw_value, str):
            candidate = str(raw_value).strip()
        else:
            candidate = raw_value.strip()
        if candidate == "":
            if column.nullable:
                return True, None
            label = spec.label if spec else getattr(column, "key", "value")
            msg = f"{label} cannot be empty."
            raise ValueError(msg)
        return True, self._coerce_value(column, candidate)

    def _coerce_value(self, column: Any, raw_value: str) -> Any:
        try:
            python_type = column.type.python_type
        except Exception:  # noqa: BLE001
            python_type = str
        if python_type is int:
            return int(raw_value)
        if python_type is float:
            return float(raw_value)
        if getattr(python_type, "__name__", "") == "date":
            return dtdate.fromisoformat(raw_value)
        return raw_value

    def _apply_pending_to_instance(  # noqa: PLR0913
        self,
        entry_type: str,
        model_cls: type,
        instance: Any,
        field_values: dict[str, Any],
        spec_map: dict[str, FieldSpec],
        image_payload: bytes | None,
    ) -> tuple[bool, str | None]:
        changed = False
        for field_name, raw_value in field_values.items():
            column = model_cls.__table__.columns.get(field_name)  # type: ignore[attr-defined]
            if column is None:
                continue
            should_update, converted = self._prepare_value(
                column,
                raw_value,
                spec_map.get(field_name),
            )
            if not should_update:
                continue
            setattr(instance, field_name, converted)
            changed = True
        if self._apply_image_payload(instance, image_payload):
            changed = True
        if not changed:
            return False, None
        new_identifier = self._extract_instance_identifier(entry_type, instance)
        return True, new_identifier

    @staticmethod
    def _apply_image_payload(instance: Any, image_payload: bytes | None) -> bool:
        if image_payload is None or not hasattr(instance, "image"):
            return False
        existing = getattr(instance, "image", None)
        if existing is None:
            instance.image = ImageStore(image_blob=image_payload)
        else:
            existing.image_blob = image_payload
        return True

    @staticmethod
    def _extract_instance_identifier(entry_type: str, instance: Any) -> str | None:
        if entry_type == "Encounter":
            identifier = getattr(instance, "id", None)
        else:
            identifier = getattr(instance, "name", None)
        if identifier in (None, ""):
            return None
        return str(identifier)

    @staticmethod
    def _fetch_instance(
        session: Any,
        entry_type: str,
        model_cls: type,
        identifier: str,
    ) -> Any | None:
        pk_value: Any = identifier
        if entry_type == "Encounter":
            try:
                pk_value = int(identifier)
            except ValueError:
                logger.warning("invalid encounter id '%s'", identifier)
                return None
        if entry_type in {"NPC", "Location"}:
            name_column = getattr(model_cls, "name", None)
            if name_column is None:
                return None
            return (
                session.query(model_cls).filter(name_column == identifier).one_or_none()
            )
        return session.get(model_cls, pk_value)

    @staticmethod
    def _use_partial_match(spec: FieldSpec | None) -> bool:
        if spec is None:
            return True
        return not (spec.enum_values or spec.preset_values)

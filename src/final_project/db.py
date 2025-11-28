"""Contains methods for working with the database."""

from lazi.core import lazi

# does not work well with lazi
from sqlalchemy import JSON
from sqlalchemy import Engine
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import LargeBinary
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import create_engine
from sqlalchemy import or_
from sqlalchemy.dialects.mysql import SMALLINT
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import Session as SessionType
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

with lazi:  # type: ignore[attr-defined] # lazi has incorrectly typed code
    import contextlib
    import json
    import os
    import sys
    import tomllib
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import date as dtdate
    from functools import cache
    from pathlib import Path
    from typing import Annotated
    from typing import Any
    from typing import Literal
    from typing import Protocol
    from typing import TextIO
    from typing import cast

    import structlog
    import yaml
    from beartype import beartype
    from beartype.vale import Is
    from dotenv import load_dotenv
    from pydantic import BaseModel
    from pydantic import Field

    from final_project import LogLevels
    from final_project.settings_manager import path_from_settings

    try:  # optional dependency used only proof of loading ddl
        import mysql.connector as mysql_connector
    except ImportError:
        mysql_connector = None

logger = structlog.getLogger("final_project")
SCRIPTROOT = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPTROOT / ".." / ".." / "project").resolve() / ".."

load_dotenv(PROJECT_ROOT / ".env")
CONFIG_PATH = path_from_settings("config")
SAMPLE_NPC_PATH = path_from_settings("sample_npc")
SAMPLE_LOCATION_PATH = path_from_settings(
    "sample_locations",
)
SAMPLE_ENCOUNTER_PATH = path_from_settings(
    "sample_encounters",
)
CAMPAIGN_STATUSES: tuple[str, ...] = (
    "ACTIVE",
    "ONHOLD",
    "COMPLETED",
    "CANCELED",
)


# beartype annotations
Varchar256 = Annotated[str, Is[lambda s: isinstance(s, str) and len(s) <= 256]]  # pyright: ignore[reportUnknownLambdaType] # noqa: PLR2004
SmallInt = Annotated[int, Is[lambda x: isinstance(x, int) and 0 <= x <= 65535]]  # pyright: ignore[reportUnknownLambdaType] # noqa: PLR2004
LongBlob = LargeBinary(length=(2**32) - 1)  # Max length for LONGBLOB


@beartype
def _get_env_var(name: str) -> Any:
    ret = os.getenv(name)
    if ret is None:
        msg = f"Unable to find: {name} in environmental variables."
        raise RuntimeError(msg)
    return ret


@cache
def _read_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as file:
        ret = tomllib.load(file)
    logger.debug("read config data", config=ret)
    return ret


@cache
def _load_sample_data(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        logger.error("%s file missing", label, path=str(path))
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            raw_data: Any = yaml.safe_load(file)
    except yaml.YAMLError:
        logger.exception("failed to parse %s yaml", label, path=str(path))
        return []
    if raw_data is None:
        raw_data = []
    if not isinstance(raw_data, list):
        logger.error("%s data must be a list", label, path=str(path))
        return []
    samples: list[dict[str, Any]] = []
    entries = cast(list[Any], raw_data)
    for entry in entries:
        if isinstance(entry, Mapping):
            entry = cast(Mapping[Any, Any], entry)
            samples.append({str(k): v for k, v in dict(entry).items()})
        else:
            logger.warning("skipping malformed %s entry", label, entry=entry)
    return samples


def _read_image_bytes(path: Path | None) -> bytes | None:
    if path is None:
        return None
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    try:
        return resolved.read_bytes()
    except FileNotFoundError:
        logger.warning("sample npc image not found", path=str(resolved))
        return None


def _coerce_optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    text = str(value).strip()
    if not text:
        return None
    return Path(text)


@beartype
class DBConfig(BaseModel):
    """Pydantic model of the config for a db connection."""

    drivername: str
    username: str | None
    password: str | None
    host: str | None
    port: int | None
    database: str | None
    query: Mapping[str, Sequence[str] | str] = Field(default_factory=dict)


class _Connector(Protocol):
    def __call__(self, loglevel: LogLevels = LogLevels.WARNING) -> Engine: ...


def _connector_factory() -> _Connector:
    engine: Engine | None = None

    def _connect(loglevel: LogLevels = LogLevels.WARNING) -> Engine:
        """Connect to the db, caching the engine inside a closure."""
        nonlocal engine
        if engine is not None:
            return engine
        db_config = DBConfig(
            username=_get_env_var("DB_USERNAME"),
            password=_get_env_var("DB_PASSWORD"),
            **_read_config()["DB"],
        )
        db_url = URL.create(**db_config.model_dump())

        echo = loglevel == LogLevels.DEBUG
        engine = create_engine(
            db_url,
            echo=echo,
        )  # echo=True for logging SQL statements
        try:
            with engine.connect():
                logger.info("Successfully connected to the database!")
        except Exception as e:  # noqa: BLE001
            logger.critical("Error connecting to the database", error=e)
        return engine

    return _connect


connect = _connector_factory()


@cache
def _get_session_factory() -> sessionmaker[SessionType]:
    """Return a cached session factory bound to the configured engine."""
    factory: sessionmaker[SessionType] = sessionmaker(
        bind=connect(),
        expire_on_commit=False,
    )
    return factory


def get_session() -> SessionType:
    """Create a new SQLAlchemy session using the shared factory."""
    factory = _get_session_factory()
    return factory()


class Base(DeclarativeBase):
    """SqlAlchemy base class.

    see https://docs.sqlalchemy.org/en/20/changelog/whatsnew_20.html#migrating-an-existing-mapping
    """

    pass


# --- Core Entities ---


@beartype
class Campaign(Base):
    """Represents the campaign Table."""

    __tablename__ = "campaign"
    name: Mapped[Varchar256] = mapped_column(String(256), primary_key=True)
    start_date: Mapped[dtdate] = mapped_column()
    status: Mapped[Literal["ACTIVE", "ONHOLD", "COMPLETED", "CANCELED"]] = (
        mapped_column(
            Enum(*CAMPAIGN_STATUSES, name="campaign_status"),
        )
    )

    locations = relationship(
        "Location",
        back_populates="campaign",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    encounters = relationship(
        "Encounter",
        back_populates="campaign",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    factions = relationship(
        "Faction",
        back_populates="campaign",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    npcs = relationship(
        "NPC",
        back_populates="campaign",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


@beartype
class Location(Base):
    """Represents the location table."""

    __tablename__ = "location"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[Varchar256] = mapped_column(String(256), index=True, unique=True)
    type: Mapped[Literal["DUNGEON", "WILDERNESS", "TOWN", "INTERIOR"]] = mapped_column(
        Enum("DUNGEON", "WILDERNESS", "TOWN", "INTERIOR", name="location_type"),
    )
    description: Mapped[str] = mapped_column(Text)
    image_blob: Mapped[bytes | None] = mapped_column(LongBlob, nullable=True)
    campaign_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "campaign.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
    )

    campaign = relationship("Campaign", back_populates="locations")
    encounters = relationship(
        "Encounter",
        back_populates="location",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


@beartype
class Encounter(Base):
    """Represents the encounter table."""

    __tablename__ = "encounter"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "campaign.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
    )
    location_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "location.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
    )
    date: Mapped[dtdate] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(Text)
    image_blob: Mapped[bytes | None] = mapped_column(LongBlob, nullable=True)

    campaign = relationship("Campaign", back_populates="encounters")
    location = relationship("Location", back_populates="encounters")
    participants = relationship(
        "EncounterParticipants",
        back_populates="encounter",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


@beartype
class NPC(Base):
    """Represents the NPC table."""

    __tablename__ = "npc"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[Varchar256] = mapped_column(String(256), index=True, unique=True)
    age: Mapped[SmallInt] = mapped_column(SMALLINT(unsigned=True))
    gender: Mapped[Literal["FEMALE", "MALE", "NONBINARY", "UNSPECIFIED"]] = (
        mapped_column(
            Enum(
                "FEMALE",
                "MALE",
                "NONBINARY",
                "UNSPECIFIED",
                name="gender_enum",
            ),
            nullable=False,
            default="UNSPECIFIED",
            server_default="UNSPECIFIED",
        )
    )
    alignment_name: Mapped[
        Literal[
            "LAWFUL GOOD",
            "LAWFUL NEUTRAL",
            "LAWFUL EVIL",
            "NEUTRAL GOOD",
            "TRUE NEUTRAL",
            "NEUTRAL EVIL",
            "CHAOTIC GOOD",
            "CHAOTIC NEUTRAL",
            "CHAOTIC EVIL",
        ]
    ] = mapped_column(
        Enum(
            "LAWFUL GOOD",
            "LAWFUL NEUTRAL",
            "LAWFUL EVIL",
            "NEUTRAL GOOD",
            "TRUE NEUTRAL",
            "NEUTRAL EVIL",
            "CHAOTIC GOOD",
            "CHAOTIC NEUTRAL",
            "CHAOTIC EVIL",
            name="alignment_enum",
        ),
    )
    description: Mapped[str] = mapped_column(Text)
    image_blob: Mapped[bytes | None] = mapped_column(LongBlob, nullable=True)
    species_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "species.name",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
    )
    campaign_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "campaign.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
    )
    abilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)

    campaign = relationship("Campaign", back_populates="npcs")
    species = relationship("Species", back_populates="npcs")
    factions = relationship(
        "FactionMembers",
        back_populates="npc",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    encounters = relationship(
        "EncounterParticipants",
        back_populates="npc",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relationships = relationship(
        "Relationship",
        foreign_keys="[Relationship.npc_name_1]",
        back_populates="origin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


@beartype
class Species(Base):
    """Represents the Species table."""

    __tablename__ = "species"
    name: Mapped[Varchar256] = mapped_column(String(256), primary_key=True)
    traits_json: Mapped[str] = mapped_column(Text)

    npcs = relationship("NPC", back_populates="species")


@beartype
class Faction(Base):
    """Represents the faction table."""

    __tablename__ = "faction"
    name: Mapped[Varchar256] = mapped_column(String(256), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    campaign_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "campaign.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        nullable=True,
    )

    campaign = relationship("Campaign", back_populates="factions")
    members = relationship(
        "FactionMembers",
        back_populates="faction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# --- Join Tables ---


@beartype
class FactionMembers(Base):
    """Represents join table that holds which faction has which members."""

    __tablename__ = "faction_members"
    faction_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "faction.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    npc_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "npc.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    notes: Mapped[str] = mapped_column(Text)

    faction = relationship("Faction", back_populates="members", passive_deletes=True)
    npc = relationship("NPC", back_populates="factions", passive_deletes=True)


@beartype
class EncounterParticipants(Base):
    """Represents join table that holds which encounter has which members."""

    __tablename__ = "encounter_participants"
    npc_name: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "npc.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    encounter_id: Mapped[int] = mapped_column(
        ForeignKey(
            "encounter.id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    notes: Mapped[str] = mapped_column(Text)

    npc = relationship(
        "NPC",
        back_populates="encounters",
        passive_deletes=True,
    )
    encounter = relationship(
        "Encounter",
        back_populates="participants",
        passive_deletes=True,
    )


@beartype
class Relationship(Base):
    """Represents relationships between NPCs."""

    __tablename__ = "relationship"
    npc_name_1: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "npc.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    npc_name_2: Mapped[Varchar256] = mapped_column(
        String(256),
        ForeignKey(
            "npc.name",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    name: Mapped[Varchar256] = mapped_column(String(256))

    origin = relationship(
        "NPC",
        foreign_keys=[npc_name_1],
        back_populates="relationships",
    )
    target = relationship(
        "NPC",
        foreign_keys=[npc_name_2],
        back_populates="relationships",
        passive_deletes=True,
    )


def _entry_name(entry: Mapping[str, Any]) -> str:
    return str(entry.get("name", "")).strip()


def _campaign_from_data(
    session: SessionType,
    campaign_data: Mapping[str, Any],
) -> Campaign:
    campaign_name = str(campaign_data["name"])
    campaign = session.get(Campaign, campaign_name)
    if campaign is not None:
        return campaign
    start_date = dtdate.fromisoformat(str(campaign_data["start_date"]))
    status = str(campaign_data["status"]).upper()
    campaign = Campaign(
        name=campaign_name,
        start_date=start_date,
        status=status,
    )
    session.add(campaign)
    return campaign


def _species_from_data(
    session: SessionType,
    species_data: Mapping[str, Any],
) -> Species:
    species_name = str(species_data["name"])
    species = session.get(Species, species_name)
    if species is not None:
        return species
    traits_source = species_data.get("traits", {})
    if isinstance(traits_source, str):
        traits_text = traits_source
    else:
        traits_text = json.dumps(traits_source or {}, indent=2)
    species = Species(
        name=species_name,
        traits_json=traits_text,
    )
    session.add(species)
    return species


def _location_from_data(
    session: SessionType,
    location_data: Mapping[str, Any],
    default_campaign: Campaign,
) -> Location:
    location_name = str(location_data["name"])
    location = (
        session.query(Location).filter(Location.name == location_name).one_or_none()
    )
    if location is not None:
        return location
    campaign = default_campaign
    override_campaign = location_data.get("campaign")
    if isinstance(override_campaign, Mapping):
        campaign = _campaign_from_data(
            session,
            cast(Mapping[str, Any], override_campaign),
        )
    image_path = _coerce_optional_path(location_data.get("image_path"))
    image_blob = _read_image_bytes(image_path)
    location = Location(
        name=location_name,
        type=str(location_data["type"]).upper(),
        description=str(location_data["description"]),
        image_blob=image_blob,
        campaign=campaign,
    )
    session.add(location)
    return location


def _load_all_sample_npcs(session: SessionType) -> int:
    samples = _load_sample_data(SAMPLE_NPC_PATH, "sample npc")
    created = 0
    for sample in samples:
        npc_name = _entry_name(sample)
        if not npc_name:
            continue
        exists = session.query(NPC).filter(NPC.name == npc_name).one_or_none()
        if exists is not None:
            continue
        alignment = str(sample["alignment_name"]).upper()
        abilities_source = dict(sample.get("abilities", {}))
        abilities = {str(k): v for k, v in abilities_source.items()}
        image_path = _coerce_optional_path(sample.get("image_path"))
        image_blob = _read_image_bytes(image_path)
        description = str(sample["description"])
        age = int(sample["age"])
        gender_value = (
            str(sample.get("gender", "UNSPECIFIED")).strip().upper() or "UNSPECIFIED"
        )
        campaign_data = cast(Mapping[str, Any], sample["campaign"])
        species_data = cast(Mapping[str, Any], sample["species"])
        campaign = _campaign_from_data(session, campaign_data)
        species = _species_from_data(session, species_data)
        npc = NPC(
            name=npc_name,
            age=age,
            gender=gender_value,
            alignment_name=alignment,
            description=description,
            image_blob=image_blob,
            species=species,
            campaign=campaign,
            abilities_json=abilities,
        )
        session.add(npc)
        created += 1
    return created


def _load_all_sample_locations(session: SessionType) -> int:
    samples = _load_sample_data(SAMPLE_LOCATION_PATH, "sample location")
    created = 0
    for sample in samples:
        location_name = _entry_name(sample)
        if not location_name:
            continue
        exists = (
            session.query(Location).filter(Location.name == location_name).one_or_none()
        )
        if exists is not None:
            continue
        campaign = _campaign_from_data(
            session,
            cast(Mapping[str, Any], sample["campaign"]),
        )
        _location_from_data(session, sample, campaign)
        created += 1
    return created


def _load_all_sample_encounters(session: SessionType) -> int:
    samples = _load_sample_data(SAMPLE_ENCOUNTER_PATH, "sample encounter")
    created = 0
    for sample in samples:
        description = str(sample["description"])
        date_value = dtdate.fromisoformat(str(sample["date"]))
        exists = (
            session.query(Encounter)
            .filter(Encounter.description == description)
            .filter(Encounter.date == date_value)
            .one_or_none()
        )
        if exists is not None:
            continue
        image_path = _coerce_optional_path(sample.get("image_path"))
        image_blob = _read_image_bytes(image_path)
        campaign = _campaign_from_data(
            session,
            cast(Mapping[str, Any], sample["campaign"]),
        )
        location_payload = cast(Mapping[str, Any], sample["location"])
        location = _location_from_data(session, location_payload, campaign)
        encounter = Encounter(
            campaign=campaign,
            location=location,
            date=date_value,
            description=description,
            image_blob=image_blob,
        )
        session.add(encounter)
        created += 1
    return created


def load_all_sample_data() -> dict[str, int]:
    """Load every bundled sample NPC, location, and encounter definition."""
    session = get_session()
    results = {"locations": 0, "npcs": 0, "encounters": 0}
    try:
        engine = session.get_bind() or connect()
        Base.metadata.create_all(engine)
        results["locations"] = _load_all_sample_locations(session)
        results["npcs"] = _load_all_sample_npcs(session)
        results["encounters"] = _load_all_sample_encounters(session)
    except Exception:
        session.rollback()
        raise
    else:
        session.commit()
        return results
    finally:
        session.close()


@beartype
def list_all_npcs(session: SessionType) -> None:
    """Return all NPCs currently stored in the database."""
    try:
        npcs = session.query(NPC).all()
        for npc in npcs:
            print(f"NPC: {npc.name}, Age: {npc.age}, Alignment: {npc.alignment_name}")
    finally:
        session.close()


def get_campaigns() -> list[str]:
    """Return a list of campaign names from the database."""
    session = SessionType(bind=connect())
    try:
        campaigns = session.query(Campaign).all()
        return [campaign.name for campaign in campaigns]
    finally:
        session.close()


def _get_campaign(session: SessionType, name: str) -> Campaign:
    """Return the Campaign with the given name, or raise ValueError if not found."""
    campaign = session.get(Campaign, name)
    if campaign is None:
        msg = f"Campaign '{name}' does not exist."
        raise ValueError(msg)
    return campaign


def delete_campaign(name: str) -> None:
    """Remove the campaign and all related domain data."""
    normalized = name.strip()
    if not normalized or normalized in {"No Campaigns", "New Campaign"}:
        msg = "Select a campaign before attempting to delete it."
        raise ValueError(msg)
    session = get_session()
    try:
        campaign = _get_campaign(session, normalized)
        npc_names = [
            npc_name
            for (npc_name,) in session.query(NPC.name)
            .filter(NPC.campaign_name == normalized)
            .all()
        ]
        if npc_names:
            session.query(Relationship).filter(
                or_(
                    Relationship.npc_name_1.in_(npc_names),
                    Relationship.npc_name_2.in_(npc_names),
                ),
            ).delete(synchronize_session=False)
            session.query(FactionMembers).filter(
                FactionMembers.npc_name.in_(npc_names),
            ).delete(synchronize_session=False)
        encounter_ids = [
            encounter_id
            for (encounter_id,) in session.query(Encounter.id)
            .filter(Encounter.campaign_name == normalized)
            .all()
        ]
        if encounter_ids:
            session.query(EncounterParticipants).filter(
                EncounterParticipants.encounter_id.in_(encounter_ids),
            ).delete(synchronize_session=False)
        faction_names = [
            faction_name
            for (faction_name,) in session.query(Faction.name)
            .filter(Faction.campaign_name == normalized)
            .all()
        ]
        if faction_names:
            session.query(FactionMembers).filter(
                FactionMembers.faction_name.in_(faction_names),
            ).delete(synchronize_session=False)
        session.query(Encounter).filter(
            Encounter.campaign_name == normalized,
        ).delete(synchronize_session=False)
        session.query(Location).filter(
            Location.campaign_name == normalized,
        ).delete(synchronize_session=False)
        session.query(NPC).filter(
            NPC.campaign_name == normalized,
        ).delete(synchronize_session=False)
        session.query(Faction).filter(
            Faction.campaign_name == normalized,
        ).delete(synchronize_session=False)
        session.delete(campaign)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("failed to delete campaign", campaign=normalized)
        msg = "Unable to delete the campaign. Check logs for details."
        raise RuntimeError(msg) from exc
    except ValueError:
        session.rollback()
        raise
    finally:
        session.close()


def create_campaign(
    name: str,
    start_date: dtdate | str,
    status: str,
) -> Campaign:
    """Create a new campaign with the provided metadata."""
    normalized_name = name.strip()
    if not normalized_name:
        msg = "Campaign name cannot be empty."
        raise ValueError(msg)
    if isinstance(start_date, str):
        try:
            date_value = dtdate.fromisoformat(start_date)
        except ValueError as exc:
            msg = "Campaign start date must be in YYYY-MM-DD format."
            raise ValueError(msg) from exc
    else:
        date_value = start_date
    status_value = status.strip().upper()
    if status_value not in CAMPAIGN_STATUSES:
        allowed = ", ".join(CAMPAIGN_STATUSES)
        msg = f"Campaign status must be one of: {allowed}."
        raise ValueError(msg)
    session = get_session()
    try:
        existing = session.get(Campaign, normalized_name)
        if existing is not None:
            msg = f"Campaign '{normalized_name}' already exists."
            raise ValueError(msg)
        campaign = Campaign(
            name=normalized_name,
            start_date=date_value,
            status=status_value,
        )
        session.add(campaign)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("failed to create campaign", campaign=normalized_name)
        msg = "Unable to create the campaign. Check logs for details."
        raise RuntimeError(msg) from exc
    else:
        return campaign
    finally:
        session.close()


def get_npcs(campaign: str | None = None) -> list[str]:
    """Return a list of NPC names from the database, optionally filtered by campaign."""
    session = SessionType(bind=connect())
    try:
        query = session.query(NPC)
        if campaign:
            query = query.filter(NPC.campaign_name == campaign)
        npcs = query.order_by(NPC.name).all()
        return [npc.name for npc in npcs]
    finally:
        session.close()


def get_species(campaign: str | None = None) -> list[str]:
    """Return species names, optionally restricted to a single campaign."""
    session = SessionType(bind=connect())
    try:
        if campaign:
            query = (
                session.query(Species.name)
                .join(NPC, NPC.species_name == Species.name)
                .filter(NPC.campaign_name == campaign)
                .distinct()
                .order_by(Species.name)
            )
            return [name for (name,) in query.all()]
        species_list = session.query(Species).order_by(Species.name).all()
        return [species.name for species in species_list]
    finally:
        session.close()


def get_locations(campaign: str | None = None) -> list[str]:
    """Return a list of location names, optionally filtered by campaign."""
    session = SessionType(bind=connect())
    try:
        query = session.query(Location)
        if campaign:
            query = query.filter(Location.campaign_name == campaign)
        locations = query.order_by(Location.name).all()
        return [location.name for location in locations]
    finally:
        session.close()


def core_tables_empty() -> bool:
    """Return True when the NPC, location, and encounter tables have no rows."""
    session = get_session()
    try:
        npc_missing = session.query(NPC.id).limit(1).first() is None
        location_missing = session.query(Location.id).limit(1).first() is None
        encounter_missing = session.query(Encounter.id).limit(1).first() is None
        return npc_missing and location_missing and encounter_missing
    finally:
        session.close()


def get_factions(campaign: str | None = None) -> list[str]:
    """Return faction names, optionally filtered by campaign."""
    session = SessionType(bind=connect())
    try:
        query = session.query(Faction)
        if campaign:
            query = query.filter(Faction.campaign_name == campaign)
        factions = query.order_by(Faction.name).all()
        return [faction.name for faction in factions]
    finally:
        session.close()


def get_faction_details(name: str) -> tuple[str, str] | None:
    """Return (description, campaign_name) for a faction."""
    session = SessionType(bind=connect())
    try:
        faction = session.query(Faction).filter(Faction.name == name).one_or_none()
        if faction is None:
            return None
        return faction.description, faction.campaign_name
    finally:
        session.close()


def get_faction_membership(npc_name: str) -> tuple[str, str] | None:
    """Return the first faction membership (name, notes) for the NPC."""
    session = SessionType(bind=connect())
    try:
        membership = (
            session.query(FactionMembers)
            .filter(FactionMembers.npc_name == npc_name)
            .order_by(FactionMembers.faction_name)
            .first()
        )
        if membership is None:
            return None
        return membership.faction_name, membership.notes
    finally:
        session.close()


def upsert_faction(name: str, description: str, campaign_name: str) -> None:
    """Create or update a faction definition."""
    session = get_session()
    try:
        faction = session.query(Faction).filter(Faction.name == name).one_or_none()
        if faction is None:
            faction = Faction(
                name=name,
                description=description,
                campaign_name=campaign_name,
            )
            session.add(faction)
        else:
            faction.description = description
            faction.campaign_name = campaign_name
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("failed to save faction", faction=name)
        msg = "Unable to save the faction. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def assign_faction_member(npc_name: str, faction_name: str, notes: str) -> None:
    """Assign an NPC to a faction, replacing previous memberships."""
    session = get_session()
    try:
        (
            session.query(FactionMembers)
            .filter(FactionMembers.npc_name == npc_name)
            .delete(synchronize_session=False)
        )
        member = FactionMembers(
            faction_name=faction_name,
            npc_name=npc_name,
            notes=notes,
        )
        session.add(member)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception(
            "failed to assign faction membership",
            npc=npc_name,
            faction=faction_name,
        )
        msg = "Unable to update the faction membership. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def clear_faction_membership(npc_name: str) -> None:
    """Remove any faction memberships for the specified NPC."""
    session = get_session()
    try:
        (
            session.query(FactionMembers)
            .filter(FactionMembers.npc_name == npc_name)
            .delete(synchronize_session=False)
        )
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("failed to clear faction membership", npc=npc_name)
        msg = "Unable to clear the faction membership. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def get_encounter_participants(encounter_id: int) -> list[tuple[str, str]]:
    """Return (npc_name, notes) rows for the encounter."""
    session = get_session()
    try:
        rows = (
            session.query(EncounterParticipants.npc_name, EncounterParticipants.notes)
            .filter(EncounterParticipants.encounter_id == encounter_id)
            .order_by(EncounterParticipants.npc_name)
            .all()
        )
        return [(npc, notes) for npc, notes in rows]
    except SQLAlchemyError:
        logger.exception(
            "failed to load encounter participants",
            encounter=encounter_id,
        )
        return []
    finally:
        session.close()


def upsert_encounter_participant(
    encounter_id: int,
    npc_name: str,
    notes: str,
) -> None:
    """Insert or update a participant row for the encounter."""
    session = get_session()
    try:
        encounter = session.get(Encounter, encounter_id)
        if encounter is None:
            session.rollback()
            msg = "Save the encounter before editing participants."
            raise ValueError(msg)
        npc = session.query(NPC).filter(NPC.name == npc_name).one_or_none()
        if npc is None:
            session.rollback()
            msg = "Select a valid NPC before adding them to the encounter."
            raise ValueError(msg)
        participant = (
            session.query(EncounterParticipants)
            .filter(
                EncounterParticipants.encounter_id == encounter_id,
                EncounterParticipants.npc_name == npc_name,
            )
            .one_or_none()
        )
        if participant is None:
            participant = EncounterParticipants(
                encounter_id=encounter_id,
                npc_name=npc_name,
                notes=notes,
            )
            session.add(participant)
        else:
            participant.notes = notes
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception(
            "failed to update encounter participant",
            encounter=encounter_id,
            npc=npc_name,
        )
        msg = "Unable to update encounter participants. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def delete_encounter_participant(encounter_id: int, npc_name: str) -> None:
    """Remove the NPC from the encounter participants list."""
    session = get_session()
    try:
        (
            session.query(EncounterParticipants)
            .filter(
                EncounterParticipants.encounter_id == encounter_id,
                EncounterParticipants.npc_name == npc_name,
            )
            .delete(synchronize_session=False)
        )
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception(
            "failed to delete encounter participant",
            encounter=encounter_id,
            npc=npc_name,
        )
        msg = "Unable to remove the encounter participant. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def is_text_column(column: Any) -> bool:
    """Return True when the provided SQLAlchemy column stores text."""
    return isinstance(getattr(column, "type", None), Text)


def get_relationship_rows(source_name: str) -> list[tuple[str, str]]:
    """Return pairs of (target_npc, relation_name) for the given NPC."""
    session = get_session()
    try:
        rows = (
            session.query(Relationship.npc_name_2, Relationship.name)
            .filter(Relationship.npc_name_1 == source_name)
            .order_by(Relationship.npc_name_2)
            .all()
        )
        return [(target, relation) for target, relation in rows]
    except SQLAlchemyError:
        logger.exception("failed to load relationships", npc=source_name)
        return []
    finally:
        session.close()


def save_relationship(
    source_name: str,
    target_name: str,
    relation_name: str,
) -> None:
    """Create or update an NPC relationship."""
    if source_name == target_name:
        msg = "Select a different NPC for the relationship."
        raise ValueError(msg)
    session = get_session()
    try:
        source = session.query(NPC).filter(NPC.name == source_name).one_or_none()
        if source is None:
            msg = "Save the NPC before adding relationships."
            raise ValueError(msg)
        target = session.query(NPC).filter(NPC.name == target_name).one_or_none()
        if target is None:
            msg = "Select a valid related NPC."
            raise ValueError(msg)
        relation = (
            session.query(Relationship)
            .filter(
                Relationship.npc_name_1 == source_name,
                Relationship.npc_name_2 == target_name,
            )
            .one_or_none()
        )
        if relation is None:
            relation = Relationship(
                npc_name_1=source_name,
                npc_name_2=target_name,
                name=relation_name,
            )
            session.add(relation)
        else:
            relation.name = relation_name
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("failed to save relationship", npc=source_name)
        msg = "Unable to save the relationship. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def delete_relationship(source_name: str, target_name: str) -> None:
    """Remove a relationship between two NPCs if it exists."""
    session = get_session()
    try:
        relation = (
            session.query(Relationship)
            .filter(
                Relationship.npc_name_1 == source_name,
                Relationship.npc_name_2 == target_name,
            )
            .one_or_none()
        )
        if relation is None:
            return
        session.delete(relation)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("failed to delete relationship", npc=source_name)
        msg = "Unable to delete the relationship. Check logs for details."
        raise RuntimeError(msg) from exc
    finally:
        session.close()


def get_types() -> list[str]:
    """Return a list of types."""
    return ["NPC", "Location", "Encounter"]


def setup_database(
    *,
    rebuild: bool = False,
    loglevel: LogLevels = LogLevels.INFO,
) -> sessionmaker[SessionType]:
    """Ensure schema exists (optionally rebuilding) and return a session factory."""
    engine = connect(loglevel)
    logger.debug("Create tables if missing.")
    if rebuild:
        logger.info("Dropping all tables and rebuilding schema.")
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def apply_external_schema_with_connector(
    *,
    path: Path | None = None,
) -> None:
    """Use mysql-connector-python to execute db.ddl in one pass."""
    ddl_path = path or (PROJECT_ROOT / "data" / "db.ddl")
    if not ddl_path.exists():
        logger.warning("Cannot load DDL; file missing", path=str(ddl_path))
        return
    ddl_sql = ddl_path.read_text(encoding="utf-8").strip()
    if not ddl_sql:
        logger.info("DDL file is empty; skipping load", path=str(ddl_path))
        return
    if mysql_connector is None:
        logger.warning(
            "mysql-connector-python is not installed; skipping DDL load",
            path=str(ddl_path),
        )
        return
    config = _read_config().get("DB", {})
    try:
        connection = mysql_connector.connect(  # type: ignore[union-attr]
            user=_get_env_var("DB_USERNAME"),
            password=_get_env_var("DB_PASSWORD"),
            host=config.get("host"),
            port=config.get("port"),
            database=config.get("database"),
        )
    except Exception:
        logger.exception("Failed to load DDL via mysql-connector", path=str(ddl_path))
        return

    with contextlib.closing(connection) as managed_connection:
        try:
            with managed_connection.cursor() as cursor:
                cursor.execute(ddl_sql)
                for _, result_set in cursor.fetchsets():
                    logger.debug("sql statement", results=result_set)
            managed_connection.commit()
            logger.info("Applied DDL via mysql-connector", path=str(ddl_path))
        except Exception:
            with contextlib.suppress(Exception):
                managed_connection.rollback()
            logger.exception(
                "Failed to load DDL via mysql-connector",
                path=str(ddl_path),
            )


def export_database_ddl(stream: TextIO | None = None) -> None:
    """Write CREATE TABLE/INDEX statements for the schema to a stream."""
    target = stream or sys.stdout
    engine = connect()
    statements: list[str] = []
    try:
        dialect = engine.dialect
        for table in Base.metadata.sorted_tables:
            statements.append(str(CreateTable(table).compile(dialect=dialect)))
            index_statements = [
                str(CreateIndex(index).compile(dialect=dialect))
                for index in table.indexes
            ]
            statements.extend(index_statements)
    finally:
        engine.dispose()
    if not statements:
        target.write("-- No tables defined.\n")
        return
    output = ";\n\n".join(statements) + ";\n"
    target.write(output)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage the RPG NPC database.",
    )
    parser.add_argument(
        "--export_ddl",
        action="store_true",
        help="Exports the database DDL to stdout.",
    )
    args = parser.parse_args()

    if args.export_ddl:
        export_database_ddl()
    else:
        parser.print_help()

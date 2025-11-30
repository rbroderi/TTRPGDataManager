"""Database integrity and cascade regression tests."""

from __future__ import annotations

from datetime import date as dtdate
from secrets import token_hex
from typing import Any

from sqlalchemy.orm import Session

from final_project.db import NPC
from final_project.db import Campaign
from final_project.db import Encounter
from final_project.db import EncounterParticipants
from final_project.db import Faction
from final_project.db import FactionMembers
from final_project.db import Location
from final_project.db import Relationship
from final_project.db import Species


def _unique(label: str, suffix: str) -> str:
    return f"{label}::{suffix}"


def _snapshot_counts(session: Session) -> dict[str, int]:
    return {
        "campaign": session.query(Campaign).count(),
        "location": session.query(Location).count(),
        "encounter": session.query(Encounter).count(),
        "npc": session.query(NPC).count(),
        "faction": session.query(Faction).count(),
        "faction_members": session.query(FactionMembers).count(),
        "encounter_participants": session.query(EncounterParticipants).count(),
        "relationship": session.query(Relationship).count(),
        "species": session.query(Species).count(),
    }


def _seed_graph(session: Session) -> dict[str, Any]:
    """Create a campaign graph with related data for cascade tests."""
    suffix = token_hex(8)
    species = Species(name=_unique("High Elf", suffix), traits_json="{}")
    campaign = Campaign(
        name=_unique("Verdant Dawn", suffix),
        start_date=dtdate(2024, 1, 1),
        status="ACTIVE",
    )
    location = Location(
        name=_unique("Greenway", suffix),
        type="TOWN",
        description=f"Border outpost ({suffix})",
        campaign=campaign,
    )
    encounter = Encounter(
        campaign=campaign,
        location=location,
        date=dtdate(2024, 2, 1),
        description=f"Ambush on the trail ({suffix})",
    )
    primary_npc = NPC(
        name=_unique("Lysa Grey", suffix),
        age=28,
        gender="UNSPECIFIED",
        alignment_name="TRUE NEUTRAL",
        description="Scout captain",
        species=species,
        campaign=campaign,
        abilities_json={"dex": 16},
    )
    secondary_npc = NPC(
        name=_unique("Thorn Bright", suffix),
        age=32,
        gender="UNSPECIFIED",
        alignment_name="TRUE NEUTRAL",
        description="Quartermaster",
        species=species,
        campaign=campaign,
        abilities_json={"int": 14},
    )
    faction = Faction(
        name=_unique("Emerald Wardens", suffix),
        description="Frontier guard",
        campaign=campaign,
    )
    membership = FactionMembers(
        faction=faction,
        npc=primary_npc,
        notes="Command liaison",
    )
    participant = EncounterParticipants(
        encounter=encounter,
        npc=primary_npc,
        notes="Led patrol",
    )
    relationship = Relationship(
        origin=primary_npc,
        target=secondary_npc,
        name="Trusted Ally",
    )
    session.add_all(
        [
            species,
            campaign,
            location,
            encounter,
            primary_npc,
            secondary_npc,
            faction,
            membership,
            participant,
            relationship,
        ],
    )
    session.commit()
    return {
        "campaign": campaign,
        "primary_npc": primary_npc,
        "secondary_npc": secondary_npc,
        "species": species,
    }


def test_delete_campaign_cascades_children(db_session: Session) -> None:
    """Deleting a campaign removes dependent rows but preserves shared species."""
    baseline = _snapshot_counts(db_session)
    records = _seed_graph(db_session)
    db_session.delete(records["campaign"])
    db_session.commit()

    after = _snapshot_counts(db_session)
    assert after["campaign"] == baseline["campaign"]
    assert after["location"] == baseline["location"]
    assert after["encounter"] == baseline["encounter"]
    assert after["npc"] == baseline["npc"]
    assert after["faction"] == baseline["faction"]
    assert after["faction_members"] == baseline["faction_members"]
    assert after["encounter_participants"] == baseline["encounter_participants"]
    assert after["relationship"] == baseline["relationship"]
    assert after["species"] == baseline["species"] + 1


def test_delete_npc_cleans_memberships(db_session: Session) -> None:
    """Deleting an NPC clears memberships but leaves other campaign rows."""
    baseline = _snapshot_counts(db_session)
    records = _seed_graph(db_session)
    db_session.delete(records["primary_npc"])
    db_session.commit()

    assert (
        db_session.query(NPC)
        .filter(NPC.name == records["primary_npc"].name)
        .one_or_none()
        is None
    )
    assert (
        db_session.query(NPC)
        .filter(NPC.name == records["secondary_npc"].name)
        .one_or_none()
        is not None
    )
    after = _snapshot_counts(db_session)
    assert after["faction_members"] == baseline["faction_members"]
    assert after["encounter_participants"] == baseline["encounter_participants"]
    assert after["relationship"] == baseline["relationship"]
    assert after["npc"] == baseline["npc"] + 1
    assert after["faction"] == baseline["faction"] + 1
    assert after["encounter"] == baseline["encounter"] + 1
    assert after["location"] == baseline["location"] + 1
    assert after["campaign"] == baseline["campaign"] + 1
    assert after["species"] == baseline["species"] + 1

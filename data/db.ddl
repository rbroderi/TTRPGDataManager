CREATE DATABASE IF NOT EXISTS final_project
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE final_project;

CREATE TABLE IF NOT EXISTS campaign (
    name VARCHAR(256) NOT NULL,
    start_date DATE NOT NULL,
    status ENUM('ACTIVE', 'ONHOLD', 'COMPLETED', 'CANCELED') NOT NULL,
    PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS species (
    name VARCHAR(256) NOT NULL,
    traits_json TEXT NOT NULL,
    PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS faction (
    name VARCHAR(256) NOT NULL,
    description TEXT,
    campaign_name VARCHAR(256),
    PRIMARY KEY (name),
    KEY ix_faction_campaign (campaign_name),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS location (
    id INTEGER NOT NULL AUTO_INCREMENT,
    name VARCHAR(256) NOT NULL,
    type ENUM('DUNGEON', 'WILDERNESS', 'TOWN', 'INTERIOR') NOT NULL,
    description TEXT NOT NULL,
    campaign_name VARCHAR(256) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY ix_location_name (name),
    KEY ix_location_campaign (campaign_name),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS npc (
    id INTEGER NOT NULL AUTO_INCREMENT,
    name VARCHAR(256) NOT NULL,
    age SMALLINT UNSIGNED NOT NULL,
    gender ENUM('FEMALE', 'MALE', 'NONBINARY', 'UNSPECIFIED') NOT NULL DEFAULT 'UNSPECIFIED',
    alignment_name ENUM('LAWFUL GOOD', 'LAWFUL NEUTRAL', 'LAWFUL EVIL', 'NEUTRAL GOOD', 'TRUE NEUTRAL', 'NEUTRAL EVIL', 'CHAOTIC GOOD', 'CHAOTIC NEUTRAL', 'CHAOTIC EVIL') NOT NULL,
    description TEXT NOT NULL,
    species_name VARCHAR(256) NOT NULL,
    campaign_name VARCHAR(256) NOT NULL,
    abilities_json JSON,
    PRIMARY KEY (id),
    UNIQUE KEY ix_npc_name (name),
    KEY ix_npc_campaign (campaign_name),
    FOREIGN KEY (species_name) REFERENCES species (name)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS encounter (
    id INTEGER NOT NULL AUTO_INCREMENT,
    campaign_name VARCHAR(256) NOT NULL,
    location_name VARCHAR(256) NOT NULL,
    date DATE,
    description TEXT NOT NULL,
    PRIMARY KEY (id),
    KEY ix_encounter_campaign (campaign_name),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (location_name) REFERENCES location (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS image_store (
    id INTEGER NOT NULL AUTO_INCREMENT,
    image_blob BLOB(4294967295) NOT NULL,
    npc_id INTEGER,
    location_id INTEGER,
    encounter_id INTEGER,
    PRIMARY KEY (id),
    UNIQUE KEY uq_image_store_npc (npc_id),
    UNIQUE KEY uq_image_store_location (location_id),
    UNIQUE KEY uq_image_store_encounter (encounter_id),
    FOREIGN KEY (npc_id) REFERENCES npc (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES location (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (encounter_id) REFERENCES encounter (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS faction_members (
    faction_name VARCHAR(256) NOT NULL,
    npc_name VARCHAR(256) NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (faction_name, npc_name),
    UNIQUE KEY uq_faction_members_npc (npc_name),
    FOREIGN KEY (faction_name) REFERENCES faction (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (npc_name) REFERENCES npc (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationship (
    npc_name_1 VARCHAR(256) NOT NULL,
    npc_name_2 VARCHAR(256) NOT NULL,
    name VARCHAR(256) NOT NULL,
    PRIMARY KEY (npc_name_1, npc_name_2),
    FOREIGN KEY (npc_name_1) REFERENCES npc (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (npc_name_2) REFERENCES npc (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS encounter_participants (
    npc_name VARCHAR(256) NOT NULL,
    encounter_id INTEGER NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (npc_name, encounter_id),
    KEY ix_encounter_participants_encounter (encounter_id),
    FOREIGN KEY (npc_name) REFERENCES npc (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (encounter_id) REFERENCES encounter (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

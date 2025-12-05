CREATE DATABASE IF NOT EXISTS ttrpgdataman
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE ttrpgdataman;

CREATE TABLE IF NOT EXISTS campaign (
    name VARCHAR(256) NOT NULL,
    start_date DATE NOT NULL,
    status ENUM('ACTIVE', 'ONHOLD', 'COMPLETED', 'CANCELED') NOT NULL,
    PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS campaign_record (
    id INTEGER NOT NULL AUTO_INCREMENT,
    campaign_name VARCHAR(256) NOT NULL,
    record_type VARCHAR(50) NOT NULL,
    PRIMARY KEY (id),
    KEY ix_campaign_record_campaign (campaign_name),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
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
    id INTEGER NOT NULL,
    campaign_name VARCHAR(256) NOT NULL,
    name VARCHAR(256) NOT NULL,
    type ENUM('DUNGEON', 'WILDERNESS', 'TOWN', 'INTERIOR') NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_location_campaign_name (campaign_name, name),
    FOREIGN KEY (id) REFERENCES campaign_record (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS npc (
    id INTEGER NOT NULL,
    campaign_name VARCHAR(256) NOT NULL,
    name VARCHAR(256) NOT NULL,
    age SMALLINT UNSIGNED NOT NULL,
    gender ENUM('FEMALE', 'MALE', 'NONBINARY', 'UNSPECIFIED') NOT NULL DEFAULT 'UNSPECIFIED',
    alignment_name ENUM('LAWFUL GOOD', 'LAWFUL NEUTRAL', 'LAWFUL EVIL', 'NEUTRAL GOOD', 'TRUE NEUTRAL', 'NEUTRAL EVIL', 'CHAOTIC GOOD', 'CHAOTIC NEUTRAL', 'CHAOTIC EVIL') NOT NULL,
    description TEXT NOT NULL,
    species_name VARCHAR(256) NOT NULL,
    abilities_json JSON,
    PRIMARY KEY (id),
    UNIQUE KEY uq_npc_campaign_name (campaign_name, name),
    FOREIGN KEY (species_name) REFERENCES species (name)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (id) REFERENCES campaign_record (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT chk_npc_age CHECK (age < 10000)
);

CREATE TABLE IF NOT EXISTS encounter (
    id INTEGER NOT NULL,
    campaign_name VARCHAR(256) NOT NULL,
    location_name VARCHAR(256) NOT NULL,
    date DATE,
    description TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_encounter_campaign_location_date (campaign_name, location_name, date),
    FOREIGN KEY (id) REFERENCES campaign_record (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (campaign_name, location_name) REFERENCES location (campaign_name, name)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS image_store (
    campaign_record_id INTEGER NOT NULL,
    image_blob LONGBLOB NOT NULL,
    PRIMARY KEY (campaign_record_id),
    FOREIGN KEY (campaign_record_id) REFERENCES campaign_record (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS faction_members (
    faction_name VARCHAR(256) NOT NULL,
    npc_id INTEGER NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (faction_name, npc_id),
    UNIQUE KEY uq_faction_members_npc (npc_id),
    FOREIGN KEY (faction_name) REFERENCES faction (name)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (npc_id) REFERENCES npc (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationship (
    npc_id_1 INTEGER NOT NULL,
    npc_id_2 INTEGER NOT NULL,
    name VARCHAR(256) NOT NULL,
    PRIMARY KEY (npc_id_1, npc_id_2),
    FOREIGN KEY (npc_id_1) REFERENCES npc (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (npc_id_2) REFERENCES npc (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS encounter_participants (
    npc_id INTEGER NOT NULL,
    encounter_id INTEGER NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (npc_id, encounter_id),
    KEY ix_encounter_participants_encounter (encounter_id),
    FOREIGN KEY (npc_id) REFERENCES npc (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (encounter_id) REFERENCES encounter (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

DELIMITER $$

DROP TRIGGER IF EXISTS trg_location_campaign_name_bi $$
CREATE TRIGGER trg_location_campaign_name_bi
BEFORE INSERT ON location
FOR EACH ROW
BEGIN
    DECLARE parent_campaign VARCHAR(256);
    SELECT campaign_name INTO parent_campaign FROM campaign_record WHERE id = NEW.id;
    SET NEW.campaign_name = parent_campaign;
END $$

DROP TRIGGER IF EXISTS trg_location_campaign_name_bu $$
CREATE TRIGGER trg_location_campaign_name_bu
BEFORE UPDATE ON location
FOR EACH ROW
BEGIN
    DECLARE parent_campaign VARCHAR(256);
    SELECT campaign_name INTO parent_campaign FROM campaign_record WHERE id = NEW.id;
    SET NEW.campaign_name = parent_campaign;
END $$

DROP TRIGGER IF EXISTS trg_npc_campaign_name_bi $$
CREATE TRIGGER trg_npc_campaign_name_bi
BEFORE INSERT ON npc
FOR EACH ROW
BEGIN
    DECLARE parent_campaign VARCHAR(256);
    SELECT campaign_name INTO parent_campaign FROM campaign_record WHERE id = NEW.id;
    SET NEW.campaign_name = parent_campaign;
END $$

DROP TRIGGER IF EXISTS trg_npc_campaign_name_bu $$
CREATE TRIGGER trg_npc_campaign_name_bu
BEFORE UPDATE ON npc
FOR EACH ROW
BEGIN
    DECLARE parent_campaign VARCHAR(256);
    SELECT campaign_name INTO parent_campaign FROM campaign_record WHERE id = NEW.id;
    SET NEW.campaign_name = parent_campaign;
END $$

DROP TRIGGER IF EXISTS trg_encounter_campaign_name_bi $$
CREATE TRIGGER trg_encounter_campaign_name_bi
BEFORE INSERT ON encounter
FOR EACH ROW
BEGIN
    DECLARE parent_campaign VARCHAR(256);
    SELECT campaign_name INTO parent_campaign FROM campaign_record WHERE id = NEW.id;
    SET NEW.campaign_name = parent_campaign;
END $$

DROP TRIGGER IF EXISTS trg_encounter_campaign_name_bu $$
CREATE TRIGGER trg_encounter_campaign_name_bu
BEFORE UPDATE ON encounter
FOR EACH ROW
BEGIN
    DECLARE parent_campaign VARCHAR(256);
    SELECT campaign_name INTO parent_campaign FROM campaign_record WHERE id = NEW.id;
    SET NEW.campaign_name = parent_campaign;
END $$

DROP TRIGGER IF EXISTS trg_relationship_distinct_ids_bi $$
CREATE TRIGGER trg_relationship_distinct_ids_bi
BEFORE INSERT ON relationship
FOR EACH ROW
BEGIN
    IF NEW.npc_id_1 = NEW.npc_id_2 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'npc_id_1 and npc_id_2 must differ';
    END IF;
END $$

DROP TRIGGER IF EXISTS trg_relationship_distinct_ids_bu $$
CREATE TRIGGER trg_relationship_distinct_ids_bu
BEFORE UPDATE ON relationship
FOR EACH ROW
BEGIN
    IF NEW.npc_id_1 = NEW.npc_id_2 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'npc_id_1 and npc_id_2 must differ';
    END IF;
END $$

DELIMITER ;

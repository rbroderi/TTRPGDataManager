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
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
);

CREATE TABLE IF NOT EXISTS location (
    id INTEGER NOT NULL AUTO_INCREMENT,
    name VARCHAR(256) NOT NULL,
    type ENUM('DUNGEON', 'WILDERNESS', 'TOWN', 'INTERIOR') NOT NULL,
    description TEXT NOT NULL,
    image_blob BLOB(4294967295),
    campaign_name VARCHAR(256) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY ix_location_name (name),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
);

CREATE TABLE IF NOT EXISTS npc (
    id INTEGER NOT NULL AUTO_INCREMENT,
    name VARCHAR(256) NOT NULL,
    age SMALLINT UNSIGNED NOT NULL,
    gender ENUM('FEMALE', 'MALE', 'NONBINARY', 'UNSPECIFIED') NOT NULL DEFAULT 'UNSPECIFIED',
    alignment_name ENUM('LAWFUL GOOD', 'LAWFUL NEUTRAL', 'LAWFUL EVIL', 'NEUTRAL GOOD', 'TRUE NEUTRAL', 'NEUTRAL EVIL', 'CHAOTIC GOOD', 'CHAOTIC NEUTRAL', 'CHAOTIC EVIL') NOT NULL,
    description TEXT NOT NULL,
    image_blob BLOB(4294967295),
    species_name VARCHAR(256) NOT NULL,
    campaign_name VARCHAR(256) NOT NULL,
    abilities_json JSON,
    PRIMARY KEY (id),
    UNIQUE KEY ix_npc_name (name),
    FOREIGN KEY (species_name) REFERENCES species (name),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name)
);

CREATE TABLE IF NOT EXISTS encounter (
    id INTEGER NOT NULL AUTO_INCREMENT,
    campaign_name VARCHAR(256) NOT NULL,
    location_name VARCHAR(256) NOT NULL,
    date DATE,
    description TEXT NOT NULL,
    image_blob BLOB(4294967295),
    PRIMARY KEY (id),
    FOREIGN KEY (campaign_name) REFERENCES campaign (name),
    FOREIGN KEY (location_name) REFERENCES location (name)
);

CREATE TABLE IF NOT EXISTS faction_members (
    faction_name VARCHAR(256) NOT NULL,
    npc_name VARCHAR(256) NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (faction_name, npc_name),
    FOREIGN KEY (faction_name) REFERENCES faction (name),
    FOREIGN KEY (npc_name) REFERENCES npc (name)
);

CREATE TABLE IF NOT EXISTS relationship (
    npc_name_1 VARCHAR(256) NOT NULL,
    npc_name_2 VARCHAR(256) NOT NULL,
    name VARCHAR(256) NOT NULL,
    PRIMARY KEY (npc_name_1, npc_name_2),
    FOREIGN KEY (npc_name_1) REFERENCES npc (name),
    FOREIGN KEY (npc_name_2) REFERENCES npc (name)
);

CREATE TABLE IF NOT EXISTS encounter_participants (
    npc_name VARCHAR(256) NOT NULL,
    encounter_id INTEGER NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (npc_name, encounter_id),
    FOREIGN KEY (npc_name) REFERENCES npc (name),
    FOREIGN KEY (encounter_id) REFERENCES encounter (id)
);

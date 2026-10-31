-- Schéma relationnel du dossier clinique.
-- Produit par l'ETL FHIR R4. Les faits chargés et le journal sont immuables :
-- les triggers interdisent UPDATE et DELETE. Les insertions restent autorisées.
--
-- Appliquer sur une base SQLite vide :
--   sqlite3 data/hospital.db < sql/schema.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    family_name TEXT,
    given_name TEXT,
    birth_date TEXT,
    gender TEXT,
    source TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    ingested_at TEXT,
    CHECK (source IN ('fhir', 'api')),
    CHECK (gender IS NULL OR gender IN ('male', 'female', 'other', 'unknown'))
);

CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    status TEXT,
    class_code TEXT,
    class_system TEXT,
    class_display TEXT,
    type_code TEXT,
    type_system TEXT,
    type_display TEXT,
    reason_code TEXT,
    reason_system TEXT,
    reason_display TEXT,
    period_start TEXT,
    period_end TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    CHECK (source = 'fhir')
);

CREATE TABLE IF NOT EXISTS conditions (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    encounter_id TEXT REFERENCES encounters (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    clinical_status TEXT,
    code TEXT,
    code_system TEXT,
    code_display TEXT,
    onset_at TEXT,
    recorded_at TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    CHECK (source = 'fhir')
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    encounter_id TEXT REFERENCES encounters (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    parent_observation_id TEXT REFERENCES observations (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    status TEXT,
    code TEXT,
    code_system TEXT,
    code_display TEXT,
    value_numeric REAL,
    value_unit TEXT,
    value_text TEXT,
    value_code TEXT,
    value_code_system TEXT,
    effective_at TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    CHECK (source = 'fhir')
);

CREATE TABLE IF NOT EXISTS medications (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    encounter_id TEXT REFERENCES encounters (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    status TEXT,
    intent TEXT,
    code TEXT,
    code_system TEXT,
    code_display TEXT,
    dosage_text TEXT,
    recorded_at TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    CHECK (source = 'fhir')
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    reference_type TEXT NOT NULL,
    encounter_id TEXT REFERENCES encounters (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    condition_id TEXT REFERENCES conditions (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    observation_id TEXT REFERENCES observations (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    medication_id TEXT REFERENCES medications (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    body TEXT NOT NULL,
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (author_role = 'clinician'),
    CHECK (
        (
            reference_type = 'patient'
            AND encounter_id IS NULL
            AND condition_id IS NULL
            AND observation_id IS NULL
            AND medication_id IS NULL
        )
        OR (
            reference_type = 'encounter'
            AND encounter_id IS NOT NULL
            AND condition_id IS NULL
            AND observation_id IS NULL
            AND medication_id IS NULL
        )
        OR (
            reference_type = 'condition'
            AND encounter_id IS NULL
            AND condition_id IS NOT NULL
            AND observation_id IS NULL
            AND medication_id IS NULL
        )
        OR (
            reference_type = 'observation'
            AND encounter_id IS NULL
            AND condition_id IS NULL
            AND observation_id IS NOT NULL
            AND medication_id IS NULL
        )
        OR (
            reference_type = 'medication'
            AND encounter_id IS NULL
            AND condition_id IS NULL
            AND observation_id IS NULL
            AND medication_id IS NOT NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    patient_id TEXT,
    status TEXT NOT NULL,
    inserted_counts TEXT NOT NULL,
    skipped_count INTEGER NOT NULL,
    message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    CHECK (status IN ('success', 'failed'))
);

CREATE INDEX IF NOT EXISTS ix_encounters_patient ON encounters (patient_id);
CREATE INDEX IF NOT EXISTS ix_conditions_patient ON conditions (patient_id);
CREATE INDEX IF NOT EXISTS ix_conditions_encounter ON conditions (encounter_id);
CREATE INDEX IF NOT EXISTS ix_observations_patient_code ON observations (patient_id, code);
CREATE INDEX IF NOT EXISTS ix_observations_encounter ON observations (encounter_id);
CREATE INDEX IF NOT EXISTS ix_observations_parent ON observations (parent_observation_id);
CREATE INDEX IF NOT EXISTS ix_medications_patient ON medications (patient_id);
CREATE INDEX IF NOT EXISTS ix_comments_patient_created ON comments (patient_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_sha ON ingestion_runs (content_sha256);

CREATE TRIGGER IF NOT EXISTS trg_patients_no_update
BEFORE UPDATE ON patients
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table patients est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_patients_no_delete
BEFORE DELETE ON patients
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table patients est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_encounters_no_update
BEFORE UPDATE ON encounters
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table encounters est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_encounters_no_delete
BEFORE DELETE ON encounters
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table encounters est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_conditions_no_update
BEFORE UPDATE ON conditions
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table conditions est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_conditions_no_delete
BEFORE DELETE ON conditions
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table conditions est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_observations_no_update
BEFORE UPDATE ON observations
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table observations est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_observations_no_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table observations est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_medications_no_update
BEFORE UPDATE ON medications
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table medications est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_medications_no_delete
BEFORE DELETE ON medications
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table medications est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_comments_no_update
BEFORE UPDATE ON comments
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table comments est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_comments_no_delete
BEFORE DELETE ON comments
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table comments est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_ingestion_runs_no_update
BEFORE UPDATE ON ingestion_runs
BEGIN
    SELECT RAISE(ABORT, 'Modification interdite. La table ingestion_runs est immuable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_ingestion_runs_no_delete
BEFORE DELETE ON ingestion_runs
BEGIN
    SELECT RAISE(ABORT, 'Suppression interdite. La table ingestion_runs est immuable.');
END;

"""Chargement idempotent : une clé FHIR déjà présente n'est jamais réécrite."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.clock import utc_now_iso
from app.models import (
    Condition,
    Encounter,
    IngestionRun,
    Medication,
    Observation,
    Patient,
)
from app.errors import FlattenError
from etl.flatten import FlatBundle, flatten_bundle

EMPTY_COUNTS = {
    "patients": 0,
    "encounters": 0,
    "conditions": 0,
    "observations": 0,
    "medications": 0,
}


@dataclass
class IngestResult:
    source_file: str
    status: str
    patient_id: str | None
    content_sha256: str
    inserted: dict[str, int]
    skipped: int
    message: str | None


def load_file(session: Session, path: Path) -> IngestResult:
    """Charge un bundle. Les lignes existantes restent intactes. Le journal est ajouté."""
    started = utc_now_iso()
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        flat = flatten_bundle_payload(payload)
        inserted, skipped, warnings = persist(session, flat, utc_now_iso())
        session.add(
            IngestionRun(
                source_file=path.name,
                content_sha256=digest,
                patient_id=flat.patient.id,
                status="success",
                inserted_counts=json.dumps(inserted, sort_keys=True),
                skipped_count=skipped,
                message=_message(warnings, inserted),
                started_at=started,
                finished_at=utc_now_iso(),
            )
        )
        session.commit()
        return IngestResult(
            source_file=path.name,
            status="success",
            patient_id=flat.patient.id,
            content_sha256=digest,
            inserted=inserted,
            skipped=skipped,
            message=_message(warnings, inserted),
        )
    except Exception as exc:
        session.rollback()
        message = f"{type(exc).__name__}: {exc}"[:1000]
        try:
            session.add(
                IngestionRun(
                    source_file=path.name,
                    content_sha256=digest,
                    patient_id=None,
                    status="failed",
                    inserted_counts=json.dumps(EMPTY_COUNTS, sort_keys=True),
                    skipped_count=0,
                    message=message,
                    started_at=started,
                    finished_at=utc_now_iso(),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        return IngestResult(
            source_file=path.name,
            status="failed",
            patient_id=None,
            content_sha256=digest,
            inserted=dict(EMPTY_COUNTS),
            skipped=0,
            message=message,
        )


def flatten_bundle_payload(payload: object) -> FlatBundle:
    if not isinstance(payload, dict):
        raise FlattenError("Le document racine doit être un objet JSON.")
    return flatten_bundle(payload)


def persist(session: Session, flat: FlatBundle, ingested_at: str) -> tuple[dict[str, int], int, list[str]]:
    inserted = dict(EMPTY_COUNTS)
    skipped = flat.skipped
    warnings = list(flat.warnings)
    patient = flat.patient

    if session.get(Patient, patient.id) is None:
        session.add(
            Patient(
                id=patient.id,
                family_name=patient.family_name,
                given_name=patient.given_name,
                birth_date=patient.birth_date,
                gender=patient.gender,
                source="fhir",
                created_by=None,
                created_at=ingested_at,
                ingested_at=ingested_at,
            )
        )
        inserted["patients"] = 1
    else:
        skipped += 1
    session.flush()

    for encounter in flat.encounters:
        if session.get(Encounter, encounter.id) is not None:
            skipped += 1
            continue
        session.add(
            Encounter(
                id=encounter.id,
                patient_id=patient.id,
                status=encounter.status,
                class_code=encounter.class_code,
                class_system=encounter.class_system,
                class_display=encounter.class_display,
                type_code=encounter.type_code,
                type_system=encounter.type_system,
                type_display=encounter.type_display,
                reason_code=encounter.reason_code,
                reason_system=encounter.reason_system,
                reason_display=encounter.reason_display,
                period_start=encounter.period_start,
                period_end=encounter.period_end,
                source="fhir",
                ingested_at=ingested_at,
            )
        )
        inserted["encounters"] += 1
    session.flush()

    for condition in flat.conditions:
        if session.get(Condition, condition.id) is not None:
            skipped += 1
            continue
        session.add(
            Condition(
                id=condition.id,
                patient_id=patient.id,
                encounter_id=_encounter_fk(session, patient.id, condition.encounter_id, warnings),
                clinical_status=condition.clinical_status,
                code=condition.code,
                code_system=condition.code_system,
                code_display=condition.code_display,
                onset_at=condition.onset_at,
                recorded_at=condition.recorded_at,
                source="fhir",
                ingested_at=ingested_at,
            )
        )
        inserted["conditions"] += 1

    for medication in flat.medications:
        if session.get(Medication, medication.id) is not None:
            skipped += 1
            continue
        session.add(
            Medication(
                id=medication.id,
                patient_id=patient.id,
                encounter_id=_encounter_fk(session, patient.id, medication.encounter_id, warnings),
                status=medication.status,
                intent=medication.intent,
                code=medication.code,
                code_system=medication.code_system,
                code_display=medication.code_display,
                dosage_text=medication.dosage_text,
                recorded_at=medication.recorded_at,
                source="fhir",
                ingested_at=ingested_at,
            )
        )
        inserted["medications"] += 1

    roots = [row for row in flat.observations if row.parent_observation_id is None]
    children = [row for row in flat.observations if row.parent_observation_id is not None]
    root_inserted, root_skipped = _insert_observations(
        session, patient.id, roots, warnings, ingested_at
    )
    inserted["observations"] += root_inserted
    skipped += root_skipped
    session.flush()
    child_inserted, child_skipped = _insert_observations(
        session, patient.id, children, warnings, ingested_at, require_parent=True
    )
    inserted["observations"] += child_inserted
    skipped += child_skipped
    session.flush()
    return inserted, skipped, warnings


def _insert_observations(
    session: Session,
    patient_id: str,
    rows: list,
    warnings: list[str],
    ingested_at: str,
    require_parent: bool = False,
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for row in rows:
        if session.get(Observation, row.id) is not None:
            skipped += 1
            continue
        parent_id = row.parent_observation_id
        if require_parent:
            parent = session.get(Observation, parent_id) if parent_id else None
            if parent is None or parent.patient_id != patient_id:
                warnings.append(f"Observation/{row.id} ignorée : panneau parent introuvable.")
                skipped += 1
                continue
        session.add(
            Observation(
                id=row.id,
                patient_id=patient_id,
                encounter_id=_encounter_fk(session, patient_id, row.encounter_id, warnings),
                parent_observation_id=parent_id,
                status=row.status,
                code=row.code,
                code_system=row.code_system,
                code_display=row.code_display,
                value_numeric=row.value_numeric,
                value_unit=row.value_unit,
                value_text=row.value_text,
                value_code=row.value_code,
                value_code_system=row.value_code_system,
                effective_at=row.effective_at,
                source="fhir",
                ingested_at=ingested_at,
            )
        )
        inserted += 1
    return inserted, skipped


def _encounter_fk(
    session: Session, patient_id: str, encounter_id: str | None, warnings: list[str]
) -> str | None:
    if not encounter_id:
        return None
    encounter = session.get(Encounter, encounter_id)
    if encounter is not None and encounter.patient_id == patient_id:
        return encounter_id
    warnings.append(
        f"Rencontre {encounter_id} introuvable pour le patient {patient_id} : lien non enregistré."
    )
    return None


def _message(warnings: list[str], inserted: dict[str, int]) -> str | None:
    parts: list[str] = []
    if all(value == 0 for value in inserted.values()):
        parts.append("Rejeu idempotent : aucune ligne existante n'a été modifiée.")
    parts.extend(warnings)
    if not parts:
        return None
    return " | ".join(parts)[:1000]

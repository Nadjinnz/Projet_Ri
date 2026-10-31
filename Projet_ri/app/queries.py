"""Lectures relationnelles utilisées par les routes."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Comment,
    Condition,
    Encounter,
    Medication,
    Observation,
    Patient,
)
from app.schemas import (
    CommentRead,
    ConditionRead,
    EncounterRead,
    MedicationRead,
    ObservationRead,
    PatientListItem,
    PatientSummary,
)


def _count(db: Session, model: type, patient_id: str) -> int:
    statement = select(func.count()).select_from(model).where(model.patient_id == patient_id)
    return int(db.scalar(statement) or 0)


def list_patients(db: Session, *, limit: int, offset: int) -> list[PatientListItem]:
    statement = (
        select(Patient)
        .order_by(Patient.family_name, Patient.given_name, Patient.id)
        .offset(offset)
        .limit(limit)
    )
    return [PatientListItem.model_validate(row) for row in db.scalars(statement)]


def get_patient_summary(db: Session, patient_id: str) -> PatientSummary | None:
    patient = db.get(Patient, patient_id)
    if patient is None:
        return None
    return PatientSummary(
        id=patient.id,
        family_name=patient.family_name,
        given_name=patient.given_name,
        birth_date=patient.birth_date,
        gender=patient.gender,
        source=patient.source,
        created_by=patient.created_by,
        created_at=patient.created_at,
        encounter_count=_count(db, Encounter, patient_id),
        condition_count=_count(db, Condition, patient_id),
        observation_count=_count(db, Observation, patient_id),
        medication_count=_count(db, Medication, patient_id),
        comment_count=_count(db, Comment, patient_id),
    )


def list_encounters(
    db: Session, patient_id: str, *, limit: int, offset: int
) -> list[EncounterRead]:
    statement = (
        select(Encounter)
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.period_start, Encounter.id)
        .offset(offset)
        .limit(limit)
    )
    return [EncounterRead.model_validate(row) for row in db.scalars(statement)]


def list_conditions(
    db: Session, patient_id: str, *, limit: int, offset: int
) -> list[ConditionRead]:
    statement = (
        select(Condition)
        .where(Condition.patient_id == patient_id)
        .order_by(Condition.recorded_at, Condition.id)
        .offset(offset)
        .limit(limit)
    )
    return [ConditionRead.model_validate(row) for row in db.scalars(statement)]


def list_observations(
    db: Session,
    patient_id: str,
    *,
    code: str | None,
    limit: int,
    offset: int,
) -> list[ObservationRead]:
    statement = select(Observation).where(Observation.patient_id == patient_id)
    if code is not None:
        statement = statement.where(Observation.code == code)
    statement = statement.order_by(Observation.effective_at, Observation.id).offset(offset).limit(limit)
    return [ObservationRead.model_validate(row) for row in db.scalars(statement)]


def list_medications(
    db: Session, patient_id: str, *, limit: int, offset: int
) -> list[MedicationRead]:
    statement = (
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .order_by(Medication.recorded_at, Medication.id)
        .offset(offset)
        .limit(limit)
    )
    return [MedicationRead.model_validate(row) for row in db.scalars(statement)]


def comment_to_read(comment: Comment) -> CommentRead:
    reference_id = {
        "patient": comment.patient_id,
        "encounter": comment.encounter_id,
        "condition": comment.condition_id,
        "observation": comment.observation_id,
        "medication": comment.medication_id,
    }[comment.reference_type]
    if reference_id is None:
        raise RuntimeError("Commentaire sans référence.")
    return CommentRead(
        id=comment.id,
        patient_id=comment.patient_id,
        reference_type=comment.reference_type,
        reference_id=reference_id,
        body=comment.body,
        author_id=comment.author_id,
        author_role=comment.author_role,
        created_at=comment.created_at,
    )


def list_comments(
    db: Session, patient_id: str, *, limit: int, offset: int
) -> list[CommentRead]:
    statement = (
        select(Comment)
        .where(Comment.patient_id == patient_id)
        .order_by(Comment.created_at, Comment.id)
        .offset(offset)
        .limit(limit)
    )
    return [comment_to_read(row) for row in db.scalars(statement)]

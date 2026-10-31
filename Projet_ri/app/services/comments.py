"""Ajout d'un commentaire. Aucune ligne clinique n'est modifiée."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.auth import Actor
from app.clock import utc_now_iso
from app.errors import PatientNotFound, ReferenceNotFound
from app.models import Comment, Condition, Encounter, Medication, Observation, Patient

_TARGETS = {
    "encounter": (Encounter, "encounter_id"),
    "condition": (Condition, "condition_id"),
    "observation": (Observation, "observation_id"),
    "medication": (Medication, "medication_id"),
}


def add_comment(
    db: Session,
    *,
    patient_id: str,
    actor: Actor,
    body: str,
    reference_type: str,
    reference_id: str,
) -> Comment:
    if db.get(Patient, patient_id) is None:
        raise PatientNotFound()
    comment = Comment(
        id=str(uuid4()),
        patient_id=patient_id,
        reference_type=reference_type,
        body=body,
        author_id=actor.actor_id,
        author_role=actor.role.value,
        created_at=utc_now_iso(),
        **_link(db, patient_id, reference_type, reference_id),
    )
    db.add(comment)
    db.commit()
    return comment


def _link(
    db: Session, patient_id: str, reference_type: str, reference_id: str
) -> dict[str, str | None]:
    columns: dict[str, str | None] = {
        "encounter_id": None,
        "condition_id": None,
        "observation_id": None,
        "medication_id": None,
    }
    if reference_type == "patient":
        if reference_id != patient_id:
            raise ReferenceNotFound()
        return columns
    model, column = _TARGETS[reference_type]
    row = db.get(model, reference_id)
    if row is None or row.patient_id != patient_id:
        raise ReferenceNotFound()
    columns[column] = reference_id
    return columns

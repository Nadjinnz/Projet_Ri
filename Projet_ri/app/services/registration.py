"""Création administrative d'un patient. L'identifiant est choisi ici."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.auth import Actor
from app.clock import utc_now_iso
from app.models import Patient
from app.schemas import PatientCreate


def register_patient(db: Session, payload: PatientCreate, actor: Actor) -> Patient:
    patient = Patient(
        id=str(uuid4()),
        family_name=payload.family_name,
        given_name=payload.given_name,
        birth_date=payload.birth_date.isoformat(),
        gender=payload.gender.value,
        source="api",
        created_by=actor.actor_id,
        created_at=utc_now_iso(),
        ingested_at=None,
    )
    db.add(patient)
    db.commit()
    return patient

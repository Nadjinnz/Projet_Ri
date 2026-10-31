"""Modèles ORM. Le DDL exécuté est sql/schema.sql.

Les lignes déjà persistées sont figées : un UPDATE ou un DELETE ORM lève
ClinicalRecordImmutabilityError avant d'atteindre SQLite, et les triggers
bloquent les mêmes opérations émises en SQL.
"""

from sqlalchemy import Float, Integer, Text, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.errors import ClinicalRecordImmutabilityError


class Patient(Base):
    """Identité administrative. La clé est l'id FHIR, ou un UUID pour l'API."""

    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    family_name: Mapped[str | None] = mapped_column(Text)
    given_name: Mapped[str | None] = mapped_column(Text)
    birth_date: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[str | None] = mapped_column(Text)


class Encounter(Base):
    """Rencontre (visite ou séjour), clé = id FHIR."""

    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text)
    class_code: Mapped[str | None] = mapped_column(Text)
    class_system: Mapped[str | None] = mapped_column(Text)
    class_display: Mapped[str | None] = mapped_column(Text)
    type_code: Mapped[str | None] = mapped_column(Text)
    type_system: Mapped[str | None] = mapped_column(Text)
    type_display: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_system: Mapped[str | None] = mapped_column(Text)
    reason_display: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[str | None] = mapped_column(Text)
    period_end: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[str] = mapped_column(Text, nullable=False)


class Condition(Base):
    """Diagnostic. code / code_system / code_display forment le fait lisible."""

    __tablename__ = "conditions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    encounter_id: Mapped[str | None] = mapped_column(Text)
    clinical_status: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    code_system: Mapped[str | None] = mapped_column(Text)
    code_display: Mapped[str | None] = mapped_column(Text)
    onset_at: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[str] = mapped_column(Text, nullable=False)


class Observation(Base):
    """Mesure. Une composante FHIR (ex. pression systolique) est une ligne."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    encounter_id: Mapped[str | None] = mapped_column(Text)
    parent_observation_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    code_system: Mapped[str | None] = mapped_column(Text)
    code_display: Mapped[str | None] = mapped_column(Text)
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_unit: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_code: Mapped[str | None] = mapped_column(Text)
    value_code_system: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[str] = mapped_column(Text, nullable=False)


class Medication(Base):
    """Médicament issu d'un MedicationRequest ou d'un MedicationStatement."""

    __tablename__ = "medications"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    encounter_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    code_system: Mapped[str | None] = mapped_column(Text)
    code_display: Mapped[str | None] = mapped_column(Text)
    dosage_text: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[str] = mapped_column(Text, nullable=False)


class Comment(Base):
    """Commentaire append-only. L'auteur, le rôle, l'heure et la cible sont figés."""

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    reference_type: Mapped[str] = mapped_column(Text, nullable=False)
    encounter_id: Mapped[str | None] = mapped_column(Text)
    condition_id: Mapped[str | None] = mapped_column(Text)
    observation_id: Mapped[str | None] = mapped_column(Text)
    medication_id: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(Text, nullable=False)
    author_role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class IngestionRun(Base):
    """Trace d'un fichier source : nom, empreinte SHA-256, volumes insérés."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    inserted_counts: Mapped[str] = mapped_column(Text, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str] = mapped_column(Text, nullable=False)


def _reject_mutations(session: Session, _flush_context, _instances) -> None:
    protected = (
        Patient,
        Encounter,
        Condition,
        Observation,
        Medication,
        Comment,
        IngestionRun,
    )
    for obj in list(session.deleted):
        if isinstance(obj, protected):
            raise ClinicalRecordImmutabilityError(
                "Suppression interdite. Le dossier clinique et son journal sont immuables."
            )
    for obj in list(session.dirty):
        if obj in session.new:
            continue
        if isinstance(obj, protected):
            raise ClinicalRecordImmutabilityError(
                "Modification interdite. Le dossier clinique et son journal sont immuables."
            )


def _install_immutability_guard() -> None:
    if getattr(_install_immutability_guard, "done", False):
        return
    event.listen(Session, "before_flush", _reject_mutations)
    _install_immutability_guard.done = True  # type: ignore[attr-defined]


_install_immutability_guard()

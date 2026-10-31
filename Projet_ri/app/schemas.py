"""Contrats JSON de l'API."""

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class Gender(str, Enum):
    male = "male"
    female = "female"
    other = "other"
    unknown = "unknown"


class ReferenceType(str, Enum):
    patient = "patient"
    encounter = "encounter"
    condition = "condition"
    observation = "observation"
    medication = "medication"


class PatientListItem(BaseModel):
    """Traits démographiques, sans les faits cliniques."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Identifiant FHIR du patient, ou UUID émis par l'API.")
    family_name: str | None = Field(description="Nom de famille.")
    given_name: str | None = Field(description="Prénoms, séparés par un espace.")
    birth_date: str | None = Field(description="Date de naissance AAAA-MM-JJ.")
    gender: str | None = Field(
        description="Sexe administratif FHIR : male, female, other ou unknown."
    )
    source: str = Field(description="Origine de la ligne : fhir ou api.")


class PatientSummary(PatientListItem):
    """Résumé de dossier : identité et volumes, pas le détail des faits."""

    created_by: str | None = Field(
        description="X-Actor-Id du data manager, si le patient a été créé via l'API."
    )
    created_at: str = Field(description="Horodatage de création de la ligne, en UTC.")
    encounter_count: int = Field(description="Nombre de rencontres.")
    condition_count: int = Field(description="Nombre de diagnostics.")
    observation_count: int = Field(description="Nombre d'observations, composantes comprises.")
    medication_count: int = Field(description="Nombre de médicaments.")
    comment_count: int = Field(description="Nombre de commentaires du journal.")


class PatientCreate(BaseModel):
    """Création administrative. Le serveur choisit l'identifiant."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "family_name": "Bernard",
                    "given_name": "Claire",
                    "birth_date": "1991-04-03",
                    "gender": "female",
                }
            ]
        },
    )

    family_name: str = Field(min_length=1, max_length=100, description="Nom de famille.")
    given_name: str = Field(min_length=1, max_length=100, description="Prénom.")
    birth_date: date = Field(description="Date de naissance. Elle ne peut pas être future.")
    gender: Gender = Field(description="Sexe administratif FHIR.")

    @field_validator("family_name", "given_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le nom ne peut pas être vide.")
        return cleaned

    @field_validator("birth_date")
    @classmethod
    def birth_date_not_in_the_future(cls, value: date) -> date:
        today = datetime.now(timezone.utc).date()
        if value > today:
            raise ValueError("La date de naissance ne peut pas être dans le futur.")
        return value


class EncounterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    status: str | None = Field(description="Statut FHIR de la rencontre.")
    class_code: str | None = Field(description="Code de classe, par exemple AMB ou IMP.")
    class_system: str | None = Field(description="Système du code de classe.")
    class_display: str | None = Field(description="Libellé lisible de la classe.")
    type_code: str | None
    type_system: str | None
    type_display: str | None = Field(description="Libellé lisible du type de rencontre.")
    reason_code: str | None
    reason_system: str | None
    reason_display: str | None = Field(description="Libellé lisible du motif.")
    period_start: str | None = Field(description="Début, tel que reçu dans le FHIR.")
    period_end: str | None = Field(description="Fin, telle que reçue dans le FHIR.")


class ConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    encounter_id: str | None
    clinical_status: str | None = Field(description="Statut clinique FHIR, par exemple active.")
    code: str | None = Field(description="Code retenu, de préférence SNOMED CT.")
    code_system: str | None = Field(description="URI du système de codage.")
    code_display: str | None = Field(description="Libellé lisible attaché au code retenu.")
    onset_at: str | None = Field(description="Date de début du diagnostic.")
    recorded_at: str | None = Field(description="Date d'enregistrement du diagnostic.")


class ObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    encounter_id: str | None
    parent_observation_id: str | None = Field(
        description="Observation panneau dont cette ligne est une composante."
    )
    status: str | None
    code: str | None = Field(description="Code retenu, de préférence LOINC.")
    code_system: str | None = Field(description="URI du système de codage.")
    code_display: str | None = Field(description="Libellé lisible attaché au code retenu.")
    value_numeric: float | None = Field(description="Valeur numérique, si la mesure est quantitative.")
    value_unit: str | None = Field(description="Unité de la valeur numérique.")
    value_text: str | None = Field(description="Valeur textuelle ou libellé d'une valeur codée.")
    value_code: str | None = Field(description="Code de la valeur, si elle est un CodeableConcept.")
    value_code_system: str | None
    effective_at: str | None = Field(description="Date de la mesure.")

    @field_serializer("value_numeric")
    def serialize_numeric(self, value: float | None) -> float | int | None:
        if value is None:
            return None
        as_float = float(value)
        if as_float.is_integer():
            return int(as_float)
        return as_float


class MedicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    encounter_id: str | None
    status: str | None
    intent: str | None = Field(description="Intention FHIR, par exemple order.")
    code: str | None = Field(description="Code retenu, de préférence RxNorm.")
    code_system: str | None = Field(description="URI du système de codage.")
    code_display: str | None = Field(description="Libellé lisible attaché au code retenu.")
    dosage_text: str | None = Field(description="Posologie en texte libre.")
    recorded_at: str | None = Field(description="Date de prescription ou d'assertion.")


class CommentCreate(BaseModel):
    """Ajout au journal. L'auteur et l'horodatage viennent du serveur."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "body": "Fréquence cardiaque stable au cours de la visite.",
                    "reference_type": "observation",
                    "reference_id": "obs-anne-hr",
                }
            ]
        },
    )

    body: str = Field(
        min_length=1,
        max_length=4000,
        description="Texte du commentaire. Il est conservé et ne peut plus être modifié.",
    )
    reference_type: ReferenceType = Field(
        description="Type de la ressource visée : patient, encounter, condition, observation ou medication."
    )
    reference_id: str = Field(
        description="Identifiant de la ressource visée. Pour le dossier entier, l'id du patient."
    )

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le commentaire ne peut pas être vide.")
        return cleaned

    @field_validator("reference_id")
    @classmethod
    def reference_id_is_fhir(cls, value: str) -> str:
        from app.identifiers import FHIR_ID

        cleaned = value.strip()
        if FHIR_ID.fullmatch(cleaned) is None:
            raise ValueError(
                "reference_id n'est pas un identifiant FHIR valide "
                "(lettres, chiffres, point, tiret, 1 à 64 caractères)."
            )
        return cleaned


class CommentRead(BaseModel):
    id: str = Field(description="Identifiant émis par le serveur.")
    patient_id: str
    reference_type: str = Field(description="Type de la ressource commentée.")
    reference_id: str = Field(description="Identifiant de la ressource commentée.")
    body: str
    author_id: str = Field(description="X-Actor-Id du clinicien, posé par le serveur.")
    author_role: str = Field(description="Rôle de l'auteur. Vaut clinician.")
    created_at: str = Field(description="Horodatage UTC posé par le serveur.")

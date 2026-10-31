"""Authentification simulée et contrôle d'accès par rôle.

Les en-têtes X-Role et X-Actor-Id tiennent lieu de session. Un déploiement
réel les remplacerait par un jeton OIDC émis par l'hôpital.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.identifiers import InvalidIdentifier, check_resource_id

MISSING_AUTH = (
    "Authentification requise. Envoyez les en-têtes X-Role et X-Actor-Id."
)
UNKNOWN_ROLE = (
    "Rôle non reconnu. Valeurs acceptées : clinician, patient, data_manager."
)
INVALID_ACTOR = (
    "X-Actor-Id invalide. Format attendu : identifiant FHIR "
    "(lettres, chiffres, point, tiret, 1 à 64 caractères)."
)
INVALID_PATIENT_ID = (
    "Identifiant patient invalide. Format attendu : identifiant FHIR "
    "(lettres, chiffres, point, tiret, 1 à 64 caractères)."
)
INVALID_CODE = (
    "Paramètre code invalide. Format attendu : code clinique "
    "(lettres, chiffres, point, tiret, 1 à 64 caractères)."
)
PATIENT_SCOPE = "Un patient ne peut accéder qu'à son propre dossier."
PATIENT_NOT_FOUND = "Patient introuvable."
REFERENCE_NOT_FOUND = (
    "La ressource référencée est introuvable dans le dossier de ce patient."
)

role_header = APIKeyHeader(
    name="X-Role",
    scheme_name="X-Role",
    description="Rôle de l'appelant : clinician, patient ou data_manager.",
    auto_error=False,
)
actor_header = APIKeyHeader(
    name="X-Actor-Id",
    scheme_name="X-Actor-Id",
    description=(
        "Identifiant de l'appelant. Pour le rôle patient, cet identifiant "
        "est celui du dossier qu'il peut consulter."
    ),
    auto_error=False,
)


class Role(str, Enum):
    clinician = "clinician"
    patient = "patient"
    data_manager = "data_manager"


@dataclass(frozen=True)
class Actor:
    role: Role
    actor_id: str


def get_actor(
    role: Annotated[str | None, Security(role_header)],
    actor_id: Annotated[str | None, Security(actor_header)],
) -> Actor:
    if role is None or actor_id is None or not role.strip() or not actor_id.strip():
        raise HTTPException(status_code=401, detail=MISSING_AUTH)
    try:
        parsed_role = Role(role.strip())
    except ValueError:
        raise HTTPException(status_code=401, detail=UNKNOWN_ROLE) from None
    try:
        parsed_actor = check_resource_id(actor_id.strip())
    except InvalidIdentifier:
        raise HTTPException(status_code=401, detail=INVALID_ACTOR) from None
    return Actor(role=parsed_role, actor_id=parsed_actor)


def require(*roles: Role):
    """Dépendance FastAPI : laisse passer uniquement les rôles listés."""

    allowed = roles

    def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        if actor.role not in allowed:
            names = ", ".join(role.value for role in allowed)
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Accès refusé pour le rôle '{actor.role.value}'. "
                    f"Rôles autorisés : {names}."
                ),
            )
        return actor

    return dependency


def ensure_can_read_patient(actor: Actor, patient_id: str) -> None:
    if actor.role is Role.patient and actor.actor_id != patient_id:
        raise HTTPException(status_code=403, detail=PATIENT_SCOPE)


def require_patient_id(value: str) -> str:
    try:
        return check_resource_id(value)
    except InvalidIdentifier:
        raise HTTPException(status_code=400, detail=INVALID_PATIENT_ID) from None


def require_code(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail=INVALID_CODE)
    try:
        return check_resource_id(stripped)
    except InvalidIdentifier:
        raise HTTPException(status_code=400, detail=INVALID_CODE) from None

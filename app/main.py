"""Application FastAPI du dossier clinique."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app import __version__
from app.database import get_session_factory
from app.errors import ClinicalRecordImmutabilityError
from app.routers import router

DESCRIPTION = """
API de lecture du dossier clinique hospitalier, alimentée par un pipeline ETL FHIR R4.

Les bundles (un fichier JSON par patient, au format Synthea) sont aplatis en
Python puis chargés dans des tables. À partir de cet instant, chaque fait
clinique est immuable : aucun endpoint ne le modifie ni ne le supprime.
Sur un dossier déjà ouvert, la seule écriture est l'ajout d'un commentaire.

## Authentification simulée

Toute route, sauf `GET /health`, exige deux en-têtes :

- `X-Role` : `clinician`, `patient` ou `data_manager`
- `X-Actor-Id` : identifiant de l'appelant. Pour un patient, c'est l'identifiant de son dossier.

Le bouton Authorize de cette page renseigne les deux en-têtes. Cette simulation
pédagogique ne remplace pas un serveur d'identité OIDC : en production, le rôle
ne serait pas déclaré par le client.

## Codes HTTP

| Code | Situation |
| --- | --- |
| 400 | Identifiant ou paramètre `code` mal formé |
| 401 | En-tête absent, ou rôle inconnu |
| 403 | Rôle reconnu, action interdite |
| 404 | Patient absent, ou cible de commentaire hors de son dossier |
| 405 | Méthode non offerte : pas de mise à jour ni de suppression |
| 409 | Garde-fou interne : réécriture d'un enregistrement immuable |
| 422 | Corps JSON ou pagination invalide |

## Qui peut faire quoi

- **clinician** : lire tous les dossiers, ajouter un commentaire.
- **patient** : lire uniquement le dossier dont l'identifiant est le sien.
- **data_manager** : lire tous les dossiers, enregistrer un nouveau patient.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_session_factory()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Dossier clinique",
        summary="Lecture des faits FHIR et journal de commentaires.",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
        openapi_tags=[
            {
                "name": "Patients",
                "description": "Identité administrative. La création est réservée au data manager.",
            },
            {
                "name": "Rencontres",
                "description": "Visites et séjours importés depuis FHIR Encounter. Lecture seule.",
            },
            {
                "name": "Faits cliniques",
                "description": (
                    "Diagnostics, observations et médicaments. "
                    "Chaque fait conserve son code, son système, son libellé, sa date "
                    "et, s'il y a lieu, sa valeur et son unité. Lecture seule."
                ),
            },
            {
                "name": "Commentaires",
                "description": (
                    "Journal append-only. L'auteur, son rôle, l'horodatage et la cible "
                    "sont posés à l'écriture et ne changent plus."
                ),
            },
            {
                "name": "Système",
                "description": "Disponibilité du service, sans donnée clinique.",
            },
        ],
    )
    application.include_router(router)
    application.add_exception_handler(
        ClinicalRecordImmutabilityError, _immutable_record
    )

    @application.get(
        "/health",
        tags=["Système"],
        summary="État du service",
        response_description="Le service répond.",
    )
    def health() -> dict[str, str]:
        """Indique que le processus répond.

        Cette route ne lit aucun dossier et n'exige pas d'en-tête.

        Accès : public. Aucune donnée clinique n'est renvoyée.

        Erreurs : aucune en fonctionnement normal. Un échec d'infrastructure
        se traduit par l'absence de réponse, pas par un corps clinique.
        """
        return {"status": "ok"}

    return application


def _immutable_record(_request: Request, exc: ClinicalRecordImmutabilityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app = create_app()

"""Routes du dossier clinique. Lecture des faits, ajout de commentaires, création de patient."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

from app.auth import (
    PATIENT_NOT_FOUND,
    REFERENCE_NOT_FOUND,
    Actor,
    Role,
    ensure_can_read_patient,
    get_actor,
    require,
    require_code,
    require_patient_id,
)
from app.database import get_db
from app.errors import PatientNotFound, ReferenceNotFound
from app.queries import (
    comment_to_read,
    get_patient_summary,
    list_comments,
    list_conditions,
    list_encounters,
    list_medications,
    list_observations,
    list_patients,
)
from app.schemas import (
    CommentCreate,
    CommentRead,
    ConditionRead,
    EncounterRead,
    MedicationRead,
    ObservationRead,
    PatientCreate,
    PatientListItem,
    PatientSummary,
)
from app.services.comments import add_comment
from app.services.registration import register_patient

router = APIRouter(
    responses={
        401: {
            "description": "En-têtes X-Role et X-Actor-Id absents, ou rôle non reconnu."
        },
        403: {
            "description": "Le rôle est reconnu, mais cette opération ne lui est pas permise."
        },
    }
)

_PATIENT_ID = Path(
    description="Identifiant FHIR du patient, ou UUID émis par POST /patients."
)
_NOT_FOUND = {
    400: {"description": "L'identifiant du chemin n'est pas un identifiant FHIR."},
    404: {"description": "Aucun patient ne porte cet identifiant."},
}


def _readable_patient_id(db: Session, actor: Actor, raw_id: str) -> str:
    patient_id = require_patient_id(raw_id)
    ensure_can_read_patient(actor, patient_id)
    if get_patient_summary(db, patient_id) is None:
        raise HTTPException(status_code=404, detail=PATIENT_NOT_FOUND)
    return patient_id


@router.get(
    "/patients",
    response_model=list[PatientListItem],
    tags=["Patients"],
    summary="Lister les patients",
    response_description="Page de patients, triée par nom.",
)
def read_patients(
    _actor: Annotated[Actor, Depends(require(Role.clinician, Role.data_manager))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Taille de page, de 1 à 200."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Nombre de patients sautés avant la page."),
    ] = 0,
) -> list[PatientListItem]:
    """Retourne l'identité administrative des patients, sans leurs faits cliniques.

    La page est triée par nom de famille, prénom, puis identifiant. `limit` et
    `offset` découpent cette liste. Les diagnostics, mesures, médicaments et
    commentaires se lisent sur les routes du dossier, pas ici.

    Accès : clinician et data_manager. Le rôle patient reçoit 403, car cette
    liste expose d'autres dossiers que le sien.

    Erreurs : 401 si X-Role ou X-Actor-Id manque, ou si le rôle n'est pas
    clinician, patient ou data_manager. 403 si le rôle authentifié n'est pas
    clinicien ou data manager. 422 si limit ou offset est hors bornes.
    """
    return list_patients(db, limit=limit, offset=offset)


@router.post(
    "/patients",
    response_model=PatientSummary,
    status_code=201,
    tags=["Patients"],
    summary="Enregistrer un patient",
    response_description="Dossier créé. L'identifiant a été choisi par le serveur.",
    responses={422: {"description": "Corps JSON invalide, ou date de naissance future."}},
)
def create_patient(
    payload: PatientCreate,
    response: Response,
    actor: Annotated[Actor, Depends(require(Role.data_manager))],
    db: Annotated[Session, Depends(get_db)],
) -> PatientSummary:
    """Crée un dossier administratif vide. Aucun fait clinique n'est écrit.

    Le serveur génère l'identifiant (UUID) et l'inscrit dans l'en-tête
    Location. Le corps ne peut pas imposer un id, un auteur ou une source :
    la source vaut `api` et `created_by` reçoit le X-Actor-Id du data manager.
    Les champs inconnus sont refusés.

    Accès : data_manager uniquement. Un clinicien ou un patient reçoit 403.

    Erreurs : 401 si l'authentification est absente ou illisible. 403 si le
    rôle n'est pas data_manager. 422 si un nom est vide, si le sexe n'est pas
    male, female, other ou unknown, ou si la date de naissance est future.
    """
    patient = register_patient(db, payload, actor)
    response.headers["Location"] = f"/patients/{patient.id}"
    summary = get_patient_summary(db, patient.id)
    if summary is None:
        raise HTTPException(status_code=404, detail=PATIENT_NOT_FOUND)
    return summary


@router.get(
    "/patients/{id}",
    response_model=PatientSummary,
    tags=["Patients"],
    summary="Résumé d'un patient",
    response_description="Identité du patient et nombre de faits rattachés.",
    responses=_NOT_FOUND,
)
def read_patient(
    id: Annotated[str, _PATIENT_ID],
    actor: Annotated[Actor, Depends(get_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> PatientSummary:
    """Retourne l'identité du patient et le décompte de son dossier.

    Le résumé compte les rencontres, diagnostics, observations (composantes
    comprises), médicaments et commentaires. Il ne remplace pas le détail de
    ces faits, qui reste sur les routes dédiées. Rien n'est modifié.

    Accès : clinician et data_manager pour tout dossier. patient seulement si
    `{id}` est égal à X-Actor-Id.

    Erreurs : 400 si `{id}` n'est pas un identifiant FHIR. 401 si
    l'authentification est absente ou illisible. 403 si un patient demande un
    autre dossier. 404 si aucun patient ne porte cet identifiant. L'existence
    d'un autre dossier n'est pas révélée au rôle patient : il reçoit 403.
    """
    patient_id = _readable_patient_id(db, actor, id)
    summary = get_patient_summary(db, patient_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=PATIENT_NOT_FOUND)
    return summary


@router.get(
    "/patients/{id}/encounters",
    response_model=list[EncounterRead],
    tags=["Rencontres"],
    summary="Rencontres d'un patient",
    response_description="Visites et séjours du dossier, du plus ancien au plus récent.",
    responses=_NOT_FOUND,
)
def read_encounters(
    id: Annotated[str, _PATIENT_ID],
    actor: Annotated[Actor, Depends(get_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500, description="Taille de page, de 1 à 500.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Nombre de rencontres sautées.")] = 0,
) -> list[EncounterRead]:
    """Liste les rencontres du patient, sans les modifier.

    Chaque ligne conserve la classe (code, système, libellé), le type, le
    motif et les bornes de la période, tels qu'ils ont été figés à l'ingestion.
    Le tri suit le début de période puis l'identifiant.

    Accès : clinician et data_manager pour tout dossier. patient seulement
    pour son propre `{id}`.

    Erreurs : 400 si l'identifiant est mal formé. 401 si l'authentification
    est absente ou illisible. 403 si un patient consulte un autre dossier.
    404 si le patient n'existe pas. 422 si limit ou offset est hors bornes.
    Une liste vide signifie que ce dossier n'a pas de rencontre, pas que le
    patient est inconnu.
    """
    patient_id = _readable_patient_id(db, actor, id)
    return list_encounters(db, patient_id, limit=limit, offset=offset)


@router.get(
    "/patients/{id}/conditions",
    response_model=list[ConditionRead],
    tags=["Faits cliniques"],
    summary="Diagnostics d'un patient",
    response_description="Diagnostics figés à l'ingestion.",
    responses=_NOT_FOUND,
)
def read_conditions(
    id: Annotated[str, _PATIENT_ID],
    actor: Annotated[Actor, Depends(get_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500, description="Taille de page, de 1 à 500.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Nombre de diagnostics sautés.")] = 0,
) -> list[ConditionRead]:
    """Liste les diagnostics (ressource FHIR Condition) du patient.

    Pour chaque fait : code, système de codage, libellé lisible, statut
    clinique, date de début et date d'enregistrement. Le codage préféré à
    l'ingestion est SNOMED CT, puis CIM-10. Cette route est en lecture seule.

    Accès : clinician et data_manager pour tout dossier. patient seulement
    pour son propre `{id}`.

    Erreurs : 400 si l'identifiant est mal formé. 401 si l'authentification
    est absente ou illisible. 403 si un patient consulte un autre dossier.
    404 si le patient n'existe pas. 422 si la pagination est hors bornes.
    """
    patient_id = _readable_patient_id(db, actor, id)
    return list_conditions(db, patient_id, limit=limit, offset=offset)


@router.get(
    "/patients/{id}/observations",
    response_model=list[ObservationRead],
    tags=["Faits cliniques"],
    summary="Observations d'un patient",
    response_description="Mesures du dossier, filtrables par code.",
    responses={
        **_NOT_FOUND,
        400: {
            "description": "Identifiant patient ou paramètre code mal formé."
        },
    },
)
def read_observations(
    id: Annotated[str, _PATIENT_ID],
    actor: Annotated[Actor, Depends(get_actor)],
    db: Annotated[Session, Depends(get_db)],
    code: Annotated[
        str | None,
        Query(
            description=(
                "Code exact retenu à l'ingestion. Pour un export Synthea c'est "
                "en général un LOINC, par exemple 8480-6 pour la pression systolique. "
                "Les composantes d'un panneau (pression artérielle) sont des lignes "
                "distinctes et se filtrent par leur propre code."
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Taille de page, de 1 à 500.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Nombre d'observations sautées.")] = 0,
) -> list[ObservationRead]:
    """Liste les observations cliniques du patient, en lecture seule.

    Chaque ligne porte le code, le système, le libellé, la date de mesure et,
    selon le type de valeur FHIR, un nombre avec son unité, un texte, ou un
    code de valeur. Sans `code`, la page contient le panneau et ses
    composantes. Avec `code`, la correspondance est exacte : un code inconnu
    dans un dossier existant renvoie une liste vide, pas 404.

    Accès : clinician et data_manager pour tout dossier. patient seulement
    pour son propre `{id}`.

    Erreurs : 400 si l'identifiant ou `code` contient un caractère hors de
    l'alphabet FHIR (lettres, chiffres, point, tiret, 64 caractères). 401 si
    l'authentification est absente ou illisible. 403 si un patient consulte
    un autre dossier. 404 si le patient n'existe pas. 422 si la pagination
    est hors bornes.
    """
    patient_id = _readable_patient_id(db, actor, id)
    return list_observations(
        db,
        patient_id,
        code=require_code(code),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/patients/{id}/medications",
    response_model=list[MedicationRead],
    tags=["Faits cliniques"],
    summary="Médicaments d'un patient",
    response_description="Prescriptions et assertions médicamenteuses du dossier.",
    responses=_NOT_FOUND,
)
def read_medications(
    id: Annotated[str, _PATIENT_ID],
    actor: Annotated[Actor, Depends(get_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500, description="Taille de page, de 1 à 500.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Nombre de médicaments sautés.")] = 0,
) -> list[MedicationRead]:
    """Liste les médicaments (MedicationRequest et MedicationStatement).

    Pour chaque fait : code, système (RxNorm de préférence), libellé, statut,
    intention, posologie textuelle et date. La route ne prescrit rien et ne
    modifie pas une ligne déjà chargée.

    Accès : clinician et data_manager pour tout dossier. patient seulement
    pour son propre `{id}`.

    Erreurs : 400 si l'identifiant est mal formé. 401 si l'authentification
    est absente ou illisible. 403 si un patient consulte un autre dossier.
    404 si le patient n'existe pas. 422 si la pagination est hors bornes.
    """
    patient_id = _readable_patient_id(db, actor, id)
    return list_medications(db, patient_id, limit=limit, offset=offset)


@router.get(
    "/patients/{id}/comments",
    response_model=list[CommentRead],
    tags=["Commentaires"],
    summary="Commentaires d'un dossier",
    response_description="Journal des commentaires, du plus ancien au plus récent.",
    responses=_NOT_FOUND,
)
def read_comments(
    id: Annotated[str, _PATIENT_ID],
    actor: Annotated[Actor, Depends(get_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500, description="Taille de page, de 1 à 500.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Nombre de commentaires sautés.")] = 0,
) -> list[CommentRead]:
    """Retourne le journal append-only du dossier, dans l'ordre d'écriture.

    Chaque commentaire expose son auteur, le rôle de cet auteur, l'horodatage
    serveur et la ressource visée (type et identifiant). Les commentaires ne
    peuvent être ni modifiés ni supprimés : la page s'allonge, elle ne se
    réécrit pas.

    Accès : clinician et data_manager pour tout dossier. patient seulement
    pour son propre `{id}`.

    Erreurs : 400 si l'identifiant est mal formé. 401 si l'authentification
    est absente ou illisible. 403 si un patient consulte un autre dossier.
    404 si le patient n'existe pas. 422 si la pagination est hors bornes.
    """
    patient_id = _readable_patient_id(db, actor, id)
    return list_comments(db, patient_id, limit=limit, offset=offset)


@router.post(
    "/patients/{id}/comments",
    response_model=CommentRead,
    status_code=201,
    tags=["Commentaires"],
    summary="Ajouter un commentaire",
    response_description="Commentaire enregistré. Son identifiant a été choisi par le serveur.",
    responses={
        **_NOT_FOUND,
        404: {
            "description": (
                "Patient introuvable, ou ressource référencée absente de son dossier."
            )
        },
        422: {
            "description": (
                "Corps invalide : texte vide, type de référence inconnu, "
                "identifiant mal formé, ou champ non autorisé (auteur, date)."
            )
        },
    },
)
def create_comment(
    id: Annotated[str, _PATIENT_ID],
    payload: CommentCreate,
    actor: Annotated[Actor, Depends(require(Role.clinician))],
    db: Annotated[Session, Depends(get_db)],
) -> CommentRead:
    """Ajoute un commentaire au dossier. C'est la seule écriture permise sur un dossier existant.

    Le serveur pose l'identifiant, l'auteur (`X-Actor-Id`), le rôle
    (`clinician`) et l'horodatage UTC. Le client ne peut pas les fournir :
    un champ supplémentaire est refusé. `reference_type` et `reference_id`
    désignent le patient, une rencontre, un diagnostic, une observation ou
    un médicament de ce dossier. La cible doit déjà exister et appartenir
    au patient de l'URL. Le commentaire n'altère pas le fait qu'il cite.

    Accès : clinician uniquement. patient et data_manager reçoivent 403,
    y compris sur leur propre dossier.

    Erreurs : 400 si l'identifiant du chemin est mal formé. 401 si
    l'authentification est absente ou illisible. 403 si le rôle n'est pas
    clinician. 404 si le patient n'existe pas, ou si la ressource citée
    n'est pas dans son dossier. 422 si le texte est vide, si le type de
    référence est inconnu, si `reference_id` est mal formé, ou si le corps
    tente de fixer l'auteur ou la date.
    """
    patient_id = require_patient_id(id)
    try:
        comment = add_comment(
            db,
            patient_id=patient_id,
            actor=actor,
            body=payload.body,
            reference_type=payload.reference_type.value,
            reference_id=payload.reference_id,
        )
    except PatientNotFound:
        raise HTTPException(status_code=404, detail=PATIENT_NOT_FOUND) from None
    except ReferenceNotFound:
        raise HTTPException(status_code=404, detail=REFERENCE_NOT_FOUND) from None
    return comment_to_read(comment)

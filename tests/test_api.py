"""Contrat HTTP : rôles, codes d'erreur, journal append-only."""

import re

import pytest

from app.main import app

CLINICIAN = {"X-Role": "clinician", "X-Actor-Id": "dr-bernard"}
DATA_MANAGER = {"X-Role": "data_manager", "X-Actor-Id": "dm-nadia"}
PATIENT_ANNE = {"X-Role": "patient", "X-Actor-Id": "anne-dupont"}
UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
NEW_PATIENT = {
    "family_name": "Bernard",
    "given_name": "Claire",
    "birth_date": "1991-04-03",
    "gender": "female",
}


def test_every_operation_documents_who_can_call_it(client):
    spec = client.get("/openapi.json").json()
    seen = 0
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            description = operation.get("description") or ""
            assert "Accès" in description, path
            assert len(description) > 80, path
            seen += 1
    assert seen >= 8


def test_the_api_exposes_no_update_or_delete(client):
    unsafe = {"PUT", "PATCH", "DELETE"}
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        assert not (methods & unsafe)

    for method in ("put", "patch", "delete"):
        response = client.request(method, "/patients/anne-dupont", headers=CLINICIAN)
        assert response.status_code == 405
    assert client.post("/patients/anne-dupont/observations", headers=CLINICIAN, json={}).status_code == 405


def test_docs_and_health_are_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_or_unknown_identity_is_unauthorized(client):
    assert client.get("/patients").status_code == 401
    assert client.get("/patients", headers={"X-Role": "admin", "X-Actor-Id": "x"}).status_code == 401


def test_a_patient_cannot_list_other_charts_but_can_read_their_own(client):
    assert client.get("/patients", headers=PATIENT_ANNE).status_code == 403

    own = client.get("/patients/anne-dupont", headers=PATIENT_ANNE)
    assert own.status_code == 200
    body = own.json()
    assert body["given_name"] == "Anne Marie"
    assert body["encounter_count"] == 1
    assert body["condition_count"] == 1
    assert body["observation_count"] == 4
    assert body["medication_count"] == 1

    foreign = client.get("/patients/paul-martin", headers=PATIENT_ANNE)
    assert foreign.status_code == 403
    assert "propre dossier" in foreign.json()["detail"]


def test_clinician_lists_patients_and_reads_facts(client):
    page = client.get("/patients?limit=1&offset=0", headers=CLINICIAN)
    assert page.status_code == 200
    assert page.json()[0]["family_name"] == "Dupont"

    conditions = client.get("/patients/anne-dupont/conditions", headers=CLINICIAN)
    assert conditions.status_code == 200
    assert conditions.json()[0]["code"] == "59621000"
    assert conditions.json()[0]["code_display"] == "Essential hypertension"

    encounters = client.get("/patients/anne-dupont/encounters", headers=CLINICIAN)
    assert encounters.json()[0]["class_code"] == "AMB"
    assert encounters.json()[0]["class_display"] == "ambulatory"

    systolic = client.get(
        "/patients/anne-dupont/observations",
        params={"code": "8480-6"},
        headers=CLINICIAN,
    )
    assert systolic.status_code == 200
    row = systolic.json()[0]
    assert row["value_numeric"] == 128
    assert row["value_unit"] == "mmHg"
    assert row["code_system"] == "http://loinc.org"
    assert row["code_display"] == "Systolic blood pressure"

    unknown_code = client.get(
        "/patients/anne-dupont/observations",
        params={"code": "0000-0"},
        headers=CLINICIAN,
    )
    assert unknown_code.status_code == 200
    assert unknown_code.json() == []

    medications = client.get("/patients/anne-dupont/medications", headers=CLINICIAN)
    assert medications.json()[0]["code"] == "29046"
    assert medications.json()[0]["dosage_text"] == "10 mg par voie orale une fois par jour"


def test_unknown_and_malformed_patient_ids(client):
    missing = client.get("/patients/nobody-1", headers=CLINICIAN)
    assert missing.status_code == 404
    malformed = client.get("/patients/anne_dupont", headers=CLINICIAN)
    assert malformed.status_code == 400
    bad_code = client.get(
        "/patients/anne-dupont/observations",
        params={"code": "systolic pressure"},
        headers=CLINICIAN,
    )
    assert bad_code.status_code == 400


def test_data_manager_registers_a_patient_and_a_clinician_cannot(client):
    created = client.post("/patients", json=NEW_PATIENT, headers=DATA_MANAGER)
    assert created.status_code == 201
    body = created.json()
    assert UUID4.fullmatch(body["id"])
    assert body["source"] == "api"
    assert body["created_by"] == "dm-nadia"
    assert body["encounter_count"] == 0
    assert created.headers["location"] == f"/patients/{body['id']}"

    as_patient = client.get(
        f"/patients/{body['id']}",
        headers={"X-Role": "patient", "X-Actor-Id": body["id"]},
    )
    assert as_patient.status_code == 200

    refused = client.post("/patients", json=NEW_PATIENT, headers=CLINICIAN)
    assert refused.status_code == 403

    future = client.post(
        "/patients",
        json={**NEW_PATIENT, "birth_date": "2999-01-01"},
        headers=DATA_MANAGER,
    )
    assert future.status_code == 422


def test_comments_are_append_only_and_do_not_rewrite_the_fact(client):
    payload = {
        "body": "Tension à contrôler dans un mois.",
        "reference_type": "observation",
        "reference_id": "obs-anne-bp.8480-6",
    }
    first = client.post("/patients/anne-dupont/comments", json=payload, headers=CLINICIAN)
    assert first.status_code == 201
    assert first.json()["author_id"] == "dr-bernard"
    assert first.json()["author_role"] == "clinician"
    assert first.json()["reference_id"] == "obs-anne-bp.8480-6"
    assert UUID4.fullmatch(first.json()["id"])

    second = client.post(
        "/patients/anne-dupont/comments",
        json={**payload, "body": "Le patient confirme la prise du lisinopril."},
        headers=CLINICIAN,
    )
    assert second.status_code == 201

    journal = client.get("/patients/anne-dupont/comments", headers=PATIENT_ANNE)
    assert journal.status_code == 200
    assert [item["body"] for item in journal.json()] == [
        "Tension à contrôler dans un mois.",
        "Le patient confirme la prise du lisinopril.",
    ]

    observation = client.get(
        "/patients/anne-dupont/observations",
        params={"code": "8480-6"},
        headers=CLINICIAN,
    )
    assert observation.json()[0]["value_numeric"] == 128


@pytest.mark.parametrize("headers", [PATIENT_ANNE, DATA_MANAGER])
def test_only_a_clinician_adds_a_comment(client, headers):
    response = client.post(
        "/patients/anne-dupont/comments",
        json={
            "body": "Je ne devrais pas pouvoir écrire ceci.",
            "reference_type": "patient",
            "reference_id": "anne-dupont",
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_the_client_cannot_stamp_the_author_or_cite_another_chart(client):
    forged = client.post(
        "/patients/anne-dupont/comments",
        json={
            "body": "Note.",
            "reference_type": "patient",
            "reference_id": "anne-dupont",
            "author_id": "quelqu-un-d-autre",
        },
        headers=CLINICIAN,
    )
    assert forged.status_code == 422

    blank = client.post(
        "/patients/anne-dupont/comments",
        json={"body": "   ", "reference_type": "patient", "reference_id": "anne-dupont"},
        headers=CLINICIAN,
    )
    assert blank.status_code == 422

    foreign = client.post(
        "/patients/anne-dupont/comments",
        json={
            "body": "Cette mesure appartient à Paul.",
            "reference_type": "observation",
            "reference_id": "obs-paul-weight",
        },
        headers=CLINICIAN,
    )
    assert foreign.status_code == 404
    assert client.get("/patients/anne-dupont/comments", headers=CLINICIAN).json() == []

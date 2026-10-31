"""Chargement idempotent et refus de réécriture."""

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.errors import ClinicalRecordImmutabilityError
from app.models import IngestionRun, Observation
from etl.load import load_file

ANNE = Path(__file__).resolve().parents[1] / "data" / "fhir" / "anne_dupont.json"


def test_anne_is_loaded_with_an_audit_hash(session):
    result = load_file(session, ANNE)

    assert result.status == "success"
    assert result.patient_id == "anne-dupont"
    assert result.content_sha256 == hashlib.sha256(ANNE.read_bytes()).hexdigest()
    systolic = session.scalar(select(Observation).where(Observation.code == "8480-6"))
    assert systolic is not None
    assert systolic.value_numeric == 128
    assert systolic.value_unit == "mmHg"
    run = session.scalars(select(IngestionRun)).one()
    assert run.content_sha256 == result.content_sha256
    assert run.status == "success"
    assert json.loads(run.inserted_counts)["observations"] == 4


def test_reloading_does_not_change_the_clinical_value(session):
    load_file(session, ANNE)
    second = load_file(session, ANNE)

    assert second.status == "success"
    assert second.inserted == {
        "patients": 0,
        "encounters": 0,
        "conditions": 0,
        "observations": 0,
        "medications": 0,
    }
    assert "Rejeu idempotent" in (second.message or "")
    session.expire_all()
    systolic = session.scalar(select(Observation).where(Observation.code == "8480-6"))
    assert systolic.value_numeric == 128
    assert session.scalars(select(IngestionRun)).all().__len__() == 2


def test_invalid_json_is_journalized_without_a_patient(session, tmp_path):
    bad = tmp_path / "casse.json"
    bad.write_bytes(b"{")

    result = load_file(session, bad)

    assert result.status == "failed"
    assert result.patient_id is None
    assert result.content_sha256 == hashlib.sha256(b"{").hexdigest()
    from app.models import Patient

    assert session.scalars(select(Patient)).all() == []
    run = session.scalars(select(IngestionRun)).one()
    assert run.status == "failed"


def test_the_orm_cannot_update_an_observation(session):
    load_file(session, ANNE)
    observation = session.get(Observation, "obs-anne-hr")
    observation.value_numeric = 1

    with pytest.raises(ClinicalRecordImmutabilityError):
        session.commit()

    session.rollback()
    session.expire_all()
    assert session.get(Observation, "obs-anne-hr").value_numeric == 72


def test_sql_cannot_update_or_delete_an_observation(session):
    load_file(session, ANNE)

    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE observations SET value_numeric = 0 WHERE id = 'obs-anne-hr'"))
        session.commit()
    session.rollback()

    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM observations WHERE id = 'obs-anne-hr'"))
        session.commit()
    session.rollback()
    session.expire_all()
    assert session.get(Observation, "obs-anne-hr").value_numeric == 72

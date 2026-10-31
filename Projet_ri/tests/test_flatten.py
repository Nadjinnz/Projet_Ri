"""Règles d'aplatissement FHIR, sans base."""

import json
from pathlib import Path

import pytest

from app.errors import FlattenError
from etl.flatten import flatten_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_snomed_wins_over_a_local_code_and_blood_pressure_is_split():
    bundle = json.loads((ROOT / "data" / "fhir" / "anne_dupont.json").read_text(encoding="utf-8"))
    flat = flatten_bundle(bundle)

    assert flat.patient.family_name == "Dupont"
    assert flat.patient.given_name == "Anne Marie"
    assert flat.patient.birth_date == "1984-06-12"
    assert flat.patient.gender == "female"

    condition = flat.conditions[0]
    assert condition.code == "59621000"
    assert condition.code_system == "http://snomed.info/sct"
    assert condition.code_display == "Essential hypertension"
    assert condition.clinical_status == "active"
    assert condition.onset_at == "2020-01-15"
    assert condition.encounter_id == "enc-anne-1"

    systolic = next(row for row in flat.observations if row.code == "8480-6")
    assert systolic.id == "obs-anne-bp.8480-6"
    assert systolic.parent_observation_id == "obs-anne-bp"
    assert systolic.value_numeric == 128
    assert systolic.value_unit == "mmHg"
    assert systolic.code_display == "Systolic blood pressure"
    assert systolic.effective_at == "2024-03-12T10:15:00Z"

    encounter = flat.encounters[0]
    assert encounter.class_code == "AMB"
    assert encounter.class_display == "ambulatory"
    assert any("Immunization" in warning for warning in flat.warnings)


def test_urn_uuid_references_are_resolved():
    bundle = json.loads((ROOT / "data" / "fhir" / "paul_martin.json").read_text(encoding="utf-8"))
    flat = flatten_bundle(bundle)

    assert flat.patient.id == "paul-martin"
    assert flat.conditions[0].encounter_id == "enc-paul-1"
    assert flat.observations[0].value_numeric == pytest.approx(82.4)
    assert flat.observations[0].value_unit == "kg"
    assert flat.medications[0].code == "723"
    assert flat.medications[0].code_system == "http://www.nlm.nih.gov/research/umls/rxnorm"
    assert flat.medications[0].dosage_text.startswith("250 mg")


def test_a_file_must_contain_exactly_one_patient():
    with pytest.raises(FlattenError):
        flatten_bundle({"resourceType": "Bundle", "entry": []})
    with pytest.raises(FlattenError):
        flatten_bundle({"resourceType": "Patient", "id": "seul"})


def test_a_resource_for_another_patient_is_not_attached():
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "pat-1", "gender": "female"}},
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-other",
                    "status": "final",
                    "subject": {"reference": "Patient/pat-2"},
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                    "valueQuantity": {"value": 60, "unit": "/min"},
                }
            },
        ],
    }
    flat = flatten_bundle(bundle)
    assert flat.observations == []
    assert flat.skipped == 1

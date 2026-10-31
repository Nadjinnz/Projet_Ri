"""Le DDL de sql/schema.sql est celui que l'ORM interroge."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.clock import utc_now_iso
from app.database import Base
from app.models import Comment, Encounter, Observation, Patient

TABLES = (
    "patients",
    "encounters",
    "conditions",
    "observations",
    "medications",
    "comments",
    "ingestion_runs",
)


def test_orm_columns_follow_the_sql_file(engine):
    import app.models  # noqa: F401

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) >= set(TABLES)
    for table in Base.metadata.tables.values():
        in_database = [column["name"] for column in inspector.get_columns(table.name)]
        in_model = [column.name for column in table.columns]
        assert in_database == in_model, table.name


def test_immutability_triggers_exist(session):
    names = set(session.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars())
    expected = {f"trg_{table}_no_update" for table in TABLES}
    expected |= {f"trg_{table}_no_delete" for table in TABLES}
    assert expected <= names


def test_a_fact_cannot_reference_an_unknown_patient(session):
    session.add(
        Encounter(
            id="enc-x",
            patient_id="absent",
            source="fhir",
            ingested_at=utc_now_iso(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_only_a_clinician_can_be_the_author_of_a_comment(session):
    now = utc_now_iso()
    session.add(
        Patient(
            id="p1",
            family_name="Test",
            given_name="Un",
            birth_date="2000-01-01",
            gender="female",
            source="api",
            created_at=now,
        )
    )
    session.commit()
    session.add(
        Comment(
            id="c1",
            patient_id="p1",
            reference_type="patient",
            body="Note",
            author_id="dm-nadia",
            author_role="data_manager",
            created_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_comment_points_at_exactly_one_fact(session):
    now = utc_now_iso()
    session.add(
        Patient(
            id="p1",
            family_name="Test",
            given_name="Un",
            gender="male",
            source="api",
            created_at=now,
        )
    )
    session.commit()
    session.add(Encounter(id="e1", patient_id="p1", source="fhir", ingested_at=now))
    session.add(Observation(id="o1", patient_id="p1", source="fhir", ingested_at=now))
    session.commit()
    session.add(
        Comment(
            id="c1",
            patient_id="p1",
            reference_type="observation",
            observation_id="o1",
            encounter_id="e1",
            body="Deux cibles.",
            author_id="dr-bernard",
            author_role="clinician",
            created_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()

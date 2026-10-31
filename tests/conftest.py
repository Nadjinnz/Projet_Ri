"""Base SQLite en mémoire, partagée par les tests d'un même cas."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import get_db, init_db, make_engine
from app.main import app
from etl.load import load_file

ROOT = Path(__file__).resolve().parents[1]
FHIR_DIR = ROOT / "data" / "fhir"


@pytest.fixture
def engine():
    db_engine = make_engine("sqlite:///:memory:")
    init_db(db_engine)
    yield db_engine
    db_engine.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@pytest.fixture
def session(factory):
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(factory):
    db = factory()
    try:
        for path in sorted(FHIR_DIR.glob("*.json")):
            result = load_file(db, path)
            if result.status != "success":
                raise RuntimeError(result.message)
    finally:
        db.close()

    def override():
        scoped = factory()
        try:
            yield scoped
        except Exception:
            scoped.rollback()
            raise
        finally:
            scoped.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

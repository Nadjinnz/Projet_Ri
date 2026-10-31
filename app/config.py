"""Configuration lue dans l'environnement, avec des défauts locaux."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    fhir_input_dir: Path


def get_settings() -> Settings:
    default_db = (ROOT / "data" / "hospital.db").resolve().as_posix()
    return Settings(
        database_url=os.environ.get("DATABASE_URL", f"sqlite:///{default_db}"),
        fhir_input_dir=Path(os.environ.get("FHIR_INPUT_DIR", ROOT / "data" / "fhir")),
    )

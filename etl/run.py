"""Point d'entrée : python -m etl.run"""

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import init_db, make_engine
from etl.load import load_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aplatit des bundles FHIR R4 et charge les tables cliniques, sans réécrire l'existant."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Dossier contenant un fichier JSON par patient.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="URL SQLAlchemy. Défaut : SQLite data/hospital.db.",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    database_url = args.database_url or settings.database_url
    directory = args.input or settings.fhir_input_dir

    if not directory.is_dir():
        print(f"Dossier introuvable : {directory}", file=sys.stderr)
        return 2
    files = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not files:
        print(f"Aucun bundle JSON dans {directory}", file=sys.stderr)
        return 2

    engine = make_engine(database_url)
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    failed = 0
    for path in files:
        session = factory()
        try:
            result = load_file(session, path)
        finally:
            session.close()
        inserted = sum(result.inserted.values())
        print(
            f"{result.status:8} {result.source_file} "
            f"patient={result.patient_id or '-'} insérés={inserted} ignorés={result.skipped}"
        )
        if result.status != "success":
            failed += 1
            if result.message:
                print(f"         {result.message}", file=sys.stderr)
    engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

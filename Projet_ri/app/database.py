"""Connexion SQLite et application du schéma."""

import re
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
_BEGIN = re.compile(r"\bBEGIN\b", re.IGNORECASE)
_END = re.compile(r"\bEND\b", re.IGNORECASE)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """Registre des modèles. Les tables sont créées par sql/schema.sql."""


def split_sql_script(script: str) -> list[str]:
    """Découpe un script SQLite en conservant les corps de triggers."""
    lines = [
        line
        for line in script.splitlines()
        if not line.strip().startswith("--")
    ]
    cleaned = "\n".join(lines)
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    for chunk in re.split(r"(;)", cleaned):
        if chunk == ";":
            current.append(chunk)
            if depth == 0:
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
            continue
        depth += len(_BEGIN.findall(chunk))
        depth -= len(_END.findall(chunk))
        if depth < 0:
            depth = 0
        current.append(chunk)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def make_engine(url: str) -> Engine:
    connect_args: dict[str, object] = {}
    options: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in url:
            options["poolclass"] = StaticPool
    engine = create_engine(url, connect_args=connect_args, **options)
    if url.startswith("sqlite"):
        _enable_foreign_keys(engine)
    return engine


def _enable_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _prepare_sqlite_directory(url: str) -> None:
    prefix = "sqlite:///"
    if not url.startswith(prefix) or ":memory:" in url:
        return
    path = Path(url[len(prefix) :])
    if str(path) in {"", ":memory:"}:
        return
    path.parent.mkdir(parents=True, exist_ok=True)


def init_db(engine: Engine) -> None:
    """Crée les tables, les index et les triggers d'immuabilité."""
    import app.models  # noqa: F401  # installe la garde ORM

    script = SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.begin() as connection:
        for statement in split_sql_script(script):
            sql = statement.strip()
            if sql.endswith(";"):
                sql = sql[:-1].strip()
            if not sql or sql.upper().startswith("PRAGMA"):
                continue
            connection.exec_driver_sql(sql)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _prepare_sqlite_directory(settings.database_url)
        _engine = make_engine(settings.database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        init_db(engine)
        _session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _session_factory


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

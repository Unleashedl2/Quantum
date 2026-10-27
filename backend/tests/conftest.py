"""Pruebas de integración: requieren PostgreSQL real (TEST_DATABASE_URL). Se recrea la BD aplicando las migraciones."""
import os
from pathlib import Path
import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_URL:
    os.environ["DATABASE_URL"] = TEST_URL
BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def client():
    if not TEST_URL:
        pytest.skip("Defina TEST_DATABASE_URL para las pruebas de integración")
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from app.db.base import Base
    from app.db.session import engine
    import app.models  # noqa
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS alembic_version"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")          # también prueba que las migraciones corren (criterio #17)
    from app.cli import init_system
    init_system()
    from app.main import app
    return TestClient(app)


def new_client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

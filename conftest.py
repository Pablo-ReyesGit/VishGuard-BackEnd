import os

# Estas variables de entorno tienen que existir ANTES de que se importe
# core.config (que instancia Settings() al cargarse el módulo). Se define
# aquí, en la parte más alta de conftest.py, para que se ejecute antes que
# cualquier import de main/app/core.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("PROJECT_NAME", "VishGuard-Test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("FIRST_SUPERUSER", "admin@test.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "test-admin-pass1")

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.deps import get_db
from main import app


@pytest.fixture(name="session")
def session_fixture():
    # Un engine SQLite en memoria, nuevo para cada test -> aislamiento total,
    # nunca toca la base de datos real de desarrollo.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_db] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
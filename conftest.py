import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

# Las variables de entorno de prueba se definen antes de cargar la app.
# Se utiliza sqlite:// para evitar exponer credenciales de PostgreSQL en tests.
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-pytest-execution-12345")
os.environ.setdefault("PROJECT_NAME", "VishGuard-Test")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FIRST_SUPERUSER", "admin@test.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "test-admin-pass123!")

from api.deps import get_db
from main import app


@pytest.fixture(name="session")
def session_fixture():
    # Engine SQLite en memoria para aislamiento absoluto durante los tests
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
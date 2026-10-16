import os

from dotenv import load_dotenv
from sqlmodel import SQLModel, Session, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "No se encontró DATABASE_URL. Revisa el archivo .env."
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def init_db() -> None:
    """Crea las tablas registradas en los modelos SQLModel."""
    # Importar los modelos antes de crear las tablas.
    from models.user import User
    from models.alert import Alerta

    SQLModel.metadata.create_all(engine)


def get_db():
    with Session(engine) as session:
        yield session

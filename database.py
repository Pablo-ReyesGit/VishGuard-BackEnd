import datetime
from sqlmodel import SQLModel, create_engine, Session, Field
from sqlalchemy.orm import sessionmaker

# 1. Importa el objeto 'settings' instanciado en core/config.py
from core.config import settings

# 2. Accede directamente al atributo DATABASE_URL del objeto 'settings'
engine = create_engine(
    str(settings.DATABASE_URL), 
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class AlertHistory(SQLModel, table=True):
    __tablename__: str = "alert_history"

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    nivel_riesgo: str = Field(index=True, max_length=20)
    score: int
    patrones_detectados: str = Field(max_length=255)
    frase_critica: str
    recomendacion: str


def init_db() -> None:
    SQLModel.metadata.create_all(bind=engine)


def get_db():
    with Session(engine) as session:
        yield session
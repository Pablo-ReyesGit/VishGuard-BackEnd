import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# Base de datos SQLite local
DATABASE_URL = "sqlite:///./vishguard.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modelo de la tabla de alertas
class AlertHistory(Base):
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    nivel_riesgo = Column(String(20), index=True)
    score = Column(Integer)
    patrones_detectados = Column(String(255))
    frase_critica = Column(Text)
    recomendacion = Column(Text)

# Inicializar tablas en la Base de Datos
def init_db():
    Base.metadata.create_all(bind=engine)  # <-- CORREGIDO: create_all en lugar de create_engine

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
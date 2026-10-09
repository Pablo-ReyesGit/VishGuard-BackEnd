import os

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    Column,
    BigInteger,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    CheckConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

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

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# 1. USUARIO
class Usuario(Base):
    __tablename__ = "usuario"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    correo = Column(String(150), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(20), nullable=False, default="USUARIO")
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    llamadas = relationship("Llamada", back_populates="usuario")


# 2. LLAMADA
class Llamada(Base):
    __tablename__ = "llamada"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    usuario_id = Column(
        BigInteger,
        ForeignKey("usuario.id"),
        nullable=True,
        index=True,
    )
    fecha_inicio = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    duracion_segundos = Column(Integer, nullable=True)
    numero_origen = Column(String(30), nullable=True)
    tipo = Column(String(20), nullable=True)
    transcripcion = Column(Text, nullable=False)
    estado = Column(String(20), nullable=False, default="ANALIZADA")
    creada_en = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", back_populates="llamadas")
    analisis = relationship(
        "Analisis",
        back_populates="llamada",
        uselist=False,
        cascade="all, delete-orphan",
    )


# 3. ANALISIS
class Analisis(Base):
    __tablename__ = "analisis"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_analisis_score",
        ),
        UniqueConstraint("llamada_id", name="uq_analisis_llamada"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    llamada_id = Column(
        BigInteger,
        ForeignKey("llamada.id"),
        nullable=False,
    )
    nivel_riesgo = Column(String(20), nullable=False)
    score = Column(Integer, nullable=False)
    frase_critica = Column(Text, nullable=True)
    recomendacion = Column(Text, nullable=True)
    motor_ia = Column(String(50), nullable=True)
    tiempo_respuesta_ms = Column(Numeric(10, 2), nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    llamada = relationship("Llamada", back_populates="analisis")
    patrones = relationship(
        "PatronDeteccion",
        back_populates="analisis",
        cascade="all, delete-orphan",
    )
    alerta = relationship(
        "Alerta",
        back_populates="analisis",
        uselist=False,
        cascade="all, delete-orphan",
    )


# 4. PATRON_DETECCION
class PatronDeteccion(Base):
    __tablename__ = "patron_deteccion"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    analisis_id = Column(
        BigInteger,
        ForeignKey("analisis.id"),
        nullable=False,
        index=True,
    )
    nombre = Column(String(150), nullable=False)
    categoria = Column(String(50), nullable=True)
    descripcion = Column(Text, nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    analisis = relationship("Analisis", back_populates="patrones")


# 5. ALERTA
class Alerta(Base):
    __tablename__ = "alerta"
    __table_args__ = (
        UniqueConstraint("analisis_id", name="uq_alerta_analisis"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    analisis_id = Column(
        BigInteger,
        ForeignKey("analisis.id"),
        nullable=False,
    )
    nivel = Column(String(20), nullable=False)
    mensaje = Column(Text, nullable=False)
    mostrada = Column(Boolean, nullable=False, default=False)
    fecha_alerta = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    analisis = relationship("Analisis", back_populates="alerta")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)


def test_connection():
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            print("✅ Conexión a Neon exitosa:", result.scalar())
            return True
    except Exception as error:
        print("❌ Error conectando a Neon:", error)
        return False


if __name__ == "__main__":
    test_connection()
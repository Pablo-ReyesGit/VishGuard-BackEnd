
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field
from sqlalchemy import false


class Alerta(SQLModel, table=True):
    __tablename__ = "alerta"

    id: Optional[int] = Field(default=None, primary_key=True)

    usuario_id: int = Field(
        foreign_key="user.id",
        index=True
    )

    nivel_riesgo: str = Field(max_length=20)
    score: int = Field(ge=0, le=100)

    mensaje_alerta: str
    recomendacion: Optional[str] = None

    mostrada: bool = Field(default=False)
    es_simulacion: bool = Field(default=False, sa_column_kwargs={"server_default": false()})

    fecha_alerta: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

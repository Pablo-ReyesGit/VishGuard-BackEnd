
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


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

    fecha_alerta: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

"""Validación de configuración JWT/entorno. Integrar estos campos en tu core/config.py.
pip install pydantic-settings
"""
from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE = {"changethis", "secret", "changeme", "dev", "development"}

class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: Literal["dev", "prod"] = "prod"   # fail-safe: si falta la variable, se asume producción
    SECRET_KEY: str
    JWT_ALGORITHM: Literal["HS256"] = "HS256"   # algoritmo fijo (nunca "none")
    CORS_ORIGINS: list[str] = []
    GEMINI_API_KEY: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if len(self.SECRET_KEY.encode()) < 32:
            raise ValueError("SECRET_KEY debe tener >= 32 bytes")
        if self.SECRET_KEY.lower() in _INSECURE:
            raise ValueError("SECRET_KEY inseguro")
        if self.ENVIRONMENT == "prod" and "*" in self.CORS_ORIGINS:
            raise ValueError("CORS '*' no permitido en prod")
        return self

    @property
    def docs_url(self) -> str | None:   # FastAPI(docs_url=settings.docs_url, redoc_url=...)
        return None if self.ENVIRONMENT == "prod" else "/docs"

import warnings
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import (
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "changethis"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    FASTAPI_ENV: Literal["development", "production", "testing"] | None = "development"

    PROJECT_NAME: str = "Proyecto Neon"
    SENTRY_DSN: HttpUrl | None = None

    # Pydantic Settings lee automáticamente DATABASE_URL desde .env o las variables de entorno.
    # Permite 'str' para soportar el esquema 'postgresql+psycopg://'.
    DATABASE_URL: PostgresDsn | str = "postgresql+psycopg://postgres:postgres@localhost:5432/app"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str | PostgresDsn:
        if not value:
            return value
        database_url = str(value).strip()
        # Remueve el prefijo CLI 'psql ' si fue copiado por error
        if database_url.startswith("psql "):
            database_url = database_url.replace("psql ", "", 1).strip("'\"")

        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "changethis"

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value in ("changethis", "pass", "user"):
            message = (
                f'The value of {var_name} is insecure or set to default ("{value}"). '
                "Please change it in your .env file before running in production."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=2)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)

        # Extracción segura de la contraseña usando urllib.parse
        if self.DATABASE_URL:
            parsed_url = urlparse(str(self.DATABASE_URL))
            if parsed_url.password:
                self._check_default_secret("DATABASE_URL password", parsed_url.password)

        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()
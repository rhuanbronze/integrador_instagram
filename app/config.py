"""Environment configuration. Secrets are never serialized as plaintext."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    meta_api_version: str = Field(default="v26.0", pattern=r"^v\d+\.\d+$")
    instagram_access_token: SecretStr
    instagram_user_id: str = Field(default="", pattern=r"^\d*$")
    mysql_host: str = Field(min_length=1)
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = Field(default="instagram_bi", min_length=1)
    mysql_user: str = Field(min_length=1)
    mysql_password: SecretStr
    timezone: str = "America/Cuiaba"
    account_collection_hours: float = Field(default=24, gt=0)
    media_collection_hours: float = Field(default=6, gt=0)
    media_insights_lookback_days: int = Field(default=90, ge=0)
    request_timeout_seconds: float = Field(default=30, gt=0)
    request_max_retries: int = Field(default=3, ge=0, le=10)
    admin_api_key: SecretStr
    log_level: str = "INFO"
    audience_collection_enabled: bool = True
    collect_on_startup: bool = True
    scheduler_enabled: bool = True

    @field_validator("instagram_access_token", "mysql_password", "admin_api_key")
    @classmethod
    def nonempty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("A nonempty secret is required")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("log_level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid log level")
        return value.upper()

    @property
    def instagram_base_url(self) -> str:
        return f"https://graph.instagram.com/{self.meta_api_version}"

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

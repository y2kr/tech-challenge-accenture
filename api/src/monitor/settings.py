import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    cors_origins: str
    database_url: str = ""
    test_database_url: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    @field_validator("database_url", "test_database_url")
    @classmethod
    def force_psycopg_driver(cls, url: str) -> str:
        return re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", url)


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    cors_origins: str
    database_url: str = ""
    test_database_url: str = ""


settings = Settings()

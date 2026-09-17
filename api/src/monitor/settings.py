from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    cors_origins: str
    database_url: str = ""
    test_database_url: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"


settings = Settings()

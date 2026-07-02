import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: Optional[str] = None
    llm_model: str = "gemini-2.5-flash"
    embedding_provider: str = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    vector_store_path: str = "./chroma_data"
    log_level: str = "info"
    port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./loom.db"
    github_client_id: Optional[str] = None
    github_client_secret: Optional[str] = None
    jwt_secret: str = "default_jwt_secret_change_me_in_production"
    encryption_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

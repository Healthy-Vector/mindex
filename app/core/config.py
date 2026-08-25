from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str

    # --- PIN 세션 (지시서 §4.7) ---
    jwt_secret: str = "dev-insecure-change-me-at-least-32-bytes"
    jwt_alg: str = "HS256"
    session_ttl_minutes: int = 15
    session_refresh_throttle_seconds: int = 60

    # --- 페이지네이션 기본값 (지시서 §4.6) ---
    page_size_default: int = 20
    page_size_max: int = 100

    llm_provider: str = "openai"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    solar_api_key: Optional[str] = None
    hyperclova_api_key: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

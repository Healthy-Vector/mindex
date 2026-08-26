from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str

    # --- CORS ---
    # 콤마로 구분한 허용 오리진 목록. 값이 "*" 하나면 모든 오리진을 열되
    # 요청 오리진을 그대로 되비춰(regex) Authorization 헤더까지 허용한다
    # (와일드카드 "*"는 credentials와 함께 못 쓰므로 regex로 우회). 기본값은
    # 개발 오리진만 — 프록시 없이 브라우저가 직접 API를 부를 때만 필요하다.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_allow_all(self) -> bool:
        return self.cors_origins.strip() == "*"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # --- PIN 세션 (지시서 §4.7) ---
    jwt_secret: str = "dev-insecure-change-me-at-least-32-bytes"
    jwt_alg: str = "HS256"
    session_ttl_minutes: int = 15
    session_refresh_throttle_seconds: int = 60

    # --- 페이지네이션 기본값 (지시서 §4.6) ---
    page_size_default: int = 20
    page_size_max: int = 100

    # --- 계약 원본 PDF 저장소 (D-34) ---
    # object storage는 도입하지 않는다. 확정 시 staging.pdf_blob의 바이트를
    # 이 디렉터리로 옮기고, contract_history.file_path에는 여기 기준 상대
    # 경로만 남긴다. 읽을 때 이 경계 밖은 거부한다(app/services/storage.py).
    contract_storage_dir: str = "./data/contracts"

    llm_provider: str = "openai"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    solar_api_key: Optional[str] = None
    hyperclova_api_key: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

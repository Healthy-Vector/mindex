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

    # --- 임베딩 / 벡터 검색 ---
    # 기본값 True — 검색 벡터 랭킹을 켠다. 켜져 있으면 sentence-transformers가
    # 설치돼 있어야 하고, 서버 기동 시 임베딩 모델을 미리 데운다(warm-up).
    # 임베딩 없이 어휘(pg_trgm) 폴백으로만 돌리려면 EMBEDDINGS_ENABLED=false로
    # 끈다(팀 전파용 opt-out). 런타임에 패키지를 설치하지는 않는다 — 설치는
    # 배포 단계, 이 플래그는 사용 여부만 정한다.
    embeddings_enabled: bool = True

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

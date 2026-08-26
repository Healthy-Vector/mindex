"""FastAPI 인스턴스 · 예외 핸들러 등록 · 라우터 조립 (담당 P4).

라우터는 마일스톤별로 추가한다. 각 라우터 파일이 자신의 엔드포인트를 소유한다.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.errors import register_error_handlers

settings = get_settings()

app = FastAPI(
    title="mindex",
    description="OpenSQL 기반 저작권 계약 인텔리전스 플랫폼",
    version="0.1.0",
)

# CORS — 프론트는 보통 Vite 프록시(같은 오리진)로 붙어 CORS가 안 걸리지만,
# 브라우저가 다른 오리진에서 API를 직접 부르는 배포에서는 이 설정이 필요하다.
# CORS_ORIGINS="*"면 모든 오리진을 열되 요청 오리진을 되비춰 Authorization
# 헤더(PIN 세션)까지 허용한다 — 와일드카드는 credentials와 못 쓰기 때문이다.
if settings.cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 모든 에러를 단일 응답 형태로 변환 (지시서 §4.2)
register_error_handlers(app)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.app_env}


# --- 라우터 조립 (마일스톤 진행에 따라 아래에 추가된다) ---
# M2: refs, ips / M4~5: contracts / M7: auth, rights
from app.routers import refs as _refs  # noqa: E402
from app.routers import ips as _ips  # noqa: E402
from app.routers import contracts as _contracts  # noqa: E402
from app.routers import rights as _rights  # noqa: E402
from app.routers import auth as _auth  # noqa: E402
from app.routers import search as _search  # noqa: E402
from app.routers import extraction as _extraction  # noqa: E402

app.include_router(_auth.router, prefix="/api", tags=["auth"])
app.include_router(_refs.router, prefix="/api", tags=["refs"])
app.include_router(_ips.router, prefix="/api", tags=["ips"])
app.include_router(_contracts.router, prefix="/api", tags=["contracts"])
app.include_router(_rights.router, prefix="/api", tags=["rights"])
app.include_router(_search.router, prefix="/api", tags=["search"])
app.include_router(_extraction.router, prefix="/api", tags=["extract"])

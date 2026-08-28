"""FastAPI 인스턴스 · 예외 핸들러 등록 · 라우터 조립 (담당 P4).

라우터는 마일스톤별로 추가한다. 각 라우터 파일이 자신의 엔드포인트를 소유한다.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.errors import register_error_handlers

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """기동 시 임베딩 모델을 미리 로딩한다(warm-up).

    검색 질의 임베딩은 첫 호출 때 모델을 지연 로딩하는데, 그 첫 요청이 2GB대
    모델 다운로드·로딩을 통째로 기다리게 된다. 콜드 스타트를 첫 사용자에게
    떠넘기지 않도록 여기서 미리 데운다.

    `EMBEDDINGS_ENABLED`(기본 True)로 켜고 끈다. 런타임에 패키지를 설치하지는
    않는다 — 설치는 배포 단계고 이 플래그는 사용 여부만 정한다.

    - 꺼짐: 조용히 생략. 검색은 어휘(pg_trgm) 폴백으로 동작한다(팀 전파용 opt-out).
    - 켜짐 + 패키지 없음: 기본이 켜짐이므로 미설치는 설정 실수다 — 크게 경고하고,
      설치법과 끄는 법을 함께 남긴다. 서버 기동은 막지 않는다.
    - 켜짐 + 패키지 있음: 모델을 미리 데운다. warm-up 실패도 기동을 막지 않는다.
    """
    if not settings.embeddings_enabled:
        logger.info("EMBEDDINGS_ENABLED=false — 임베딩 warm-up 생략(어휘 검색 폴백)")
        yield
        return

    from app.pipeline import embed

    if not embed.is_available():
        logger.warning(
            "EMBEDDINGS_ENABLED=true인데 sentence-transformers가 없다. 벡터 랭킹 없이 "
            "어휘 검색으로만 동작한다. 설치: pip install -r requirements-ml.txt / "
            "의도된 것이면 EMBEDDINGS_ENABLED=false로 끈다."
        )
        yield
        return

    try:
        logger.info("임베딩 모델 warm-up 시작")
        embed.get_model()
        logger.info("임베딩 모델 warm-up 완료")
    except Exception:  # noqa: BLE001 — warm-up 실패가 기동을 막으면 안 된다
        logger.exception("임베딩 warm-up 실패 — 검색은 어휘 폴백으로 계속한다")
    yield


app = FastAPI(
    title="mindex",
    description="OpenSQL 기반 저작권 계약 인텔리전스 플랫폼",
    version="0.1.0",
    lifespan=lifespan,
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

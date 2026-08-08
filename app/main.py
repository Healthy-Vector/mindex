from fastapi import FastAPI

from app.api.contracts import router as contracts_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="mindex",
    description="OpenSQL 기반 저작권 계약 인텔리전스 플랫폼",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.app_env}


# 각자 라우터는 자신의 줄만 추가한다 (P4가 아래 1줄 소유).
app.include_router(contracts_router, prefix="/api", tags=["contracts"])

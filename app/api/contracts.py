"""SFR-014 대시보드가 호출하는 REST 엔드포인트 — 담당 P4.

프론트엔드(frontend/src/api/client.js)가 기대하는 경로:
    GET /api/contracts            → 목록
    GET /api/contracts/{id}       → 상세 (rights_grants 포함)
    GET /api/search?q=...         → 검색 (SFR-008 MCP / SFR-009 하이브리드 검색 위임)

이 파일은 아직 구현되지 않았다. app/main.py에서 라우터를 등록하려면:
    from app.api.contracts import router as contracts_router
    app.include_router(contracts_router, prefix="/api")
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db

router = APIRouter()


@router.get("/contracts")
def list_contracts(db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: int, db: Session = Depends(get_db)):
    raise NotImplementedError


@router.get("/search")
def search(q: str, db: Session = Depends(get_db)):
    # SFR-009 하이브리드 검색(app/search/hybrid.py)에 위임한다.
    raise NotImplementedError

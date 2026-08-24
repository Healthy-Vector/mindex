"""계약 라우터 — 5·6·7·8·9·11번 (지시서 §5 §6).

충돌은 에러가 아니다(§4.3): 5번은 200, 6번은 201 로 주고 본문에 내역을 담는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.contracts import VerifyRequest, VerifyResponse
from app.services import conflict as conflict_svc
from app.services.team_context import resolve_team_id

router = APIRouter()


@router.post("/contracts/verify", response_model=VerifyResponse)
def verify_contract(body: VerifyRequest, db: Session = Depends(get_db)) -> VerifyResponse:
    """5번 — 충돌검사. DB 에 행을 남기지 않는다(항상 롤백). 충돌도 200(§4.3 §5.5)."""
    team_id = resolve_team_id(db)
    result = conflict_svc.verify_contract(db, body, team_id)
    return VerifyResponse.model_validate(result)


# --- 6번 POST /contracts — 확정 저장 (지시서 §5.6) ---
from fastapi import Response  # noqa: E402

from app.schemas.contracts import ConfirmRequest, ConfirmResponse  # noqa: E402


@router.post("/contracts", response_model=ConfirmResponse, status_code=201)
def confirm_contract(
    body: ConfirmRequest, response: Response, db: Session = Depends(get_db)
) -> ConfirmResponse:
    """6번 — 확정 저장. 충돌도 201(§4.3): 본문 hasConflict/conflicts 로 구분."""
    team_id = resolve_team_id(db)
    result = conflict_svc.confirm_contract(db, body, team_id)
    return ConfirmResponse.model_validate(result)


# --- 7번 GET /contracts — 목록 (지시서 §6 7번) ---
from typing import Optional as _Opt  # noqa: E402

from fastapi import Query  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.schemas.listing import ContractListItem, ProcessingListItem  # noqa: E402
from app.services.display import compute_display  # noqa: E402


def _contract_meta(db: Session, contract_id: int) -> tuple[bool, _Opt[str], _Opt[int]]:
    """(hasConflict, displayState, daysToExpiry) 계산."""
    latest = db.execute(
        text(
            "SELECT status FROM master.contract_history WHERE contract_id=:c "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"c": contract_id},
    ).first()
    has_conflict = bool(latest and latest[0] == "conflicted")
    agg = db.execute(
        text(
            "SELECT min(lower(period)) AS lo, max(upper(period)) AS hi "
            "FROM master.rights_grant WHERE contract_id=:c AND status='active'"
        ),
        {"c": contract_id},
    ).first()
    state, days = compute_display(agg[0] if agg else None, agg[1] if agg else None)
    return has_conflict, state, days


@router.get("/contracts")
def list_contracts(
    include_processing: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    size: _Opt[int] = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """계약 + 처리중(staging) 을 created_at 역순으로 병합. UNION 하지 않는다(§6 7번)."""
    s = get_settings()
    size = size or s.page_size_default
    team_id = resolve_team_id(db)

    contracts = db.execute(
        text(
            "SELECT c.id, c.title, c.counterparty, c.contract_type, c.status, "
            "       c.signed_date, c.created_at, "
            "       COALESCE(h.title, c.title) AS disp_title, "
            "       COALESCE(h.amount, c.amount) AS amount, "
            "       COALESCE(h.currency, c.currency) AS currency "
            "FROM master.contract c "
            "LEFT JOIN master.contract_history h ON h.id = c.current_history_id "
            "WHERE c.team_id = :t ORDER BY c.created_at DESC"
        ),
        {"t": team_id},
    ).mappings().all()

    items: list[dict] = []
    for c in contracts:
        has_conflict, state, days = _contract_meta(db, c["id"])
        item = ContractListItem(
            id=c["id"], title=c["disp_title"], counterparty=c["counterparty"],
            contract_type=c["contract_type"], status=c["status"],
            has_conflict=has_conflict, display_state=state, days_to_expiry=days,
            service_title=None, signed_date=c["signed_date"], created_at=c["created_at"],
        )
        items.append(item.model_dump(by_alias=True, mode="json"))

    if include_processing:
        procs = db.execute(
            text(
                "SELECT j.tmpid, j.status, j.stage, j.reason, j.created_at, b.filename "
                "FROM staging.extract_job j "
                "LEFT JOIN staging.pdf_blob b ON b.tmpid = j.tmpid "
                "WHERE j.status IN ('QUEUED','RUNNING','FAILED') "
                "ORDER BY j.created_at DESC"
            )
        ).mappings().all()
        for p in procs:
            item = ProcessingListItem(
                tmpid=str(p["tmpid"]), status=p["status"], stage=p["stage"],
                filename=p["filename"], reason=p["reason"], created_at=p["created_at"],
            )
            items.append(item.model_dump(by_alias=True, mode="json"))

    # created_at 역순 병합 (문자열 ISO 비교로 충분)
    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    total = len(items)
    window = items[(page - 1) * size : (page - 1) * size + size]
    return {"items": window, "total": total, "page": page, "size": size}


# --- 8번 GET /contracts/{id} — 상세 (지시서 §6 8번, 세션 필요 §4.7) ---
from app.deps import require_session  # noqa: E402
from app.errors import NotFound  # noqa: E402
from app.services.territory import end_inclusive_from_upper  # noqa: E402
from app.schemas.detail import (  # noqa: E402
    Authority,
    ContractDetail,
    HistoryRow,
    RightRow,
)


@router.get("/contracts/{contract_id}", response_model=ContractDetail)
def get_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    _team: str = Depends(require_session),
) -> ContractDetail:
    """요청 하나로 카드 4개+버전 이력을 모두 채운다. 정상/충돌 동일 스키마(§6 8번)."""
    c = db.execute(
        text("SELECT * FROM master.contract WHERE id=:c"), {"c": contract_id}
    ).mappings().first()
    if c is None:
        raise NotFound("계약을 찾을 수 없습니다")

    # 정본은 current_history_id, 없으면(충돌 등) 최신 이력
    hist = None
    if c["current_history_id"]:
        hist = db.execute(
            text("SELECT * FROM master.contract_history WHERE id=:h"),
            {"h": c["current_history_id"]},
        ).mappings().first()
    if hist is None:
        hist = db.execute(
            text(
                "SELECT * FROM master.contract_history WHERE contract_id=:c "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": contract_id},
        ).mappings().first()

    team_name = db.execute(
        text("SELECT name FROM master.team WHERE id=:t"), {"t": c["team_id"]}
    ).scalar()

    # rights: active + conflicted (terminated 제외)
    rrows = db.execute(
        text(
            "SELECT id, lineage_id, content_asset_id, territory, rights_type, "
            "       lower(period) AS lo, upper(period) AS hi, exclusivity, status, "
            "       conditions_raw, confidence, evidence "
            "FROM master.rights_grant "
            "WHERE contract_id=:c AND status IN ('active','conflicted') "
            "ORDER BY id"
        ),
        {"c": contract_id},
    ).mappings().all()
    rights = [
        RightRow(
            rights_grant_id=r["id"], lineage_id=r["lineage_id"],
            content_asset_id=r["content_asset_id"], territory=r["territory"],
            rights_type=r["rights_type"], period_start=r["lo"],
            period_end=end_inclusive_from_upper(r["hi"]), exclusivity=r["exclusivity"],
            status=r["status"], conditions_raw=r["conditions_raw"],
            confidence=float(r["confidence"]) if r["confidence"] is not None else None,
            evidence=r["evidence"],
        )
        for r in rrows
    ]

    hrows = db.execute(
        text(
            "SELECT id, version, status, created_at, conflict_report "
            "FROM master.contract_history WHERE contract_id=:c ORDER BY created_at"
        ),
        {"c": contract_id},
    ).mappings().all()
    history = [
        HistoryRow(
            id=h["id"], version=h["version"], status=h["status"],
            created_at=h["created_at"], conflict_report=h["conflict_report"],
        )
        for h in hrows
    ]

    latest_status = hrows[-1]["status"] if hrows else None
    has_conflict = latest_status == "conflicted"
    conflict_report = None
    if has_conflict:
        conflict_report = hrows[-1]["conflict_report"]

    agg = db.execute(
        text(
            "SELECT min(lower(period)) AS lo, max(upper(period)) AS hi "
            "FROM master.rights_grant WHERE contract_id=:c AND status='active'"
        ),
        {"c": contract_id},
    ).first()
    state, days = compute_display(agg[0] if agg else None, agg[1] if agg else None)

    src = hist or c
    return ContractDetail(
        id=c["id"],
        title=(src["title"] if src and src["title"] else c["title"]),
        counterparty=(src["counterparty"] if src and src["counterparty"] else c["counterparty"]),
        contract_type=c["contract_type"],
        status=c["status"],
        signed_date=(src["signed_date"] if src else c["signed_date"]),
        lang=(src["lang"] if src else c["lang"]),
        amount=float(src["amount"]) if src and src["amount"] is not None else None,
        currency=(src["currency"] if src else c["currency"]),
        has_conflict=has_conflict,
        conflict_report=conflict_report,
        display_state=state,
        days_to_expiry=days,
        service_title=None,
        grantor=team_name,
        authority=Authority(),
        rights=rights,
        history=history,
    )

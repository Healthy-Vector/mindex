"""계약 라우터 — 5·6·7·8·9·11 (P2-DB 정렬).

판정은 DB 함수(validate_rights_batch/save_rights_batch)가 한다. 충돌은 에러가
아니라 정상 응답이며(§4.3), conflict_report(P2 형태)를 그대로 통과시킨다.
team_id 는 도메인에 전파되지 않는다(단일사 온프렘).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.deps import require_session
from app.errors import AlreadyCancelled, NoSourceFile, NotFound
from app.schemas.contracts import (
    CancelResponse,
    ConfirmRequest,
    ConfirmResponse,
    VerifyRequest,
    VerifyResponse,
)
from app.schemas.detail import (
    Authority,
    ContentAssetRef,
    ContractDetail,
    HistoryRow,
    IpBrief,
    RightRow,
)
from app.schemas.listing import ContractListItem, ProcessingListItem
from app.services import conflict as conflict_svc
from app.services.display import compute_display
from app.services.territory import end_inclusive_from_upper

router = APIRouter()


# ── 5번 검증 ─────────────────────────────────────────────────
@router.post("/contracts/verify", response_model=VerifyResponse)
def verify_contract(body: VerifyRequest, db: Session = Depends(get_db)) -> VerifyResponse:
    """DB validate_rights_batch() 호출. DB 에 아무것도 남기지 않는다. 충돌도 200(§4.3)."""
    return VerifyResponse.model_validate(conflict_svc.validate_batch(db, body))


# ── 6번 확정 저장 ────────────────────────────────────────────
@router.post("/contracts", response_model=ConfirmResponse, status_code=201)
def confirm_contract(body: ConfirmRequest, db: Session = Depends(get_db)) -> ConfirmResponse:
    """DB save_rights_batch() 호출. 성공/충돌 모두 201, conflictReport 로 구분(§4.3)."""
    return ConfirmResponse.model_validate(conflict_svc.save_batch(db, body))


# ── 7번 목록 ─────────────────────────────────────────────────
def _contract_meta(db: Session, contract_id: int):
    agg = db.execute(
        text(
            "SELECT min(lower(period)) lo, max(upper(period)) hi "
            "FROM rights_grant WHERE contract_id=:c AND status='active'"
        ),
        {"c": contract_id},
    ).first()
    return compute_display(agg[0] if agg else None, agg[1] if agg else None)


@router.get("/contracts")
def list_contracts(
    include_processing: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    size: Optional[int] = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
):
    s = get_settings()
    size = size or s.page_size_default

    rows = db.execute(
        text(
            "SELECT c.id, c.grantor, c.grantee, c.status, c.signed_date, c.created_at, "
            "       lh.file_name AS title, lh.status AS latest_status "
            "FROM contract c "
            "LEFT JOIN LATERAL ("
            "  SELECT file_name, status FROM contract_history "
            "  WHERE contract_id=c.id ORDER BY version DESC LIMIT 1"
            ") lh ON true "
            "ORDER BY c.created_at DESC"
        )
    ).mappings().all()

    items: list[dict] = []
    for c in rows:
        state, days = _contract_meta(db, c["id"])
        items.append(
            ContractListItem(
                id=c["id"], title=c["title"], grantor=c["grantor"], grantee=c["grantee"],
                status=c["status"], has_conflict=(c["latest_status"] == "conflicted"),
                display_state=state, days_to_expiry=days, service_title=None,
                signed_date=c["signed_date"], created_at=c["created_at"],
            ).model_dump(by_alias=True, mode="json")
        )

    if include_processing:
        procs = db.execute(
            text(
                "SELECT j.tmpid, j.status, j.stage, j.reason, j.created_at "
                "FROM staging.extract_job j "
                "WHERE j.status IN ('QUEUED','RUNNING','FAILED') ORDER BY j.created_at DESC"
            )
        ).mappings().all()
        for p in procs:
            items.append(
                ProcessingListItem(
                    tmpid=str(p["tmpid"]), status=p["status"], stage=p["stage"],
                    filename=None, reason=p["reason"], created_at=p["created_at"],
                ).model_dump(by_alias=True, mode="json")
            )

    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    total = len(items)
    window = items[(page - 1) * size : (page - 1) * size + size]
    return {"items": window, "total": total, "page": page, "size": size}


# ── 8번 상세 (세션 필요) ─────────────────────────────────────
@router.get("/contracts/{contract_id}", response_model=ContractDetail)
def get_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    _team: str = Depends(require_session),
) -> ContractDetail:
    c = db.execute(
        text("SELECT * FROM contract WHERE id=:c"), {"c": contract_id}
    ).mappings().first()
    if c is None:
        raise NotFound("계약을 찾을 수 없습니다")

    histories = db.execute(
        text(
            "SELECT id, version, document_kind, status, file_name, uploaded_at, conflict_report "
            "FROM contract_history WHERE contract_id=:c ORDER BY version"
        ),
        {"c": contract_id},
    ).mappings().all()
    cur_id = c["current_history_id"]
    hrows = [
        HistoryRow(
            history_id=h["id"], version=h["version"], document_kind=h["document_kind"],
            status=h["status"], file_name=h["file_name"], uploaded_at=h["uploaded_at"],
            is_current=(h["id"] == cur_id), conflict_report=h["conflict_report"],
        )
        for h in histories
    ]
    latest = histories[-1] if histories else None
    has_conflict = bool(latest and latest["status"] == "conflicted")
    conflict_report = latest["conflict_report"] if has_conflict else None
    title = None
    if cur_id:
        cur = next((h for h in histories if h["id"] == cur_id), None)
        title = cur["file_name"] if cur else None
    if title is None and latest:
        title = latest["file_name"]

    rrows = db.execute(
        text(
            "SELECT rg.id, rg.lineage_id, rg.status, rg.content_asset_id, "
            "       ca.title AS asset_title, ca.scope_type, "
            "       ip.id AS ip_id, ip.title AS ip_title, ip.kind AS ip_kind, "
            "       rg.legal_right, lr.name_ko AS lr_label, "
            "       rg.exploitation_mode, em.name_ko AS em_label, "
            "       rg.territory, cl.label AS terr_label, "
            "       lower(rg.period) lo, upper(rg.period) hi, "
            "       rg.exclusivity, rg.evidence, rg.conditions_raw, "
            "       rg.created_at, rg.terminated_at, rg.terminated_reason "
            "FROM rights_grant rg "
            "JOIN content_asset ca ON ca.id=rg.content_asset_id "
            "JOIN ip ON ip.id=ca.ip_id "
            "LEFT JOIN legal_right lr ON lr.code=rg.legal_right "
            "LEFT JOIN exploitation_mode em ON em.code=rg.exploitation_mode "
            "LEFT JOIN country_label cl ON cl.country_code=rg.territory AND cl.lang='ko' "
            "WHERE rg.contract_id=:c AND rg.status='active' ORDER BY rg.id"
        ),
        {"c": contract_id},
    ).mappings().all()

    rights: list[RightRow] = []
    ips: list[IpBrief] = []
    seen_ip: set[int] = set()
    for r in rrows:
        rights.append(
            RightRow(
                rights_grant_id=r["id"], lineage_id=r["lineage_id"], status=r["status"],
                content_asset=ContentAssetRef(
                    content_asset_id=r["content_asset_id"], ip_id=r["ip_id"],
                    ip_title=r["ip_title"], ip_kind=r["ip_kind"],
                    scope_type=r["scope_type"], title=r["asset_title"],
                ),
                legal_right=r["legal_right"], legal_right_label=r["lr_label"],
                exploitation_mode=r["exploitation_mode"], exploitation_mode_label=r["em_label"],
                territory=r["territory"], territory_label=r["terr_label"],
                period_start=r["lo"], period_end=end_inclusive_from_upper(r["hi"]),
                exclusivity=r["exclusivity"], evidence=r["evidence"],
                conditions_raw=r["conditions_raw"], created_at=r["created_at"],
                terminated_at=r["terminated_at"], terminated_reason=r["terminated_reason"],
            )
        )
        if r["ip_id"] is not None and r["ip_id"] not in seen_ip:
            seen_ip.add(r["ip_id"])
            ips.append(IpBrief(ip_id=r["ip_id"], title=r["ip_title"], kind=r["ip_kind"]))

    state, days = _contract_meta(db, contract_id)
    cur_ver = next((h["version"] for h in histories if h["id"] == cur_id), None)

    return ContractDetail(
        id=c["id"], title=title, grantor=c["grantor"], grantee=c["grantee"], status=c["status"],
        signed_date=c["signed_date"], lang=c["lang"],
        amount=float(c["amount"]) if c["amount"] is not None else None, currency=c["currency"],
        current_version=cur_ver, has_conflict=has_conflict, conflict_report=conflict_report,
        display_state=state, days_to_expiry=days, service_title=None,
        authority=Authority(),
        ips=ips, rights=rights, histories=hrows,
    )


# ── 9번 원본 파일 (세션 필요) ────────────────────────────────
@router.get("/contracts/{contract_id}/file")
def get_contract_file(
    contract_id: int,
    db: Session = Depends(get_db),
    _team: str = Depends(require_session),
):
    fp = db.execute(
        text(
            "SELECT COALESCE("
            "  (SELECT file_path FROM contract_history WHERE id=c.current_history_id), "
            "  (SELECT file_path FROM contract_history WHERE contract_id=c.id ORDER BY version DESC LIMIT 1)"
            ") FROM contract c WHERE c.id=:c"
        ),
        {"c": contract_id},
    ).scalar()
    if not fp or not os.path.isfile(fp):
        raise NoSourceFile("원본 파일을 찾을 수 없습니다")
    return FileResponse(fp, media_type="application/pdf", filename=os.path.basename(fp))


# ── 11번 계약 종료 (세션 필요) ───────────────────────────────
@router.post("/contracts/{contract_id}/cancel", response_model=CancelResponse)
def cancel_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    _team: str = Depends(require_session),
) -> CancelResponse:
    """contract.status='cancelled' 로 바꾸면 트리거(release_contract_rights)가
    active 권리를 terminated 로 내린다(§5.7 대응, P2-DB 12번 트리거)."""
    current = db.execute(
        text("SELECT status FROM contract WHERE id=:c FOR UPDATE"),
        {"c": contract_id},
    ).scalar()
    if current is None:
        db.rollback()
        raise NotFound("계약을 찾을 수 없습니다")
    if current == "cancelled":
        db.rollback()
        raise AlreadyCancelled("이미 종료된 계약입니다")

    active = db.execute(
        text("SELECT count(*) FROM rights_grant WHERE contract_id=:c AND status='active'"),
        {"c": contract_id},
    ).scalar_one()
    terminated_at = db.execute(
        text("UPDATE contract SET status='cancelled', updated_at=now() "
             "WHERE id=:c AND status<>'cancelled' RETURNING updated_at"),
        {"c": contract_id},
    ).scalar()
    if terminated_at is None:
        db.rollback()
        raise AlreadyCancelled("이미 종료된 계약입니다")
    db.commit()
    return CancelResponse(
        contract_id=contract_id,
        status="cancelled",
        terminated_rights=int(active),
        terminated_at=terminated_at,
    )

"""검증·확정 — P2-DB 판정 함수의 얇은 래퍼 (P2-DB D-27/D-30 정렬).

판정은 전적으로 DB가 한다:
- 5번 verify  → validate_rights_batch()  (내부 서브트랜잭션에서 시도 후 강제 롤백)
- 6번 confirm → save_rights_batch()       (세대 전환·lineage 승계·conflict_report 포함)
Python 쪽에 겹침 판정 로직을 두지 않는다. 2축(legal_right × exploitation_mode)
nested-set span 비교, 비독점 XOR 판정, conflict_report 생성 모두 DB 함수/트리거 소관.

conflict_report(jsonb)는 P2 형태 그대로 통과시킨다:
{ constraint_name, exception_detail, conflicts:[{incoming{legal_right,exploitation_mode,
  territory,period,exclusivity}, existing_grant_id, existing_contract_id, overlap_period,
  legal_right_relation, exploitation_mode_relation, blocking_layer}] }
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.errors import AlreadyConfirmed, ExtractNotReady, NotFound, ValidationFailed
from app.services.territory import expand_territories, to_daterange_literal


def build_rights_json(db: Session, rights: list) -> str:
    """RightIn 목록 → save/validate_rights_batch 가 받는 jsonb 배열 문자열.

    rights 1건 × territories N개 → N개 원소(그룹 코드는 국가로 전개).
    [) 기간 변환은 territory 헬퍼 한 곳. evidence 는 그대로 통과(quote 필수는 DB CHECK).
    """
    arr: list[dict[str, Any]] = []
    for r in rights:
        for cc in expand_territories(db, r.territories):
            arr.append(
                {
                    "content_asset_id": r.content_asset_id,  # None 이면 DB 가 기본 asset 사용
                    "territory": cc,
                    "legal_right": r.legal_right,
                    "exploitation_mode": r.exploitation_mode,
                    "period": to_daterange_literal(r.period.start, r.period.end),
                    "exclusivity": r.exclusivity,
                    "evidence": r.evidence,
                    "conditions_raw": r.conditions_raw,
                }
            )
    _reject_internal_overlap(db, arr)
    return json.dumps(arr, ensure_ascii=False, default=str)


def _reject_internal_overlap(db: Session, rows: list[dict[str, Any]]) -> None:
    """P2 EXCLUDE가 의도적으로 제외하는 같은 계약 내부의 중복을 선제 차단한다."""
    if len(rows) < 2:
        return
    lr = {
        r["code"]: (r["lft"], r["rgt"])
        for r in db.execute(text("SELECT code, lft, rgt FROM legal_right")).mappings()
    }
    em = {
        r["code"]: (r["lft"], r["rgt"])
        for r in db.execute(text("SELECT code, lft, rgt FROM exploitation_mode")).mappings()
    }

    def span_overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return a[0] <= b[1] and b[0] <= a[1]

    def period_bounds(value: str) -> tuple[str, str]:
        lo, hi = value[1:-1].split(",", 1)
        return lo, hi

    for i, left in enumerate(rows):
        for j, right in enumerate(rows[i + 1 :], start=i + 1):
            if left["content_asset_id"] != right["content_asset_id"]:
                continue
            if left["territory"] != right["territory"]:
                continue
            if left["legal_right"] not in lr or right["legal_right"] not in lr:
                continue
            if left["exploitation_mode"] not in em or right["exploitation_mode"] not in em:
                continue
            if not span_overlaps(lr[left["legal_right"]], lr[right["legal_right"]]):
                continue
            if not span_overlaps(em[left["exploitation_mode"]], em[right["exploitation_mode"]]):
                continue
            l_start, l_end = period_bounds(left["period"])
            r_start, r_end = period_bounds(right["period"])
            if not (l_start < r_end and r_start < l_end):
                continue
            if left["exclusivity"] == right["exclusivity"] == "non_exclusive":
                continue
            raise ValidationFailed(
                "같은 요청 안의 권리 범위가 서로 중복됩니다",
                details={"leftIndex": i, "rightIndex": j},
            )


def validate_batch(db: Session, req) -> dict[str, Any]:
    """5번 — validate_rights_batch() 호출. DB 가 내부에서 롤백하므로 아무것도 남지 않는다."""
    try:
        _validate_request_refs(db, req)
        rights_json = build_rights_json(db, req.rights)
        row = db.execute(
            text(
                "SELECT batch_result, constraint_name, conflict_report "
                "FROM validate_rights_batch("
                "  :contract_id, :grantor, :grantee, :ip_id, :file_name, :file_path, :file_hash,"
                "  CAST(:rights AS jsonb), :mime_type, :raw_text, CAST(:document_kind AS contract_document_kind))"
            ),
            {
                "contract_id": req.contract_id,
                "grantor": req.grantor,
                "grantee": req.grantee,
                "ip_id": req.ip_id,
                "file_name": req.file_name,
                "file_path": req.file_path,
                "file_hash": req.file_hash,
                "rights": rights_json,
                "mime_type": req.mime_type or "application/pdf",
                "raw_text": req.raw_text,
                "document_kind": req.document_kind or "draft",
            },
        ).mappings().first()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_clean_db_error(ex)) from ex
    finally:
        # validate 는 DB 함수가 자체 롤백하지만, 바깥 트랜잭션도 확실히 정리한다.
        db.rollback()

    return {
        "batch_result": row["batch_result"],
        "has_conflict": row["batch_result"] == "CONFLICTED",
        "constraint_name": row["constraint_name"],
        "conflict_report": row["conflict_report"],
    }


def save_batch(db: Session, req) -> dict[str, Any]:
    """6번 — save_rights_batch() 호출 후 커밋. 성공/충돌 모두 커밋된다(§D-30)."""
    try:
        _validate_request_refs(db, req, lock_contract=True)
        _validate_source_tmpid(db, req.source_tmpid)
        rights_json = build_rights_json(db, req.rights)
        chunks_json = (
            json.dumps(
                [
                    {
                        "clause_no": c.clause_no,
                        "chunk_text": c.chunk_text,
                        "lang": c.lang,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "embedding": ("[" + ",".join(str(float(x)) for x in c.embedding) + "]")
                        if c.embedding
                        else None,
                    }
                    for c in req.chunks
                ],
                ensure_ascii=False,
            )
            if getattr(req, "chunks", None)
            else None
        )
        row = db.execute(
            text(
                "SELECT batch_result, out_contract_id, out_history_id, constraint_name, conflict_report "
                "FROM save_rights_batch("
                "  :contract_id, :grantor, :grantee, :ip_id, :file_name, :file_path, :file_hash,"
                "  CAST(:rights AS jsonb), :mime_type, :raw_text, CAST(:chunks AS jsonb),"
                "  CAST(:document_kind AS contract_document_kind), CAST(:source_tmpid AS uuid))"
            ),
            {
                "contract_id": req.contract_id,
                "grantor": req.grantor,
                "grantee": req.grantee,
                "ip_id": req.ip_id,
                "file_name": req.file_name,
                "file_path": req.file_path,
                "file_hash": req.file_hash,
                "rights": rights_json,
                "mime_type": req.mime_type or "application/pdf",
                "raw_text": req.raw_text,
                "chunks": chunks_json,
                "document_kind": req.document_kind or "final",
                "source_tmpid": str(req.source_tmpid) if req.source_tmpid else None,
            },
        ).mappings().first()
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        if _is_source_tmpid_duplicate(ex):
            raise AlreadyConfirmed("이미 확정에 사용된 sourceTmpid입니다") from ex
        raise ValidationFailed(_clean_db_error(ex)) from ex

    return {
        "batch_result": row["batch_result"],
        "contract_id": row["out_contract_id"],
        "contract_history_id": row["out_history_id"],
        "has_conflict": row["batch_result"] == "CONFLICTED",
        "constraint_name": row["constraint_name"],
        "conflict_report": row["conflict_report"],
    }


def terminate_grant(db: Session, grant_id: int, reason: str, note: Optional[str] = None) -> None:
    """단건 권리 수동 종료 — terminate_rights_grant() (waiver/cancelled)."""
    try:
        db.execute(
            text("SELECT terminate_rights_grant(:g, CAST(:r AS terminated_reason_kind), :n)"),
            {"g": grant_id, "r": reason, "n": note},
        )
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_clean_db_error(ex)) from ex


def _validate_request_refs(db: Session, req, *, lock_contract: bool = False) -> None:
    """P2 함수가 의미상 보장하지 않는 contract/IP/asset 소속을 API 경계에서 확인한다."""
    if req.contract_id is not None:
        suffix = " FOR UPDATE" if lock_contract else ""
        found = db.execute(
            text("SELECT id FROM contract WHERE id=:c" + suffix),
            {"c": req.contract_id},
        ).scalar()
        if found is None:
            raise NotFound("계약을 찾을 수 없습니다")

    asset_ids = {r.content_asset_id for r in req.rights if r.content_asset_id is not None}
    if req.ip_id is None:
        if asset_ids:
            raise ValidationFailed("ipId가 없으면 contentAssetId를 지정할 수 없습니다")
        return

    if db.execute(text("SELECT id FROM ip WHERE id=:i"), {"i": req.ip_id}).scalar() is None:
        raise NotFound("IP를 찾을 수 없습니다")
    if not asset_ids:
        return
    rows = db.execute(
        text("SELECT id, ip_id FROM content_asset WHERE id = ANY(:ids)"),
        {"ids": list(asset_ids)},
    ).mappings().all()
    by_id = {r["id"]: r["ip_id"] for r in rows}
    for asset_id in asset_ids:
        if asset_id not in by_id:
            raise NotFound(f"contentAssetId {asset_id}를 찾을 수 없습니다")
        if by_id[asset_id] != req.ip_id:
            raise ValidationFailed(
                "contentAssetId가 요청한 ipId에 속하지 않습니다",
                details={"contentAssetId": asset_id, "ipId": req.ip_id},
            )


def _validate_source_tmpid(db: Session, source_tmpid) -> None:
    if source_tmpid is None:
        return
    used_by = db.execute(
        text("SELECT id FROM contract WHERE source_tmpid=:t FOR UPDATE"),
        {"t": str(source_tmpid)},
    ).scalar()
    if used_by is not None:
        raise AlreadyConfirmed(
            "이미 확정에 사용된 sourceTmpid입니다",
            details={"contractId": int(used_by)},
        )
    extracted = db.execute(
        text(
            "SELECT j.status, r.payload FROM staging.extract_job j "
            "JOIN staging.extract_result r ON r.tmpid=j.tmpid "
            "WHERE j.tmpid=:t FOR UPDATE OF j"
        ),
        {"t": str(source_tmpid)},
    ).mappings().first()
    status = extracted["status"] if extracted else None
    if status != "DONE":
        raise ExtractNotReady(
            "추출 결과가 저장된 DONE sourceTmpid만 확정할 수 있습니다",
            details={"status": status},
        )


def _clean_db_error(ex: Exception) -> str:
    msg = str(getattr(ex, "orig", ex))
    # psycopg 에러 첫 줄만 노출(CONTEXT/스택 제거)
    return msg.strip().splitlines()[0][:300] if msg.strip() else "요청 처리에 실패했습니다"


def _is_source_tmpid_duplicate(ex: DBAPIError) -> bool:
    orig = getattr(ex, "orig", None)
    code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    constraint = getattr(getattr(orig, "diag", None), "constraint_name", "") or ""
    return code == "23505" and "source_tmpid" in constraint

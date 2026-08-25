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

from app.errors import ValidationFailed
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
    return json.dumps(arr, ensure_ascii=False, default=str)


def validate_batch(db: Session, req) -> dict[str, Any]:
    """5번 — validate_rights_batch() 호출. DB 가 내부에서 롤백하므로 아무것도 남지 않는다."""
    rights_json = build_rights_json(db, req.rights)
    try:
        row = db.execute(
            text(
                "SELECT batch_result, constraint_name, conflict_report "
                "FROM validate_rights_batch("
                "  :contract_id, :counterparty, :ip_id, :file_name, :file_path, :file_hash,"
                "  CAST(:rights AS jsonb), :mime_type, :raw_text, CAST(:document_kind AS contract_document_kind))"
            ),
            {
                "contract_id": req.contract_id,
                "counterparty": req.counterparty,
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
    rights_json = build_rights_json(db, req.rights)
    chunks_json = (
        json.dumps(
            [
                {
                    "clause_no": c.clause_no,
                    "chunk_text": c.chunk_text,
                    "lang": c.lang,
                    "page": c.page,
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
    try:
        row = db.execute(
            text(
                "SELECT batch_result, out_contract_id, out_history_id, constraint_name, conflict_report "
                "FROM save_rights_batch("
                "  :contract_id, :counterparty, :ip_id, :file_name, :file_path, :file_hash,"
                "  CAST(:rights AS jsonb), :mime_type, :raw_text, CAST(:chunks AS jsonb),"
                "  CAST(:document_kind AS contract_document_kind), CAST(:source_tmpid AS uuid))"
            ),
            {
                "contract_id": req.contract_id,
                "counterparty": req.counterparty,
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


def _clean_db_error(ex: Exception) -> str:
    msg = str(getattr(ex, "orig", ex))
    # psycopg 에러 첫 줄만 노출(CONTEXT/스택 제거)
    return msg.strip().splitlines()[0][:300] if msg.strip() else "요청 처리에 실패했습니다"

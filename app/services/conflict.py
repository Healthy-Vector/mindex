"""검증·확정 — P2-DB 판정 함수의 얇은 래퍼 (P2-DB D-27/D-30 정렬).

판정은 전적으로 DB가 한다:
- 5번 verify  → validate_rights_batch()  (내부 서브트랜잭션에서 시도 후 강제 롤백)
- 6번 confirm → save_rights_batch()       (세대 전환·lineage 승계·conflict_report 포함)
Python 쪽에 겹침 판정 로직을 두지 않는다. 2축(legal_right × exploitation_mode)
nested-set span 비교, 비독점 XOR 판정, conflict_report 생성 모두 DB 함수/트리거 소관.

conflict_report(jsonb)는 내용은 유지하고 API 응답 키만 camelCase로 변환한다:
{ constraintName, exceptionDetail, conflicts:[{incoming{legalRight,exploitationMode,
  territory,period,exclusivity}, existingGrantId, existingContractId, overlapPeriod,
  legalRightRelation, exploitationModeRelation, blockingLayer}] }

TODO: 충돌 화면 버전업 때 LLM 한 줄 설명의 API·저장·UI 계약을 함께 추가한다.
현재 응답에는 설명 필드를 추가하지 않는다.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.errors import AlreadyConfirmed, ExtractNotReady, NotFound, ValidationFailed
from app.schemas.common import camelize_json_keys
from app.services import staging_edit
from app.services.storage import sha256_hex, write_contract_pdf
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


def apply_staging_edit(db: Session, req) -> list:
    """⑥ — 화면이 보낸 patch를 staging에 반영하고 판정에 쓸 권리 목록을 돌려준다 (D-34).

    **여기서 커밋한다.** 뒤따르는 판정은 성공이든 충돌이든 롤백되지만 사용자의
    수정본은 남아야 한다 — 확정(⑧)이 같은 값을 읽어 저장하기 때문이다.
    """
    row = staging_edit.load_done_extraction(db, req.source_tmpid)
    payload, dto = staging_edit.apply_patch(db, row["payload"], req.patch)
    staging_edit.persist_edited(db, req.source_tmpid, payload)
    db.commit()
    return staging_edit.rights_from_dto(dto)


def _staging_file_fields(db: Session, source_tmpid) -> tuple[str, str, bytes]:
    """확정 시 쓸 원본 파일명·해시·바이트. 경로는 세대 id가 정해진 뒤에 만든다."""
    row = db.execute(
        text("SELECT filename, data FROM staging.pdf_blob WHERE tmpid=:t"),
        {"t": str(source_tmpid)},
    ).mappings().first()
    if row is None:
        raise ExtractNotReady(
            "원본 PDF를 찾을 수 없습니다", details={"tmpId": str(source_tmpid)}
        )
    data = bytes(row["data"])
    return (row["filename"] or "contract.pdf"), sha256_hex(data), data


def validate_batch(db: Session, req) -> dict[str, Any]:
    """5번 — validate_rights_batch() 호출. 판정 결과는 DB가 내부에서 롤백한다.

    D-34로 staging 경로가 생겼다. `tmpId`가 오면 수정본을 먼저 staging에
    반영·커밋한 뒤 **저장된 값으로** 판정한다 — 판정만 롤백되고 수정본은 남는다.
    """
    if req.source_tmpid is not None:
        rights = apply_staging_edit(db, req)
    else:
        rights = req.rights
    try:
        _validate_request_refs(db, req, rights)
        rights_json = build_rights_json(db, rights)
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
                # 판정은 통째로 롤백되므로 파일 메타는 NOT NULL만 채우면 된다.
                # 실제 값은 확정(⑧)에서 서버가 staging 원본으로 채운다(D-34).
                "file_name": req.file_name or "contract.pdf",
                "file_path": req.file_path or "pending",
                "file_hash": req.file_hash or "pending",
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
        "conflict_report": camelize_json_keys(row["conflict_report"]),
    }


def save_batch(db: Session, req) -> dict[str, Any]:
    """6번 — save_rights_batch() 호출 후 커밋. 성공/충돌 모두 커밋된다(§D-30).

    D-34로 B안이 코드에 들어왔다. `tmpId`가 오면 화면이 rights를 되보내지
    않아도 되고, 서버가 `staging.extract_result`의 수정본(`edited`)을 읽어
    저장 배치를 만든다. 원본 PDF도 여기서 서버 저장소로 옮기고 경로를 기록한다.
    """
    pdf_data: Optional[bytes] = None
    if req.source_tmpid is not None:
        staged = staging_edit.load_done_extraction(db, req.source_tmpid)
        dto = staging_edit.current_dto(db, staged["payload"])
        rights = req.rights or staging_edit.rights_from_dto(dto)
        file_name, file_hash, pdf_data = _staging_file_fields(db, req.source_tmpid)
    else:
        rights = req.rights
        file_name, file_hash = req.file_name, req.file_hash

    try:
        _validate_request_refs(db, req, rights, lock_contract=True)
        _validate_source_tmpid(db, req.source_tmpid)
        rights_json = build_rights_json(db, rights)
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
                "file_name": file_name,
                # staging 경로에서는 세대 id가 정해진 뒤에 실제 경로로 UPDATE한다.
                "file_path": req.file_path if pdf_data is None else "pending",
                "file_hash": file_hash,
                "rights": rights_json,
                "mime_type": req.mime_type or "application/pdf",
                "raw_text": req.raw_text,
                "chunks": chunks_json,
                "document_kind": req.document_kind or "final",
                "source_tmpid": str(req.source_tmpid) if req.source_tmpid else None,
            },
        ).mappings().first()
        # /contracts is the terminal step for an extraction result.  Both an
        # applied batch and a conflicted history are persisted by the DB
        # function, so either outcome consumes the staging job.
        if req.source_tmpid is not None:
            # D-34 — 원본 PDF를 서버 저장소로 옮기고 경로를 세대 행에 기록한다.
            # 세대 id는 지금 막 정해졌으므로 INSERT 시점에는 알 수 없었다.
            # 충돌(CONFLICTED) 세대도 행 자체는 남으므로 똑같이 파일을 둔다.
            relative = write_contract_pdf(
                pdf_data, row["out_contract_id"], row["out_history_id"]
            )
            db.execute(
                text("UPDATE contract_history SET file_path=:p WHERE id=:h"),
                {"p": relative, "h": row["out_history_id"]},
            )
            db.execute(
                text(
                    "UPDATE staging.extract_job SET consumed_at=now() "
                    "WHERE tmpid=:tmpid AND status='DONE'"
                ),
                {"tmpid": str(req.source_tmpid)},
            )
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        if _is_source_tmpid_duplicate(ex):
            raise AlreadyConfirmed("이미 확정에 사용된 tmpId입니다") from ex
        raise ValidationFailed(_clean_db_error(ex)) from ex

    return {
        "batch_result": row["batch_result"],
        "contract_id": row["out_contract_id"],
        "contract_history_id": row["out_history_id"],
        "has_conflict": row["batch_result"] == "CONFLICTED",
        "constraint_name": row["constraint_name"],
        "conflict_report": camelize_json_keys(row["conflict_report"]),
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


def _validate_request_refs(db: Session, req, rights: list, *, lock_contract: bool = False) -> None:
    """P2 함수가 의미상 보장하지 않는 contract/IP/asset 소속을 API 경계에서 확인한다.

    `rights`는 요청 body가 아니라 **판정에 실제로 쓸 목록**을 받는다 — staging
    경로에서는 저장된 수정본에서 나오기 때문이다(D-34).
    """
    if req.contract_id is not None:
        suffix = " FOR UPDATE" if lock_contract else ""
        found = db.execute(
            text("SELECT id FROM contract WHERE id=:c" + suffix),
            {"c": req.contract_id},
        ).scalar()
        if found is None:
            raise NotFound("계약을 찾을 수 없습니다")

    asset_ids = {r.content_asset_id for r in rights if r.content_asset_id is not None}
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
            "이미 확정에 사용된 tmpId입니다",
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
            "추출 결과가 저장된 DONE tmpId만 확정할 수 있습니다",
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

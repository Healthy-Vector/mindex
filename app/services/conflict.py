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
                    "evidence": {
                        "legal_right": r.evidence.get(
                            "legal_right",
                            r.evidence.get("legalRight"),
                        ),
                        "exploitation_mode": r.evidence.get(
                            "exploitation_mode",
                            r.evidence.get("exploitationMode"),
                        ),
                        "territory": r.evidence.get("territory"),
                        "period": r.evidence.get("period"),
                        "exclusivity": r.evidence.get("exclusivity"),
                    },
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


def apply_staging_edit(db: Session, req) -> tuple[list, dict[str, Any]]:
    """⑥ — 화면이 보낸 수정분을 staging에 반영하고 ``(권리 목록, DTO)``를 돌려준다 (D-34).

    **여기서 커밋한다.** 뒤따르는 판정은 성공이든 충돌이든 롤백되지만 사용자의
    수정본은 남아야 한다 — 확정(⑧)이 같은 값을 읽어 저장하기 때문이다.

    검증과 확정이 **같은 경로를 쓴다.** 예전에는 검증만 저장값으로 판정하고 확정은
    요청 body의 `rights`를 우선해서, 화면이 둘 다 보내면 검사한 값과 저장하는 값이
    갈라질 수 있었다.
    """
    row = staging_edit.load_done_extraction(db, req.source_tmpid)

    patch = dict(req.patch) if req.patch else {}
    if req.rights is not None:
        # 화면이 rights를 통째로 보내는 건 patch의 배열 전체 교체와 같은 뜻이다.
        # patch에 접어 넣어야 staging에도 남고 확정이 같은 값을 읽는다.
        patch["rights"] = [r.model_dump(by_alias=True, mode="json") for r in req.rights]

    payload, dto = staging_edit.apply_patch(db, row["payload"], patch or None)
    staging_edit.persist_edited(db, req.source_tmpid, payload)
    db.commit()
    return staging_edit.rights_from_dto(dto), dto


def _staging_context(db: Session, source_tmpid) -> dict[str, Any]:
    """업로드 시점에 `extract_job`에 저장해 둔 맥락 (D-37)."""
    row = db.execute(
        text(
            "SELECT mode, contract_id, ip_id FROM staging.extract_job WHERE tmpid=:t"
        ),
        {"t": str(source_tmpid)},
    ).mappings().first()
    return dict(row) if row else {}


def _resolve_context(db: Session, req, *, default_kind: str) -> dict[str, Any]:
    """`contractId`·`ipId`·`documentKind`를 정한다 — 요청이 우선, 없으면 업로드 맥락.

    화면이 아무 상태도 안 들고 있어도(목록의 "처리 중" 클릭, 브라우저 재접속)
    `tmpId` 하나로 동작하게 하는 게 목적이다(D-37).
    """
    job = _staging_context(db, req.source_tmpid) if req.source_tmpid is not None else {}
    return {
        "contract_id": req.contract_id if req.contract_id is not None else job.get("contract_id"),
        "ip_id": req.ip_id if req.ip_id is not None else job.get("ip_id"),
        "document_kind": req.document_kind or job.get("mode") or default_kind,
    }


def _resolve_parties(req, dto: Optional[dict[str, Any]]) -> tuple[str, str]:
    """계약 당사자를 정한다 — 요청이 우선, 없으면 추출 결과에서 가져온다 (D-36).

    `parties[]`에 GRANTOR·GRANTEE가 이미 파싱돼 있으므로 화면이 다시 보낼 필요가
    없다. 화면이 고쳤다면 patch로 `contractInfo.grantor`/`grantee`에 반영돼 여기로
    들어온다. `contract.grantor`/`grantee`는 NOT NULL이라 끝내 못 정하면 400이다.
    """
    info = (dto or {}).get("contractInfo")
    info = info if isinstance(info, dict) else {}
    grantor = req.grantor or info.get("grantor")
    grantee = req.grantee or info.get("grantee") or info.get("counterparty")

    missing = [n for n, v in (("grantor", grantor), ("grantee", grantee)) if not v]
    if missing:
        raise ValidationFailed(
            "계약 당사자를 정할 수 없습니다. 추출 결과에 없으면 직접 보내야 합니다",
            details={"missing": missing},
        )
    return grantor, grantee


def _persist_contract_meta(db: Session, contract_id: int, dto: Optional[dict[str, Any]]) -> None:
    """화면이 고친 계약 메타를 `public.contract`에 반영한다 (D-36).

    `save_rights_batch()`는 P2 소유 DB 함수라 시그니처를 건드리지 않는다. 여기서
    쓰는 네 컬럼은 이미 존재하므로 평범한 UPDATE로 충분하다 — 판정과 무관한
    값이라 판정 트랜잭션 안에서 나중에 써도 의미가 같다.

    NULL은 "지우기"가 아니라 "기존 값 유지"다(`COALESCE`) — 화면이 일부만 고쳤을 때
    나머지를 지우면 안 된다.

    """
    info = (dto or {}).get("contractInfo")
    info = info if isinstance(info, dict) else {}
    params = {
        "title": info.get("title"),
        "signed_date": info.get("signedDate"),
        "lang": info.get("lang"),
        "amount": info.get("amount"),
        "currency": info.get("currency"),
    }
    if not any(v is not None for v in params.values()):
        return
    db.execute(
        text(
            "UPDATE contract SET "
            "  title       = COALESCE(:title, title), "
            "  signed_date = COALESCE(CAST(:signed_date AS date), signed_date), "
            "  lang        = COALESCE(:lang, lang), "
            "  amount      = COALESCE(CAST(:amount AS numeric), amount), "
            "  currency    = COALESCE(:currency, currency), "
            "  updated_at  = now() "
            "WHERE id = :c"
        ),
        {**params, "c": contract_id},
    )


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
        rights, dto = apply_staging_edit(db, req)
    else:
        rights, dto = req.rights, None
    grantor, grantee = _resolve_parties(req, dto)
    ctx = _resolve_context(db, req, default_kind="draft")
    try:
        _validate_request_refs(db, req, rights, ctx)
        rights_json = build_rights_json(db, rights)
        row = db.execute(
            text(
                "SELECT batch_result, constraint_name, conflict_report "
                "FROM validate_rights_batch("
                "  :contract_id, :grantor, :grantee, :ip_id, :file_name, :file_path, :file_hash,"
                "  CAST(:rights AS jsonb), :mime_type, :raw_text, CAST(:document_kind AS contract_document_kind))"
            ),
            {
                "contract_id": ctx["contract_id"],
                "grantor": grantor,
                "grantee": grantee,
                "ip_id": ctx["ip_id"],
                # 판정은 통째로 롤백되므로 파일 메타는 NOT NULL만 채우면 된다.
                # 실제 값은 확정(⑧)에서 서버가 staging 원본으로 채운다(D-34).
                "file_name": req.file_name or "contract.pdf",
                "file_path": req.file_path or "pending",
                "file_hash": req.file_hash or "pending",
                "rights": rights_json,
                "mime_type": req.mime_type or "application/pdf",
                "raw_text": req.raw_text,
                "document_kind": ctx["document_kind"],
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
    dto: Optional[dict[str, Any]] = None
    if req.source_tmpid is not None:
        # 검증과 동일한 경로. 확정만 호출해도 수정분이 staging에 반영된 뒤 저장된다.
        rights, dto = apply_staging_edit(db, req)
        file_name, file_hash, pdf_data = _staging_file_fields(db, req.source_tmpid)
    else:
        rights = req.rights
        file_name, file_hash = req.file_name, req.file_hash
    grantor, grantee = _resolve_parties(req, dto)
    ctx = _resolve_context(db, req, default_kind="final")

    try:
        _validate_request_refs(db, req, rights, ctx, lock_contract=True)
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
                "contract_id": ctx["contract_id"],
                "grantor": grantor,
                "grantee": grantee,
                "ip_id": ctx["ip_id"],
                "file_name": file_name,
                # staging 경로에서는 세대 id가 정해진 뒤에 실제 경로로 UPDATE한다.
                "file_path": req.file_path if pdf_data is None else "pending",
                "file_hash": file_hash,
                "rights": rights_json,
                "mime_type": req.mime_type or "application/pdf",
                "raw_text": req.raw_text,
                "chunks": chunks_json,
                "document_kind": ctx["document_kind"],
                "source_tmpid": str(req.source_tmpid) if req.source_tmpid else None,
            },
        ).mappings().first()
        # /contracts is the terminal step for an extraction result.  Both an
        # applied batch and a conflicted history are persisted by the DB
        # function, so either outcome consumes the staging job.
        _persist_contract_meta(db, row["out_contract_id"], dto)
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


def _validate_request_refs(
    db: Session, req, rights: list, ctx: dict[str, Any], *, lock_contract: bool = False
) -> None:
    """P2 함수가 의미상 보장하지 않는 contract/IP/asset 소속을 API 경계에서 확인한다.

    `rights`는 요청 body가 아니라 **판정에 실제로 쓸 목록**을 받는다 — staging
    경로에서는 저장된 수정본에서 나오기 때문이다(D-34).
    """
    if ctx["contract_id"] is not None:
        suffix = " FOR UPDATE" if lock_contract else ""
        found = db.execute(
            text("SELECT id FROM contract WHERE id=:c" + suffix),
            {"c": ctx["contract_id"]},
        ).scalar()
        if found is None:
            raise NotFound("계약을 찾을 수 없습니다")

    asset_ids = {r.content_asset_id for r in rights if r.content_asset_id is not None}
    if ctx["ip_id"] is None:
        if asset_ids:
            raise ValidationFailed("ipId가 없으면 contentAssetId를 지정할 수 없습니다")
        return

    if db.execute(text("SELECT id FROM ip WHERE id=:i"), {"i": ctx["ip_id"]}).scalar() is None:
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
        if by_id[asset_id] != ctx["ip_id"]:
            raise ValidationFailed(
                "contentAssetId가 요청한 ipId에 속하지 않습니다",
                details={"contentAssetId": asset_id, "ipId": ctx["ip_id"]},
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

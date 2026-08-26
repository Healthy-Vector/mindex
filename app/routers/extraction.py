"""PDF upload hand-off and extraction-result polling endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.errors import NotFound, ValidationFailed
from app.schemas.extraction import ExtractionAccepted, ExtractionJobOut
from app.services import staging_edit
from app.services.extraction_result import to_upload_result
from app.services.ip_search import search_ip_rows

router = APIRouter()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


@router.post("/extract", response_model=ExtractionAccepted, status_code=202)
async def submit_extraction(
    file: UploadFile = File(...),
    mode: Literal["draft", "final"] = Form(...),
    contract_id: int | None = Form(default=None, alias="contractId"),
    ip_id: int | None = Form(default=None, alias="ipId"),
    db: Session = Depends(get_db),
) -> ExtractionAccepted:
    """업로드 PDF를 보관하고 워커가 가져갈 추출 작업을 큐에 넣는다.

    D-37 — `mode`가 `new`/`revision`/`final` 3값에서 `draft`/`final` 2값으로 바뀌었다.
    "신규냐 개정이냐"는 `contractId`의 유무가 이미 말해주므로 `mode`에 섞을 필요가
    없었다. 덕분에 **신규 계약의 서명본**(`final` + `contractId` 없음)이 표현된다 —
    예전 3값 체계에서는 `final`이 기존 계약을 전제해서 초안을 한 번 거쳐야 했다.
    같은 이유로 "revision/final은 contractId·ipId 필수" 검증도 없앴다.

    세 값은 `extract_job`에 저장한다. 화면 상태가 없는 진입(목록의 "처리 중" 항목
    클릭, 브라우저 재접속)에서도 `tmpId`만으로 맥락을 복원하기 위해서다.
    """
    filename = _safe_filename(file.filename)
    data = await _read_pdf(file)
    try:
        tmpid = db.execute(
            text(
                "INSERT INTO staging.pdf_blob(data, filename, byte_size) "
                "VALUES (:data, :filename, :byte_size) RETURNING tmpid"
            ),
            {"data": data, "filename": filename, "byte_size": len(data)},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO staging.extract_job(tmpid, status, mode, contract_id, ip_id) "
                "VALUES (:tmpid, 'QUEUED', :mode, :contract_id, :ip_id)"
            ),
            {
                "tmpid": str(tmpid),
                "mode": mode,
                "contract_id": contract_id,
                "ip_id": ip_id,
            },
        )
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_db_message(ex)) from ex

    return ExtractionAccepted(
        tmpid=tmpid, status="QUEUED", filename=filename, byte_size=len(data)
    )


@router.get("/extract/{tmpid}", response_model=ExtractionJobOut)
def get_extraction(tmpid: UUID, db: Session = Depends(get_db)) -> ExtractionJobOut:
    """Return the persisted worker state; adapt DONE JSONB to the UI DTO."""
    job = db.execute(
        text(
            "SELECT j.tmpid, j.status, j.stage, j.reason, j.created_at, "
            "       j.mode, j.contract_id, j.ip_id, b.filename, r.payload "
            "FROM staging.extract_job j "
            "JOIN staging.pdf_blob b ON b.tmpid=j.tmpid "
            "LEFT JOIN staging.extract_result r ON r.tmpid=j.tmpid "
            "WHERE j.tmpid=:tmpid"
        ),
        {"tmpid": str(tmpid)},
    ).mappings().first()
    if job is None:
        raise NotFound("추출 작업을 찾을 수 없습니다")

    queue_position = None
    if job["status"] == "QUEUED":
        queue_position = int(
            db.execute(
                text(
                    "SELECT count(*) FROM staging.extract_job "
                    "WHERE status='QUEUED' AND created_at < :created_at"
                ),
                {"created_at": job["created_at"]},
            ).scalar_one()
        )

    result = None
    if job["status"] == "DONE" and job["payload"] is not None:
        payload = job["payload"]
        # D-34 — verify가 반영해 둔 사용자 수정본이 있으면 그걸 돌려준다.
        # 워커 원본은 payload["raw"]에 그대로 남아 있다.
        edited = payload.get(staging_edit.EDITED_KEY)
        if isinstance(edited, Mapping):
            result = dict(edited)
        else:
            result = to_upload_result(
                payload, territory_group_members=staging_edit.territory_groups(db)
            )
        # 후보는 저장된 값이 아니라 조회 시점의 IP 목록에서 매번 다시 뽑는다.
        result["ipCandidates"] = _ip_candidates(db, _search_title(payload))

    return ExtractionJobOut(
        tmpid=job["tmpid"],
        status=job["status"],
        filename=job["filename"],
        stage=job["stage"],
        queue_position=queue_position,
        reason=job["reason"],
        mode=job["mode"],
        contract_id=job["contract_id"],
        ip_id=job["ip_id"],
        result=result,
    )


async def _read_pdf(file: UploadFile) -> bytes:
    try:
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(READ_CHUNK_BYTES):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise ValidationFailed("PDF 파일은 100MB를 초과할 수 없습니다")
            chunks.append(chunk)
    finally:
        await file.close()

    data = b"".join(chunks)
    if not data:
        raise ValidationFailed("비어 있는 PDF 파일은 업로드할 수 없습니다")
    if not data.startswith(b"%PDF-"):
        raise ValidationFailed("PDF 파일만 업로드할 수 있습니다")
    return data


def _safe_filename(filename: str | None) -> str:
    safe = Path((filename or "upload.pdf").replace("\\", "/")).name
    return safe or "upload.pdf"


def _search_title(payload: Mapping[str, Any]) -> str | None:
    raw = payload.get("raw", payload)
    if not isinstance(raw, Mapping):
        return None
    contract = raw.get("contract")
    if not isinstance(contract, Mapping):
        return None
    for grant in contract.get("rights_grants") or []:
        if not isinstance(grant, Mapping):
            continue
        content = grant.get("content")
        if not isinstance(content, Mapping):
            continue
        for subject in content.get("subjects") or []:
            if isinstance(subject, Mapping) and subject.get("title"):
                return str(subject["title"])
    title = contract.get("contract_title")
    if isinstance(title, Mapping) and title.get("value"):
        return str(title["value"])
    return None


def _ip_candidates(db: Session, search_title: str | None) -> list[dict[str, Any]]:
    if not search_title:
        return []
    rows, _ = search_ip_rows(db, search_title, include_inactive=False, page=1, size=10)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        assets = db.execute(
            text(
                "SELECT id, scope_type, season_no, episode_no, edition_code, title "
                "FROM content_asset WHERE ip_id=:ip_id ORDER BY id"
            ),
            {"ip_id": row["id"]},
        ).mappings().all()
        candidates.append(
            {
                "ipId": row["id"],
                "title": row["title"],
                "kind": row["kind"],
                "matchedAlias": row["matched_text"] if row["matched_on"] == "alias" else None,
                "matchedBy": row["matched_on"],
                "score": round(float(row["score"]), 4),
                "assets": [
                    {
                        "contentAssetId": asset["id"],
                        "scopeType": asset["scope_type"],
                        "seasonNo": asset["season_no"],
                        "episodeNo": asset["episode_no"],
                        "editionCode": asset["edition_code"],
                        "title": asset["title"],
                    }
                    for asset in assets
                ],
                "relations": [],
            }
        )
    return candidates


def _db_message(ex: DBAPIError) -> str:
    message = str(getattr(ex, "orig", ex)).strip()
    return message.splitlines()[0][:300] if message else "추출 작업을 저장하지 못했습니다"

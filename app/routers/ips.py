"""IP 관리 — 12·13·14·18·4 (P2-DB 정렬: public 스키마, team_id 없음).

- 삭제 없음. activity='deactive' 로 감춘다.
- 13 중복: 정규화 키 일치 시 409 IP_DUPLICATE + 기존 ipId.
- 14 aliases 전체 교체.
- 18 권리 대상(content_asset)은 행 단위로만 손댄다 — 14 처럼 전체 교체로 열면
  빈 배열 한 번에 기존 자산이 통째로 날아간다.
- 4 relations: ip_relation 미구현 → 빈 배열.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.errors import AssetInUse, IpDuplicate, NotFound, ValidationFailed
from app.schemas.common import Page
from app.schemas.ips import (
    AliasOut, AssetIn, AssetOut, AssetPatch, IpCreate, IpListItem, IpOut, IpPatch,
)
from app.schemas.match import AssetRef, IpMatch, MatchResponse
from app.services.ip_norm import norm_key
from app.services.ip_search import search_ip_rows

router = APIRouter()


def _aliases(db: Session, ip_id: int) -> list[AliasOut]:
    rows = db.execute(
        text("SELECT id, alias_text, lang, alias_type FROM ip_alias WHERE ip_id=:i ORDER BY id"),
        {"i": ip_id},
    ).mappings().all()
    return [AliasOut(id=r["id"], text=r["alias_text"], lang=r["lang"], alias_type=r["alias_type"]) for r in rows]


_ASSET_COLUMNS = (
    "id, scope_type, title, asset_type, season_no, episode_no, edition_code"
)


def _asset_out(row) -> AssetOut:
    return AssetOut(
        content_asset_id=row["id"], scope_type=row["scope_type"], title=row["title"],
        asset_type=row["asset_type"], season_no=row["season_no"],
        episode_no=row["episode_no"], edition_code=row["edition_code"],
    )


def _assets(db: Session, ip_id: int) -> list[AssetOut]:
    rows = db.execute(
        text(f"SELECT {_ASSET_COLUMNS} FROM content_asset WHERE ip_id=:i ORDER BY id"),
        {"i": ip_id},
    ).mappings().all()
    return [_asset_out(r) for r in rows]


def _ip_out(db: Session, row) -> IpOut:
    contract_count = db.execute(
        text(
            "SELECT count(DISTINCT rg.contract_id) FROM rights_grant rg "
            "JOIN content_asset ca ON ca.id=rg.content_asset_id WHERE ca.ip_id=:i"
        ),
        {"i": row["id"]},
    ).scalar_one()
    return IpOut(
        ip_id=row["id"], title=row["title"], kind=row["kind"], activity=row["activity"],
        created_at=row["created_at"], aliases=_aliases(db, row["id"]),
        assets=_assets(db, row["id"]), contract_count=int(contract_count),
    )


@router.get("/ips", response_model=Page[IpListItem])
def list_ips(
    q: Optional[str] = Query(default=None),
    include_inactive: bool = Query(default=False, alias="includeInactive"),
    page: int = Query(default=1, ge=1),
    size: Optional[int] = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[IpListItem]:
    s = get_settings()
    size = size or s.page_size_default
    rows, total = search_ip_rows(
        db, q, include_inactive=include_inactive, page=page, size=size
    )
    items = [
        IpListItem(
            **_ip_out(db, row).model_dump(),
            score=round(float(row["score"]), 4) if row["score"] is not None else None,
            matched_on=row["matched_on"],
            matched_text=row["matched_text"],
        )
        for row in rows
    ]
    return Page[IpListItem](items=items, total=total, page=page, size=size)


@router.post("/ips", response_model=IpOut, status_code=201)
def create_ip(body: IpCreate, db: Session = Depends(get_db)) -> IpOut:
    key = norm_key(body.title)
    existing = db.execute(
        text(
            "SELECT i.id, i.title, a.alias_text FROM ip i "
            "LEFT JOIN ip_alias a ON a.ip_id=i.id"
        )
    ).mappings().all()
    for r in existing:
        if norm_key(r["title"]) == key or (r["alias_text"] and norm_key(r["alias_text"]) == key):
            raise IpDuplicate("같은 이름의 IP 가 이미 있습니다", details={"ipId": r["id"]})
    try:
        ip_id = db.execute(
            text("INSERT INTO ip(title, kind) VALUES (:t,:k) RETURNING id"),
            {"t": body.title, "k": body.kind},
        ).scalar_one()  # 트리거가 기본 content_asset 자동 생성
        for a in body.aliases:
            db.execute(
                text("INSERT INTO ip_alias(ip_id, alias_text, lang, alias_type) VALUES (:i,:t,:l,:ty)"),
                {"i": ip_id, "t": a.text, "l": a.lang, "ty": a.alias_type},
            )
        if body.assets is not None:
            # ip INSERT 트리거가 만든 기본 SERIES_ALL을 명시 입력으로 교체한다.
            db.execute(text("DELETE FROM content_asset WHERE ip_id=:i"), {"i": ip_id})
            for a in body.assets:
                db.execute(
                    text(
                        "INSERT INTO content_asset("
                        "ip_id, asset_type, scope_type, title, season_no, episode_no, edition_code"
                        ") VALUES (:i,:at,CAST(:st AS asset_scope_kind),:t,:sn,:en,:ec)"
                    ),
                    {
                        "i": ip_id, "at": a.asset_type, "st": a.scope_type, "t": a.title,
                        "sn": a.season_no, "en": a.episode_no, "ec": a.edition_code,
                    },
                )
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_db_message(ex)) from ex
    row = db.execute(
        text("SELECT id, title, kind, activity, created_at FROM ip WHERE id=:i"), {"i": ip_id}
    ).mappings().first()
    return _ip_out(db, row)


@router.patch("/ips/{ip_id}", response_model=IpOut)
def patch_ip(ip_id: int, body: IpPatch, db: Session = Depends(get_db)) -> IpOut:
    exists = db.execute(text("SELECT 1 FROM ip WHERE id=:i"), {"i": ip_id}).first()
    if exists is None:
        raise NotFound("IP 를 찾을 수 없습니다")
    sets, params = [], {"i": ip_id}
    if body.title is not None:
        sets.append("title=:t")
        params["t"] = body.title
    if body.kind is not None:
        sets.append("kind=:k")
        params["k"] = body.kind
    if body.activity is not None:
        sets.append("activity=CAST(:a AS ip_activity_kind)")
        params["a"] = body.activity
    try:
        if sets:
            db.execute(text(f"UPDATE ip SET {', '.join(sets)} WHERE id=:i"), params)
        if body.aliases is not None:  # 전체 교체
            db.execute(text("DELETE FROM ip_alias WHERE ip_id=:i"), {"i": ip_id})
            for a in body.aliases:
                db.execute(
                    text("INSERT INTO ip_alias(ip_id, alias_text, lang, alias_type) VALUES (:i,:t,:l,:ty)"),
                    {"i": ip_id, "t": a.text, "l": a.lang, "ty": a.alias_type},
                )
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_db_message(ex)) from ex
    row = db.execute(
        text("SELECT id, title, kind, activity, created_at FROM ip WHERE id=:i"), {"i": ip_id}
    ).mappings().first()
    return _ip_out(db, row)


@router.get("/ips/match", response_model=MatchResponse)
def match_ips(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    include_inactive: bool = Query(default=False, alias="includeInactive"),
    db: Session = Depends(get_db),
) -> MatchResponse:
    rows, _ = search_ip_rows(
        db, q, include_inactive=include_inactive, page=1, size=limit
    )
    matches: list[IpMatch] = []
    for ip in rows:
        assets = db.execute(
            text(
                "SELECT id, scope_type, season_no, episode_no, edition_code, title "
                "FROM content_asset WHERE ip_id=:i ORDER BY id"
            ),
            {"i": ip["id"]},
        ).mappings().all()
        matches.append(
            IpMatch(
                ip_id=ip["id"], title=ip["title"], kind=ip["kind"],
                matched_on=ip["matched_on"], matched_text=ip["matched_text"],
                score=round(float(ip["score"]), 4),
                assets=[AssetRef(content_asset_id=a["id"], **{k: v for k, v in a.items() if k != "id"}) for a in assets],
                relations=[],  # ip_relation 미구현
            )
        )
    return MatchResponse(matches=matches)


@router.get("/ips/{ip_id}", response_model=IpOut)
def get_ip(ip_id: int, db: Session = Depends(get_db)) -> IpOut:
    """IP 단건 상세. 비활성 IP도 기존 계약 확인을 위해 조회할 수 있다."""
    row = db.execute(
        text("SELECT id, title, kind, activity, created_at FROM ip WHERE id=:i"),
        {"i": ip_id},
    ).mappings().first()
    if row is None:
        raise NotFound("IP 를 찾을 수 없습니다")
    return _ip_out(db, row)


# --- 18. 권리 대상(content_asset) 행 단위 관리 ---
def _require_ip(db: Session, ip_id: int) -> None:
    if db.execute(text("SELECT 1 FROM ip WHERE id=:i"), {"i": ip_id}).first() is None:
        raise NotFound("IP 를 찾을 수 없습니다")


def _asset_row(db: Session, ip_id: int, asset_id: int):
    """경로의 ip_id 에 실제로 속한 자산만 돌려준다.

    ip_id 조건을 빼면 asset_id 만 갈아끼워 남의 IP 자산을 고칠 수 있다(IDOR).
    """
    row = db.execute(
        text(f"SELECT {_ASSET_COLUMNS} FROM content_asset WHERE id=:a AND ip_id=:i"),
        {"a": asset_id, "i": ip_id},
    ).mappings().first()
    if row is None:
        raise NotFound("자산을 찾을 수 없습니다")
    return row


def _grant_count(db: Session, asset_id: int) -> int:
    """이 자산을 참조하는 권리 건수. status 로 거르지 않는다 — terminated 권리도
    판정 이력이 남아 있으므로 대상 범위가 사후에 바뀌면 이력이 거짓이 된다."""
    return int(
        db.execute(
            text("SELECT count(*) FROM rights_grant WHERE content_asset_id=:a"),
            {"a": asset_id},
        ).scalar_one()
    )


def _asset_message(ex: ValidationError) -> str:
    errs = ex.errors()
    if not errs:
        return "자산 필드 조합이 올바르지 않습니다"
    # pydantic 이 ValueError 를 "Value error, ..." 로 감싸므로 접두어를 떼고 원문만 쓴다.
    return str(errs[0].get("msg", "")).removeprefix("Value error, ")[:300]


@router.post("/ips/{ip_id}/assets", response_model=AssetOut, status_code=201)
def create_ip_asset(ip_id: int, body: AssetIn, db: Session = Depends(get_db)) -> AssetOut:
    """자산 한 행 추가. 기존 자산은 건드리지 않는다(전체 교체가 아니다)."""
    _require_ip(db, ip_id)
    try:
        asset_id = db.execute(
            text(
                "INSERT INTO content_asset("
                "ip_id, asset_type, scope_type, title, season_no, episode_no, edition_code"
                ") VALUES (:i,:at,CAST(:st AS asset_scope_kind),:t,:sn,:en,:ec) RETURNING id"
            ),
            {
                "i": ip_id, "at": body.asset_type, "st": body.scope_type, "t": body.title,
                "sn": body.season_no, "en": body.episode_no, "ec": body.edition_code,
            },
        ).scalar_one()
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_db_message(ex)) from ex
    return _asset_out(_asset_row(db, ip_id, asset_id))


@router.patch("/ips/{ip_id}/assets/{asset_id}", response_model=AssetOut)
def patch_ip_asset(
    ip_id: int, asset_id: int, body: AssetPatch, db: Session = Depends(get_db)
) -> AssetOut:
    """자산 부분 수정. 권리가 걸린 자산은 읽기 전용이다."""
    current = _asset_row(db, ip_id, asset_id)  # 소속 검증 포함
    used = _grant_count(db, asset_id)
    if used:
        raise AssetInUse(
            "권리가 등록된 권리 대상은 수정할 수 없습니다",
            details={"rightsGrantCount": used},
        )
    try:
        merged = body.merged_with(current)  # 병합 후 scope 정합성 검증
    except ValidationError as ex:
        raise ValidationFailed(_asset_message(ex)) from ex
    try:
        db.execute(
            text(
                "UPDATE content_asset SET "
                "scope_type=CAST(:st AS asset_scope_kind), title=:t, asset_type=:at, "
                "season_no=:sn, episode_no=:en, edition_code=:ec WHERE id=:a"
            ),
            {
                "a": asset_id, "at": merged.asset_type, "st": merged.scope_type,
                "t": merged.title, "sn": merged.season_no, "en": merged.episode_no,
                "ec": merged.edition_code,
            },
        )
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_db_message(ex)) from ex
    return _asset_out(_asset_row(db, ip_id, asset_id))


@router.delete("/ips/{ip_id}/assets/{asset_id}", status_code=204)
def delete_ip_asset(ip_id: int, asset_id: int, db: Session = Depends(get_db)) -> Response:
    """자산 한 행 삭제. 권리가 걸렸거나 마지막 한 행이면 409."""
    _asset_row(db, ip_id, asset_id)  # 소속 검증 포함
    used = _grant_count(db, asset_id)
    if used:
        raise AssetInUse(
            "권리가 등록된 권리 대상은 삭제할 수 없습니다",
            details={"rightsGrantCount": used},
        )
    remaining = int(
        db.execute(
            text("SELECT count(*) FROM content_asset WHERE ip_id=:i"), {"i": ip_id}
        ).scalar_one()
    )
    if remaining <= 1:
        # ensure_default_content_asset() 트리거가 IP 마다 한 행을 보장하는 이유와 같다 —
        # 마지막 행이 사라지면 save_rights_batch() 의 기본 자산 조회가 깨진다.
        raise AssetInUse(
            "IP 의 마지막 권리 대상은 삭제할 수 없습니다", details={"assetCount": remaining}
        )
    try:
        db.execute(text("DELETE FROM content_asset WHERE id=:a"), {"a": asset_id})
        db.commit()
    except DBAPIError as ex:
        db.rollback()
        raise ValidationFailed(_db_message(ex)) from ex
    return Response(status_code=204)


def _db_message(ex: DBAPIError) -> str:
    message = str(getattr(ex, "orig", ex)).strip()
    return message.splitlines()[0][:300] if message else "IP 요청 처리에 실패했습니다"

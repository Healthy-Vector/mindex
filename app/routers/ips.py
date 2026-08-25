"""IP 관리 — 12·13·14·4 (P2-DB 정렬: public 스키마, team_id 없음).

- 삭제 없음. activity='deactive' 로 감춘다.
- 13 중복: 정규화 키 일치 시 409 IP_DUPLICATE + 기존 ipId.
- 14 aliases 전체 교체.
- 4 relations: ip_relation 미구현 → 빈 배열.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.errors import IpDuplicate, NotFound, ValidationFailed
from app.schemas.common import Page
from app.schemas.ips import AliasOut, AssetOut, IpCreate, IpOut, IpPatch
from app.schemas.match import AssetRef, IpMatch, MatchResponse
from app.services.ip_norm import norm_key

router = APIRouter()


def _aliases(db: Session, ip_id: int) -> list[AliasOut]:
    rows = db.execute(
        text("SELECT id, alias_text, lang, alias_type FROM ip_alias WHERE ip_id=:i ORDER BY id"),
        {"i": ip_id},
    ).mappings().all()
    return [AliasOut(id=r["id"], text=r["alias_text"], lang=r["lang"], alias_type=r["alias_type"]) for r in rows]


def _assets(db: Session, ip_id: int) -> list[AssetOut]:
    rows = db.execute(
        text(
            "SELECT id, scope_type, title, asset_type, season_no, episode_no, edition_code "
            "FROM content_asset WHERE ip_id=:i ORDER BY id"
        ),
        {"i": ip_id},
    ).mappings().all()
    return [
        AssetOut(
            content_asset_id=r["id"], scope_type=r["scope_type"], title=r["title"],
            asset_type=r["asset_type"], season_no=r["season_no"],
            episode_no=r["episode_no"], edition_code=r["edition_code"],
        )
        for r in rows
    ]


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


@router.get("/ips", response_model=Page[IpOut])
def list_ips(
    q: Optional[str] = Query(default=None),
    include_inactive: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: Optional[int] = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[IpOut]:
    s = get_settings()
    size = size or s.page_size_default
    where = "" if include_inactive else "WHERE activity='active'"
    rows = db.execute(
        text(f"SELECT id, title, kind, activity, created_at FROM ip {where} ORDER BY created_at DESC")
    ).mappings().all()
    if q and q.strip():
        key = norm_key(q)
        matched_ids = set()
        for row in rows:
            if key in norm_key(row["title"]):
                matched_ids.add(row["id"])
        for alias in db.execute(text("SELECT ip_id, alias_text FROM ip_alias")).mappings():
            if key in norm_key(alias["alias_text"]):
                matched_ids.add(alias["ip_id"])
        rows = [row for row in rows if row["id"] in matched_ids]
    total = len(rows)
    window = rows[(page - 1) * size : (page - 1) * size + size]
    return Page[IpOut](items=[_ip_out(db, r) for r in window], total=total, page=page, size=size)


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
def match_ips(q: str = Query(..., min_length=1), db: Session = Depends(get_db)) -> MatchResponse:
    like = f"%{q.strip().lower()}%"
    matched: dict[int, str] = {}
    for (i,) in db.execute(
        text("SELECT id FROM ip WHERE activity='active' AND lower(title) LIKE :q"), {"q": like}
    ):
        matched[i] = "title"
    for (i,) in db.execute(
        text("SELECT DISTINCT ip_id FROM ip_alias WHERE lower(alias_text) LIKE :q"), {"q": like}
    ):
        matched.setdefault(i, "alias")

    matches: list[IpMatch] = []
    for ip_id, how in matched.items():
        ip = db.execute(
            text("SELECT id, title, kind, activity FROM ip WHERE id=:i"), {"i": ip_id}
        ).mappings().first()
        if ip is None or ip["activity"] != "active":
            continue
        assets = db.execute(
            text(
                "SELECT id, scope_type, season_no, episode_no, edition_code, title "
                "FROM content_asset WHERE ip_id=:i ORDER BY id"
            ),
            {"i": ip_id},
        ).mappings().all()
        matches.append(
            IpMatch(
                ip_id=ip["id"], title=ip["title"], kind=ip["kind"], matched_on=how,
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


def _db_message(ex: DBAPIError) -> str:
    message = str(getattr(ex, "orig", ex)).strip()
    return message.splitlines()[0][:300] if message else "IP 요청 처리에 실패했습니다"

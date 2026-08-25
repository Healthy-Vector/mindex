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
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.errors import IpDuplicate, NotFound
from app.schemas.common import Page
from app.schemas.ips import AliasOut, IpCreate, IpOut, IpPatch
from app.schemas.match import AssetRef, IpMatch, MatchResponse
from app.services.ip_norm import norm_key

router = APIRouter()


def _aliases(db: Session, ip_id: int) -> list[AliasOut]:
    rows = db.execute(
        text("SELECT id, alias_text, lang, alias_type FROM ip_alias WHERE ip_id=:i ORDER BY id"),
        {"i": ip_id},
    ).mappings().all()
    return [AliasOut(id=r["id"], alias_text=r["alias_text"], lang=r["lang"], alias_type=r["alias_type"]) for r in rows]


def _ip_out(db: Session, row) -> IpOut:
    return IpOut(
        id=row["id"], title=row["title"], kind=row["kind"], activity=row["activity"],
        created_at=row["created_at"], aliases=_aliases(db, row["id"]),
    )


@router.get("/ips", response_model=Page[IpOut])
def list_ips(
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
    total = len(rows)
    window = rows[(page - 1) * size : (page - 1) * size + size]
    return Page[IpOut](items=[_ip_out(db, r) for r in window], total=total, page=page, size=size)


@router.post("/ips", response_model=IpOut, status_code=201)
def create_ip(body: IpCreate, db: Session = Depends(get_db)) -> IpOut:
    key = norm_key(body.title)
    for r in db.execute(text("SELECT id, title FROM ip")).mappings().all():
        if norm_key(r["title"]) == key:
            raise IpDuplicate("같은 이름의 IP 가 이미 있습니다", details={"ipId": r["id"]})
    ip_id = db.execute(
        text("INSERT INTO ip(title, kind) VALUES (:t,:k) RETURNING id"),
        {"t": body.title, "k": body.kind},
    ).scalar_one()  # 트리거가 기본 content_asset 자동 생성
    for a in body.aliases:
        db.execute(
            text("INSERT INTO ip_alias(ip_id, alias_text, lang, alias_type) VALUES (:i,:t,:l,:ty)"),
            {"i": ip_id, "t": a.alias_text, "l": a.lang, "ty": a.alias_type},
        )
    db.commit()
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
        sets.append("title=:t"); params["t"] = body.title
    if body.kind is not None:
        sets.append("kind=:k"); params["k"] = body.kind
    if body.activity is not None:
        sets.append("activity=CAST(:a AS ip_activity_kind)"); params["a"] = body.activity
    if sets:
        db.execute(text(f"UPDATE ip SET {', '.join(sets)} WHERE id=:i"), params)
    if body.aliases is not None:  # 전체 교체
        db.execute(text("DELETE FROM ip_alias WHERE ip_id=:i"), {"i": ip_id})
        for a in body.aliases:
            db.execute(
                text("INSERT INTO ip_alias(ip_id, alias_text, lang, alias_type) VALUES (:i,:t,:l,:ty)"),
                {"i": ip_id, "t": a.alias_text, "l": a.lang, "ty": a.alias_type},
            )
    db.commit()
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
                assets=[AssetRef(**a) for a in assets],
                relations=[],  # ip_relation 미구현
            )
        )
    return MatchResponse(matches=matches)

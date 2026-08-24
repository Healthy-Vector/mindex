"""IP 관리 — 12번 GET /ips · 13번 POST /ips · 14번 PATCH /ips/{id} (지시서 §6).

- 삭제 엔드포인트 없음. isActive=false 로 감춘다.
- 13번 중복: 정규화 키 일치 시 409 IP_DUPLICATE + 기존 ipId.
- 14번 aliases 는 전체 교체(부분 병합 아님).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import get_settings
from app.errors import IpDuplicate, NotFound
from app.models.master import Ip, IpAlias
from app.schemas.common import Page
from app.schemas.ips import AliasOut, IpCreate, IpOut, IpPatch
from app.services.ip_norm import norm_key
from app.services.team_context import resolve_team_id

router = APIRouter()


def _to_out(ip: Ip, aliases: list[IpAlias]) -> IpOut:
    return IpOut(
        id=ip.id,
        title=ip.title,
        kind=ip.kind,
        is_active=ip.is_active,
        created_at=ip.created_at,
        updated_at=ip.updated_at,
        aliases=[
            AliasOut(id=a.id, alias_text=a.alias_text, lang=a.lang, alias_type=a.alias_type)
            for a in aliases
        ],
    )


def _aliases_of(db: Session, ip_id: int) -> list[IpAlias]:
    return list(db.execute(select(IpAlias).where(IpAlias.ip_id == ip_id)).scalars())


@router.get("/ips", response_model=Page[IpOut])
def list_ips(
    include_inactive: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: Optional[int] = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[IpOut]:
    s = get_settings()
    size = size or s.page_size_default
    team_id = resolve_team_id(db)
    q = select(Ip).where(Ip.team_id == team_id)
    if not include_inactive:
        q = q.where(Ip.is_active.is_(True))
    all_ids = list(db.execute(q.order_by(Ip.created_at.desc())).scalars())
    total = len(all_ids)
    window = all_ids[(page - 1) * size : (page - 1) * size + size]
    items = [_to_out(ip, _aliases_of(db, ip.id)) for ip in window]
    return Page[IpOut](items=items, total=total, page=page, size=size)


@router.post("/ips", response_model=IpOut, status_code=201)
def create_ip(body: IpCreate, db: Session = Depends(get_db)) -> IpOut:
    team_id = resolve_team_id(db)
    key = norm_key(body.title)
    # 정규화 키 중복 검사 (같은 팀 범위)
    existing = db.execute(select(Ip).where(Ip.team_id == team_id)).scalars()
    for ip in existing:
        if norm_key(ip.title) == key:
            raise IpDuplicate("같은 이름의 IP 가 이미 있습니다", details={"ipId": ip.id})

    ip = Ip(team_id=team_id, title=body.title, kind=body.kind, is_active=True)
    db.add(ip)
    db.flush()  # ip.id 확보
    for a in body.aliases:
        db.add(
            IpAlias(
                team_id=team_id, ip_id=ip.id, alias_text=a.alias_text,
                lang=a.lang, alias_type=a.alias_type,
            )
        )
    db.commit()
    db.refresh(ip)
    return _to_out(ip, _aliases_of(db, ip.id))


@router.patch("/ips/{ip_id}", response_model=IpOut)
def patch_ip(ip_id: int, body: IpPatch, db: Session = Depends(get_db)) -> IpOut:
    ip = db.get(Ip, ip_id)
    if ip is None:
        raise NotFound("IP 를 찾을 수 없습니다")

    if body.title is not None:
        ip.title = body.title
    if body.kind is not None:
        ip.kind = body.kind
    if body.is_active is not None:
        ip.is_active = body.is_active

    if body.aliases is not None:
        # 전체 교체 (§6 14번)
        for a in _aliases_of(db, ip.id):
            db.delete(a)
        db.flush()
        for a in body.aliases:
            db.add(
                IpAlias(
                    team_id=ip.team_id, ip_id=ip.id, alias_text=a.alias_text,
                    lang=a.lang, alias_type=a.alias_type,
                )
            )
    db.commit()
    db.refresh(ip)
    return _to_out(ip, _aliases_of(db, ip.id))

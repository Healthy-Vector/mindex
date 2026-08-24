"""팀 컨텍스트 해석 (MVP).

12~16번은 세션 없이 동작한다(§4.7). 그러나 행에는 team_id 가 필요하다.
MVP 는 단일 팀 운영을 가정하고, 세션이 없을 때는 첫 팀을 사용한다.
세션이 있으면(8·9·10·11) 토큰의 sub(team_id)를 우선한다.

미확정(§11): 다중 팀 환경의 팀 선택 규칙. 확정 전까지 단일 팀 가정.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import NotFound


def resolve_team_id(db: Session, team_hint: Optional[str] = None) -> str:
    if team_hint:
        return team_hint
    row = db.execute(
        text("SELECT id FROM master.team ORDER BY created_at LIMIT 1")
    ).first()
    if not row:
        raise NotFound("등록된 팀이 없습니다. 먼저 팀을 생성하십시오.")
    return str(row[0])

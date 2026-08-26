"""팀 컨텍스트 (P2-DB 정렬).

P2-DB 에서 team 은 PIN 관리 전용 테이블이고, team_id 를 도메인 테이블로
전파하지 않는다(단일사 온프렘, D-29/D-30). 따라서 이 헬퍼는 1번 PIN 인증에서만
쓰이며, 지정이 없으면 단일 팀을 반환한다.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import NotFound


def resolve_team_id(db: Session) -> int:
    row = db.execute(text("SELECT id FROM team ORDER BY id LIMIT 1")).first()
    if not row:
        raise NotFound("등록된 팀이 없습니다.")
    return int(row[0])

"""SFR-010 변경 로그 기반 동기화 — 담당 P1.

계약 데이터 변경 시 트리거가 change_log 테이블에 기록하고,
이 워커가 미처리 건을 순차 처리하여 벡터를 재생성한다.
처리 실패 시 상태를 보존해 재시도 가능하게 하고,
워커 재기동 후에도 누락 없이 이어서 처리한다.

ProSync(DB↔DB 전용)·Debezium(JVM·Kafka 의존)은 배제하고
트리거 + 폴링 방식으로 확정했다 (RFP v1.7).
"""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal

POLL_INTERVAL_SECONDS = 5
BATCH_SIZE = 50


def fetch_unprocessed(db: Session, limit: int = BATCH_SIZE):
    return db.execute(
        text(
            """
            SELECT id, table_name, row_id, op
            FROM change_log
            WHERE processed_at IS NULL
            ORDER BY id
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).fetchall()


def mark_processed(db: Session, change_log_id: int) -> None:
    db.execute(
        text("UPDATE change_log SET processed_at = now() WHERE id = :id"),
        {"id": change_log_id},
    )
    db.commit()


def process_change(row) -> None:
    """TODO: table_name·op에 따라 임베딩 재생성 로직 연결 (P3 pipeline 모듈 호출)."""
    raise NotImplementedError


def run_forever() -> None:
    db = SessionLocal()
    try:
        while True:
            rows = fetch_unprocessed(db)
            for row in rows:
                try:
                    process_change(row)
                    mark_processed(db, row.id)
                except Exception:
                    db.rollback()
                    # 실패 건은 processed_at이 NULL로 남아 다음 폴링에서 재시도된다.
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        db.close()


if __name__ == "__main__":
    run_forever()

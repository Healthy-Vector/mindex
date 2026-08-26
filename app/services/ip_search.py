"""IP 대표명·별칭의 결정론적 유사도 검색.

OCR이 추출한 제목처럼 등록 IP명보다 긴 문자열도 찾을 수 있도록 PostgreSQL
``pg_trgm`` 점수와 양방향 부분 문자열 보너스를 함께 사용한다. AI·임베딩은 사용하지
않으며, 검색 결과가 있을 때만 관련도 내림차순으로 정렬한다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.ip_norm import norm_key

MIN_SIMILARITY = 0.4

_SEARCH_SQL = """
WITH alias_scored AS (
    SELECT
        a.ip_id,
        a.alias_text,
        GREATEST(
            CASE
                WHEN lower(regexp_replace(a.alias_text, '[[:space:][:punct:]_]+', '', 'g')) = :query_key
                    THEN 0.99::real
                WHEN lower(regexp_replace(a.alias_text, '[[:space:][:punct:]_]+', '', 'g')) <> ''
                    AND :query_key LIKE '%' || lower(regexp_replace(a.alias_text, '[[:space:][:punct:]_]+', '', 'g')) || '%'
                    THEN 0.97::real
                WHEN lower(regexp_replace(a.alias_text, '[[:space:][:punct:]_]+', '', 'g')) LIKE '%' || :query_key || '%'
                    THEN 0.95::real
                ELSE 0::real
            END,
            similarity(lower(a.alias_text), :query),
            word_similarity(lower(a.alias_text), :query),
            strict_word_similarity(lower(a.alias_text), :query)
        ) AS score
    FROM ip_alias a
),
best_alias AS (
    SELECT DISTINCT ON (ip_id) ip_id, alias_text, score
    FROM alias_scored
    ORDER BY ip_id, score DESC, alias_text
),
scored AS (
    SELECT
        i.id,
        i.title,
        i.kind,
        i.activity,
        i.created_at,
        GREATEST(
            CASE
                WHEN lower(regexp_replace(i.title, '[[:space:][:punct:]_]+', '', 'g')) = :query_key
                    THEN 1::real
                WHEN lower(regexp_replace(i.title, '[[:space:][:punct:]_]+', '', 'g')) <> ''
                    AND :query_key LIKE '%' || lower(regexp_replace(i.title, '[[:space:][:punct:]_]+', '', 'g')) || '%'
                    THEN 0.98::real
                WHEN lower(regexp_replace(i.title, '[[:space:][:punct:]_]+', '', 'g')) LIKE '%' || :query_key || '%'
                    THEN 0.96::real
                ELSE 0::real
            END,
            similarity(lower(i.title), :query),
            word_similarity(lower(i.title), :query),
            strict_word_similarity(lower(i.title), :query)
        ) AS title_score,
        COALESCE(ba.score, 0::real) AS alias_score,
        ba.alias_text
    FROM ip i
    LEFT JOIN best_alias ba ON ba.ip_id = i.id
    WHERE (:include_inactive OR i.activity = 'active')
),
ranked AS (
    SELECT
        *,
        GREATEST(title_score, alias_score) AS score,
        CASE WHEN title_score >= alias_score THEN 'title' ELSE 'alias' END AS matched_on,
        CASE WHEN title_score >= alias_score THEN title ELSE alias_text END AS matched_text
    FROM scored
)
SELECT *, count(*) OVER () AS total_count
FROM ranked
WHERE score >= :min_similarity
ORDER BY score DESC, CASE matched_on WHEN 'title' THEN 0 ELSE 1 END, created_at DESC, id
LIMIT :limit OFFSET :offset
"""

_LIST_SQL = """
SELECT
    id,
    title,
    kind,
    activity,
    created_at,
    NULL::real AS score,
    NULL::text AS matched_on,
    NULL::text AS matched_text,
    count(*) OVER () AS total_count
FROM ip
WHERE (:include_inactive OR activity = 'active')
ORDER BY created_at DESC, id DESC
LIMIT :limit OFFSET :offset
"""


def search_ip_rows(
    db: Session,
    query: str | None,
    *,
    include_inactive: bool,
    page: int,
    size: int,
) -> tuple[list[Any], int]:
    """IP 목록 행과 필터 적용 후 전체 건수를 반환한다."""
    cleaned = (query or "").strip()
    params: dict[str, Any] = {
        "include_inactive": include_inactive,
        "limit": size,
        "offset": (page - 1) * size,
    }
    if cleaned:
        query_key = norm_key(cleaned)
        if not query_key:
            return [], 0
        params.update(
            query=cleaned.lower(),
            query_key=query_key,
            min_similarity=MIN_SIMILARITY,
        )
        sql = _SEARCH_SQL
    else:
        sql = _LIST_SQL

    rows = db.execute(text(sql), params).mappings().all()
    if rows:
        total = int(rows[0]["total_count"])
    elif page > 1:
        probe_params = {**params, "limit": 1, "offset": 0}
        probe = db.execute(text(sql), probe_params).mappings().first()
        total = int(probe["total_count"]) if probe else 0
    else:
        total = 0
    return rows, total

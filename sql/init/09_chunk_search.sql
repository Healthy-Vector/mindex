-- 조항 청크 하이브리드 검색 — 어휘(pg_trgm) + 벡터(pgvector).
--
-- pg_trgm 확장은 08_ip_search.sql이 이미 켠다(DB 전체에 한 번 켜지면 됨) —
-- 여기서는 재선언하지 않는다. contract_chunk.chunk_text에 GIN 인덱스만 추가한다.
--
-- 운영 설치 전 pg_available_extensions에서 pg_trgm 패키지 포함 여부를 확인해야
-- 한다 (08_ip_search.sql과 동일한 주의사항).
--
-- 04_vector.sql이 vector 확장 없는 순수 PostgreSQL 환경(D-10, 충돌 판정 검증용)
-- 에서는 통째로 빠질 수 있어 contract_chunk가 없을 수 있다 — 08_ip_search.sql의
-- ip/ip_alias 처리와 동일하게 조건부로 생성한다.
DO $$
BEGIN
    IF to_regclass('public.contract_chunk') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_chunk_text_trgm '
                'ON contract_chunk USING gin (lower(chunk_text) gin_trgm_ops)';
    END IF;
END
$$;

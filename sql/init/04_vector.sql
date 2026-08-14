-- 04_vector.sql — 조항 청크 + 임베딩 (SFR-005 · SFR-009-C)
--
-- vector 의존을 이 파일 하나에 격리한다 (D-10).
-- 00~03과 05·99는 pgvector 없는 순수 PostgreSQL 16에서도 그대로 돈다.
-- 충돌 판정 검증 환경의 선택지를 넓히기 위한 의도적 분리이며,
-- 이 파일만 빼고 실행해도 SFR-007은 완전하게 동작한다.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE contract_chunk (
    id           bigserial PRIMARY KEY,
    tenant_id    uuid   NOT NULL REFERENCES tenant(id),  -- D-20
    contract_id  bigint NOT NULL,

    clause_no    text,                   -- '제8조'
    chunk_text   text NOT NULL,
    lang         char(2),                -- 'ko' · 'en' · 'ja'
    page         int,

    -- SFR-005 — multilingual-e5-large, 1024차원.
    -- 한·영·일을 같은 벡터 공간에 매핑해 한국어 질의로 영문 계약서를 찾는다(TER-004).
    --
    -- D-14 — 벡터는 암호화 대상이 아니다. pgvector 유사도는 평문 벡터로 거리를
    -- 계산하므로 암호화하면 검색이 동작하지 않는다.
    -- 다만 벡터가 평문이라는 것은 한계다 — 공개 임베딩 모델을 쓰면 벡터에서
    -- 원문이 부분 복원될 수 있어 원문 암호화만으로 기밀성이 완결되지 않는다.
    embedding    vector(1024),

    created_at   timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (contract_id, tenant_id) REFERENCES contract (id, tenant_id) ON DELETE CASCADE
);

CREATE INDEX contract_chunk_embedding
    ON contract_chunk USING hnsw (embedding vector_cosine_ops);

-- SFR-009-P — 후보 축소 필터가 먼저 돌고 그다음 벡터 랭킹이다.
-- 테넌트·언어로 좁히는 경로를 인덱스로 받쳐 둔다.
CREATE INDEX contract_chunk_scope
    ON contract_chunk (tenant_id, contract_id);

-- 04_vector.sql — 조항 청크 + 임베딩 (SFR-005 · SFR-009-C)
--
-- vector 의존을 이 파일 하나에 격리한다 (D-10).
-- 00~03과 05·99는 pgvector 없는 순수 PostgreSQL 16에서도 그대로 돈다.
-- 충돌 판정 검증 환경의 선택지를 넓히기 위한 의도적 분리이며,
-- 이 파일만 빼고 실행해도 SFR-007은 완전하게 동작한다.
--
-- D-30 — document_id를 contract_history_id로 재조준했다. contract_document가
-- contract_history로 흡수됐기 때문이다(§1.4). save_rights_batch()가 선택적
-- p_chunks 인자로 이 테이블에 청크를 넣을 수 있지만(02_conflict_rules.sql),
-- 그 CREATE FUNCTION은 이 테이블이 아직 없어도 성공한다 — PL/pgSQL 함수
-- 본문은 최초 호출 시점에야 SQL이 컴파일되므로, 04가 05·99보다 먼저
-- 실행되는 한 실제 호출 시점에는 항상 테이블이 존재한다.

CREATE EXTENSION IF NOT EXISTS vector;

-- D-30 — PDF 원문이 contract_history로 옮겨갔으므로 chunk도 계약서 세대
-- 단위로 붙는다. contract_history_id가 없으면 수정 전/후 PDF의 조항이
-- 섞인다 — 예전 세대 계약서로 검색했는데 최신 세대 조항이 튀어나오는
-- 사고를 막는다.
CREATE TABLE contract_chunk (
    id                    bigserial PRIMARY KEY,
    contract_id           bigint NOT NULL,
    contract_history_id   bigint NOT NULL,

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

    FOREIGN KEY (contract_id)         REFERENCES contract         (id) ON DELETE CASCADE,
    FOREIGN KEY (contract_history_id) REFERENCES contract_history (id) ON DELETE CASCADE
);

CREATE INDEX contract_chunk_embedding
    ON contract_chunk USING hnsw (embedding vector_cosine_ops);

-- SFR-009-P — 후보 축소 필터가 먼저 돌고 그다음 벡터 랭킹이다.
-- 계약으로 좁히는 경로를 인덱스로 받쳐 둔다.
CREATE INDEX contract_chunk_scope
    ON contract_chunk (contract_id);

CREATE INDEX idx_chunk_history
    ON contract_chunk (contract_history_id);

-- mindex 스키마 초안
-- RFP DAR-001 원안(territory TEXT[] + EXCLUDE WITH &&)은 GiST가 배열 겹침을
-- 지원하지 않아 실행되지 않는다. 지역을 단일 값으로 정규화해 행을 분리한다.

CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE rights_enum AS ENUM
  ('STREAMING','REMAKE','MERCH','PUBLISHING');

-- 콘텐츠(IP)
CREATE TABLE content (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   UUID NOT NULL,
    title       TEXT NOT NULL
);

-- 계약서
CREATE TABLE contract (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     UUID NOT NULL,
    counterparty  TEXT NOT NULL,
    signed_date   DATE,
    raw_text      TEXT,
    amount        NUMERIC,
    version       INT NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- 권리 레코드 (플랫폼의 심장) — 지역 1개당 1행. 여러 지역이면 행을 나눠 저장한다.
CREATE TABLE rights_grant (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     UUID NOT NULL,
    contract_id   BIGINT NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    content_id    BIGINT NOT NULL REFERENCES content(id),

    territory     TEXT        NOT NULL,   -- 'JP', 'KR' … 단일 값
    rights_type   rights_enum NOT NULL,
    period        DATERANGE   NOT NULL,
    is_exclusive  BOOLEAN     NOT NULL,

    -- AI 추출 신뢰도 (SFR-004)
    confidence    NUMERIC(3,2),
    verified_by   TEXT,
    verified_at   TIMESTAMPTZ,

    -- 근거 추적 / Evidence Anchoring (SFR-003, 설계원칙 P-3)
    source_page   INT,
    source_clause TEXT,
    source_quote  TEXT
);

-- 충돌 판정: 독점권 중복을 DB가 원천 차단 (SFR-007, 설계원칙 P-2)
ALTER TABLE rights_grant
ADD CONSTRAINT no_exclusive_overlap
EXCLUDE USING gist (
    tenant_id    WITH =,
    content_id   WITH =,
    rights_type  WITH =,
    territory    WITH =,
    period       WITH &&
)
WHERE (is_exclusive);

-- 조항 청크 + 벡터 (SFR-005)
CREATE TABLE contract_chunk (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    UUID NOT NULL,
    contract_id  BIGINT NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    clause_no    TEXT,
    chunk_text   TEXT NOT NULL,
    lang         TEXT,
    embedding    vector(1024)
);

CREATE INDEX ON contract_chunk
  USING hnsw (embedding vector_cosine_ops);

-- 변경 로그 — 동기화 워커가 폴링 (SFR-010, 담당 P1)
CREATE TABLE change_log (
    id           BIGSERIAL PRIMARY KEY,
    table_name   TEXT NOT NULL,
    row_id       BIGINT NOT NULL,
    op           TEXT NOT NULL,
    processed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON change_log (processed_at) WHERE processed_at IS NULL;

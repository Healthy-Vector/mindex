CREATE TYPE field_status_kind AS ENUM (
    'PRESENT_EXPLICIT',
    'PRESENT_DERIVED',
    'UNRESOLVED',
    'ABSENT',
    'EXTERNAL_REFERENCE'
);

CREATE TYPE document_language_kind AS ENUM ('KO', 'EN', 'JP');

CREATE TYPE party_role_kind AS ENUM ('GRANTOR', 'GRANTEE');

CREATE TABLE pdf_cache (
    id         bigserial PRIMARY KEY,
    file_path  text NOT NULL,   -- 로컬 파일시스템 경로
    raw_text   text,            -- PDF 파싱 원문
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE contract_extraction (
    id                   bigserial PRIMARY KEY,
    pdf_cache_id         bigint NOT NULL REFERENCES pdf_cache(id) ON DELETE CASCADE,
    schema_version       text NOT NULL,             -- 예: k-rights.contract-extraction.v0.1
    source_document_ref  text,                       -- 호출자 opaque reference. DB ID 아님
    document_language    document_language_kind,

    title                jsonb,                      -- FieldResult<string>
    agreement_type       jsonb,                      -- FieldResult<DIRECT_LICENSE|SUBLICENSE>
    agreement_date       jsonb,                      -- FieldResult<YYYY-MM-DD>

    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_contract_extraction_pdf_cache ON contract_extraction (pdf_cache_id);

CREATE TABLE party (
    id                       bigserial PRIMARY KEY,
    contract_extraction_id   bigint NOT NULL REFERENCES contract_extraction(id) ON DELETE CASCADE,
    role                     party_role_kind,
    name                     text,
    field_status             field_status_kind NOT NULL,
    raw_expression           text
);

CREATE INDEX idx_party_contract_extraction ON party (contract_extraction_id);

CREATE TABLE rights_grant (
    id                       bigserial PRIMARY KEY,
    contract_extraction_id   bigint NOT NULL REFERENCES contract_extraction(id) ON DELETE CASCADE,
    grant_ref                text NOT NULL,          -- 페이로드 내 임시 참조값. 예: grant-1. 영속 ID 아님

    content                  jsonb,                  -- {field_status, subjects[], raw_expression}
    legal_right              jsonb,                  -- {field_status, values[], raw_expression}
    exploitation_mode        jsonb,                  -- {field_status, values[], raw_expression}
    territory                jsonb,                  -- {field_status, values[], excluded_values[], definitions[], raw_expression}
    license_period           jsonb,                  -- {field_status, start, end, raw_expression}
    exclusivity              jsonb,                  -- {field_status, value, raw_expression}
    authority_constraints    jsonb,                  -- {field_status, may_sublicense, allowed_recipient_types[], target_recipient_type, raw_expression}
    scope_modifiers          jsonb,                  -- [{modifier_type, dimension, field_status, values[], raw_expression}]

    UNIQUE (contract_extraction_id, grant_ref)
);

CREATE TABLE payment (
    id                       bigserial PRIMARY KEY,
    contract_extraction_id   bigint NOT NULL REFERENCES contract_extraction(id) ON DELETE CASCADE,
    payment_ref              text NOT NULL,          -- 페이로드 내 임시 참조값. 예: payment-1
    amount                   numeric,
    currency                 char(3),                -- ISO 4217

    UNIQUE (contract_extraction_id, payment_ref)
);

CREATE TABLE evidence (
    id                       bigserial PRIMARY KEY,
    contract_extraction_id   bigint NOT NULL REFERENCES contract_extraction(id) ON DELETE CASCADE,
    evidence_ref             text NOT NULL,          -- 페이로드 내 임시 참조값. 예: evidence-1
    labels                   text[],                 -- 문언이 수행하는 clause function 목록
    targets                  jsonb NOT NULL,         -- [{target_type, target_ref, field}]
    text                     text NOT NULL,          -- 계약서 exact text
    section                  text,
    page_start               int,
    page_end                 int,
    start_char               int,                    -- canonical text 기준 offset (UTF-8/LF/코드포인트, start 포함)
    end_char                 int,                    -- canonical text 기준 offset (end 미포함)

    UNIQUE (contract_extraction_id, evidence_ref)
);

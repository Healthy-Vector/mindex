-- mindex_staging — 임시 DB 스키마 (docs/mindex-임시DB-비동기파이프라인.html §2 그대로 구현)
--
-- 운영 DB(mindex)와 물리적으로 분리된 별도 인스턴스다. 메인 DB에 대한 FK는
-- 없다 — contract.source_tmpid ↔ extract_job.tmpid 연결은 UNIQUE 제약으로만
-- 성립하는 논리적 참조다 (sql/init/01_schema.sql, D-32).
--
-- 이전 pdf_cache 5테이블(pdf_cache/contract_extraction/party/rights_grant/
-- payment/evidence, 동기 처리 전제) 설계를 대체한다. OCR·LLM 추출이 건당
-- 50~60초 걸려 요청 안에서 끝낼 수 없어 비동기 큐로 바뀌었고, 세부 필드를
-- 정규화 테이블로 쪼개지 않고 extract_result.payload jsonb 하나로 둔다 —
-- 어차피 확정 전 검토용이며 확정된 값만 운영 DB rights_grant로 넘어간다.

CREATE TABLE pdf_blob (
    tmpid      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data       bytea NOT NULL,        -- 암호화된 PDF 바이트 원본
    filename   text,
    byte_size  int,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE extract_job (
    tmpid       uuid PRIMARY KEY REFERENCES pdf_blob(tmpid) ON DELETE CASCADE,
    status      text NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
    stage       text CHECK (stage IS NULL OR stage IN ('OCR', 'LLM')),  -- 화면 진행 표시용
    lease_until timestamptz,          -- RUNNING 점유 만료 시각. SKIP LOCKED 회수 기준
    attempts    int NOT NULL DEFAULT 0,
    reason      text,                 -- FAILED 사유
    consumed_at timestamptz,          -- 운영 DB 확정이 끝난 시각. 별도 DB라서 필요한 컬럼
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_extract_job_status_created ON extract_job (status, created_at);

CREATE TABLE extract_result (
    tmpid      uuid PRIMARY KEY REFERENCES extract_job(tmpid) ON DELETE CASCADE,
    payload    jsonb NOT NULL,        -- AI 추출 결과 원본. status='DONE'과 함께 커밋
    confidence numeric(4,3),
    created_at timestamptz NOT NULL DEFAULT now()
);

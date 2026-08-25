-- 06_staging_schema.sql — staging 스키마 (D-33, D-32 정정)
--
-- 같은 mindex DB 안의 별도 스키마다. 별도 인스턴스가 아니다 — D-32에서
-- "물리적으로 분리된 별도 인스턴스"로 확정했던 건 팀이 "인스턴스"를
-- 스키마 레벨로 잘못 이해한 것이었고, D-33에서 정정했다. 같은 DB 안이라
-- contract.source_tmpid를 staging.extract_job.tmpid에 실제 FK로 걸 수 있다
-- (이 파일 맨 아래).
--
-- 이전 pdf_cache 5테이블(pdf_cache/contract_extraction/party/rights_grant/
-- payment/evidence, 동기 처리 전제) 설계를 대체한다. OCR·LLM 추출이 건당
-- 50~60초 걸려 요청 안에서 끝낼 수 없어 비동기 큐로 바뀌었고, 세부 필드를
-- 정규화 테이블로 쪼개지 않고 extract_result.payload jsonb 하나로 둔다 —
-- 어차피 확정 전 검토용이며 확정된 값만 rights_grant로 넘어간다.

CREATE SCHEMA staging;

CREATE TABLE staging.pdf_blob (
    tmpid      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data       bytea NOT NULL,        -- 암호화된 PDF 바이트 원본
    filename   text,
    byte_size  int,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE staging.extract_job (
    tmpid       uuid PRIMARY KEY REFERENCES staging.pdf_blob(tmpid) ON DELETE CASCADE,
    status      text NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
    stage       text CHECK (stage IS NULL OR stage IN ('OCR', 'LLM')),  -- 화면 진행 표시용
    lease_until timestamptz,          -- RUNNING 점유 만료 시각. SKIP LOCKED 회수 기준
    attempts    int NOT NULL DEFAULT 0,
    reason      text,                 -- FAILED 사유
    consumed_at timestamptz,          -- 확정(contract.source_tmpid 기록)이 끝난 시각.
                                       -- 확정과 정리(§7 O-15)를 한 트랜잭션으로 묶을지는 미결이라 당분간 유지
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_extract_job_status_created ON staging.extract_job (status, created_at);

CREATE TABLE staging.extract_result (
    tmpid      uuid PRIMARY KEY REFERENCES staging.extract_job(tmpid) ON DELETE CASCADE,
    payload    jsonb NOT NULL,        -- AI 추출 결과 원본. status='DONE'과 함께 커밋
    created_at timestamptz NOT NULL DEFAULT now()
);

-- contract는 01_schema.sql에서 이미 만들어져 있다. staging 스키마가 이제
-- 막 생겼으니 FK는 여기서 ALTER로 붙인다(evidence_quotes_present CHECK를
-- 02_conflict_rules.sql에서 ALTER로 붙이는 것과 같은 이유 — 대상이 이 파일
-- 이전엔 존재하지 않았다). TTL 정리로 extract_job 행이 삭제되면
-- contract.source_tmpid는 CASCADE가 아니라 SET NULL로 풀린다 — 정리
-- 배치가 계약 행 자체를 건드리면 안 되기 때문이다.
ALTER TABLE contract
    ADD FOREIGN KEY (source_tmpid)
    REFERENCES staging.extract_job(tmpid) ON DELETE SET NULL;

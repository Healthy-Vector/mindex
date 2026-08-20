-- 05_change_log.sql — 변경 로그 (SFR-010, 주최사 명시 요건 ④)
--
-- 담당 분해: DB 트리거와 이 테이블은 P2, 폴링 워커는 P1이다 (O-05 해소).
-- SRS v1.0과 Build Order v1.0 모두 SFR-010 담당을 P1로 적고 있으며,
-- P2는 워커가 읽을 로그를 만들어 주는 데까지가 몫이다.

CREATE TABLE change_log (
    id           bigserial PRIMARY KEY,
    table_name   text   NOT NULL,
    row_id       bigint NOT NULL,
    op           char(1) NOT NULL CHECK (op IN ('I', 'U', 'D')),

    -- 워커가 재기동돼도 누락 없이 이어서 처리하려면 처리 상태가 행에 남아야 한다.
    -- 실패 시 재시도 가능해야 하므로 attempt·last_error를 함께 둔다.
    processed_at timestamptz,
    attempts     int NOT NULL DEFAULT 0,
    last_error   text,

    created_at   timestamptz NOT NULL DEFAULT now()
);

-- 미처리분만 훑는 부분 인덱스. 워커의 폴링 쿼리가 이걸 탄다.
CREATE INDEX change_log_pending
    ON change_log (created_at)
    WHERE processed_at IS NULL;

-- 변경을 앱이 아니라 DB가 기록한다.
-- 앱이 INSERT 문을 빠뜨려도 로그가 비지 않는다 — 원칙 P-4와 같은 이유다.
-- 함수 본체는 D-30에서도 변경하지 않는다.
CREATE OR REPLACE FUNCTION log_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO change_log (table_name, row_id, op)
    VALUES (
        TG_TABLE_NAME,
        COALESCE(NEW.id, OLD.id),
        CASE TG_OP WHEN 'INSERT' THEN 'I' WHEN 'UPDATE' THEN 'U' ELSE 'D' END
    );
    RETURN NULL;
END;
$$;

-- 재색인이 필요한 테이블에만 건다. D-22 — rights_grant 트리거는 코드리뷰로
-- 제거했다. change_log_worker.py의 실제 목적은 계약 원문 재청킹·재임베딩이고
-- (docstring: "벡터를 재생성한다"), rights_grant는 벡터화 대상이 아니다.
--
-- D-30 — 트리거를 contract_document가 아니라 contract_history에 건다.
-- raw_text(재청킹 대상)가 contract_document를 흡수한 contract_history로
-- 옮겨갔기 때문이다(§1.4). contract 자체(counterparty·status 등
-- 메타데이터)가 바뀌어도 재임베딩할 내용이 없으므로, contract 트리거를
-- 그대로 뒀다면 목적에 안 맞는 로그만 쌓였을 것이다 — 이 판단은 D-24
-- 때부터 유지된다.
CREATE TRIGGER contract_history_change_log
    AFTER INSERT OR UPDATE OR DELETE ON contract_history
    FOR EACH ROW EXECUTE FUNCTION log_change();

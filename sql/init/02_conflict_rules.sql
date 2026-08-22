-- 02_conflict_rules.sql — 충돌 판정 2단(트리거) + 배치 검증/저장 + WAIVER
-- (D-05·D-27·D-30, SFR-007·011)
--
-- 이 파일이 담당하는 것:
--   1. sync_rights_grant_spans()          — 판정축 코드 → nested-set span 비정규화 (D-27, 유지)
--   2. guard_taxonomy_frozen()            — taxonomy 좌표 변경 차단 (D-27, 유지)
--   3. is_valid_evidence_entry/is_valid_evidence — evidence JSONB 근거 검증 (D-30)
--   4. default_lineage_id()               — lineage_id 자기참조 기본값 (D-30)
--   5. ensure_default_content_asset()     — ip 생성 시 기본 content_asset 자동 생성 (D-30)
--   6. check_exclusivity_conflict()       — 독점↔비독점 XOR 충돌 (D-05, D-30로 조인키 갱신)
--   7. attempt_rights_batch_insert()      — 배치 INSERT 시도 내부 헬퍼 (D-30)
--   8. validate_rights_batch()            — 검증: 배치 전체를 INSERT 후 강제 롤백 (D-28 계승, D-30)
--   9. save_rights_batch()                — 등록: 배치 저장 + 세대 전환 + lineage 승계 (D-30)
--  10. terminate_rights_grant()           — WAIVER/CANCELLED 수동 종료 (D-30)
--  11. validate_contract_signing()        — contract.status='signed' 전환 검증 (D-31)
--
-- log_change()와 change_log 트리거는 05_change_log.sql이 그대로 담당한다
-- (함수 본체 무변경, 트리거 바인딩만 contract_document → contract_history로 재부착).

-- ─────────────────────────────────────────────────────────────
-- 1. 판정축 span 비정규화 (D-27, 변경 없음)
-- ─────────────────────────────────────────────────────────────
--
-- EXCLUDE의 키 표현식은 서브쿼리를 못 쓴다 — 참조 테이블에서 조인해 올 수
-- 없으므로 span이 rights_grant 행에 실물로 있어야 한다. 그 비정규화를 앱이
-- 아니라 DB가 한다: 앱이 span 컬럼에 무엇을 넣든 여기서 덮어쓴다.
CREATE OR REPLACE FUNCTION sync_rights_grant_spans() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  SELECT span INTO NEW.legal_right_span FROM legal_right WHERE code = NEW.legal_right;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'legal_right %는 정의되지 않은 코드다', NEW.legal_right;
  END IF;

  SELECT span INTO NEW.exploitation_mode_span FROM exploitation_mode WHERE code = NEW.exploitation_mode;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exploitation_mode %는 정의되지 않은 코드다', NEW.exploitation_mode;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER rights_grant_sync_spans
  BEFORE INSERT OR UPDATE ON rights_grant
  FOR EACH ROW EXECUTE FUNCTION sync_rights_grant_spans();

-- ─────────────────────────────────────────────────────────────
-- 2. taxonomy 좌표 동결 (D-27, 변경 없음)
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION guard_taxonomy_frozen() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM rights_grant) THEN
    -- 아직 판정 데이터가 없다 — 시드 시점이거나 빈 DB다. 자유롭게 바꿔도 된다.
    RETURN COALESCE(NEW, OLD);
  END IF;

  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION
      '% taxonomy의 행(%)은 rights_grant 데이터가 있는 동안 삭제할 수 없다. '
      'taxonomy 변경은 sql/init 수정 후 `docker compose down -v` 재초기화로 처리한다(D-10·D-27)',
      TG_TABLE_NAME, OLD.code;
  END IF;

  IF NEW.lft IS DISTINCT FROM OLD.lft OR NEW.rgt IS DISTINCT FROM OLD.rgt THEN
    RAISE EXCEPTION
      '% taxonomy의 nested-set 좌표(%)는 rights_grant 데이터가 있는 동안 변경할 수 없다 — '
      '이미 저장된 span이 낡은 좌표계를 가리키게 되고 EXCLUDE가 조용히 틀린다. '
      '`docker compose down -v` 재초기화로 처리한다(D-10·D-27)',
      TG_TABLE_NAME, OLD.code;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER legal_right_frozen
  BEFORE UPDATE OR DELETE ON legal_right
  FOR EACH ROW EXECUTE FUNCTION guard_taxonomy_frozen();

CREATE TRIGGER exploitation_mode_frozen
  BEFORE UPDATE OR DELETE ON exploitation_mode
  FOR EACH ROW EXECUTE FUNCTION guard_taxonomy_frozen();

-- ─────────────────────────────────────────────────────────────
-- 3. evidence JSONB 근거 검증 (D-30, §1.5)
-- ─────────────────────────────────────────────────────────────
--
-- P-3(모든 추출값은 원문 인용을 동반) 원칙을 candidate_evidence 테이블이
-- 아니라 CHECK 제약으로 강제한다. 값은 객체 1개 또는 배열(여러 근거 위치)
-- 둘 다 허용한다 — period는 본문·별표 두 군데에 근거가 흩어질 수 있다.
CREATE OR REPLACE FUNCTION is_valid_evidence_entry(e jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_typeof(e) = 'object' AND (e ? 'quote') AND btrim(e->>'quote') <> ''
$$;

CREATE OR REPLACE FUNCTION is_valid_evidence(doc jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT bool_and(
             CASE jsonb_typeof(doc -> key)
               WHEN 'object' THEN is_valid_evidence_entry(doc -> key)
               WHEN 'array'  THEN NOT EXISTS (
                   SELECT 1 FROM jsonb_array_elements(doc -> key) el WHERE NOT is_valid_evidence_entry(el)
               )
               ELSE false
             END)
    FROM unnest(ARRAY['legal_right','exploitation_mode','territory','period','exclusivity']) AS key
$$;

-- rights_grant 테이블은 01_schema.sql에서 이미 만들어졌다. 이 CHECK는 함수가
-- 필요해 여기서 ALTER로 붙인다 — evidence_has_required_keys(같은 컬럼의
-- 다른 CHECK, 함수 불필요)는 01에 이미 있다. 이 CHECK가 기존
-- candidate_evidence.evidence_quote_not_blank의 P-3 근거-필수 원칙을 그대로
-- 이어받는다.
ALTER TABLE rights_grant
    ADD CONSTRAINT evidence_quotes_present CHECK (is_valid_evidence(evidence));

-- ─────────────────────────────────────────────────────────────
-- 4. lineage_id 자기참조 기본값 (D-30)
-- ─────────────────────────────────────────────────────────────
--
-- bigserial의 nextval()은 BEFORE ROW 트리거보다 먼저 확정되므로 NEW.id
-- 참조가 안전하다 — DEFAULT 표현식은 트리거 실행 전에 NEW 레코드 구성
-- 단계에서 이미 적용된다.
CREATE OR REPLACE FUNCTION default_lineage_id() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.lineage_id IS NULL THEN
    NEW.lineage_id := NEW.id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER rights_grant_default_lineage
  BEFORE INSERT ON rights_grant
  FOR EACH ROW EXECUTE FUNCTION default_lineage_id();

-- ─────────────────────────────────────────────────────────────
-- 5. ip 생성 시 기본 content_asset 자동 생성 (D-30, §1.2)
-- ─────────────────────────────────────────────────────────────
--
-- 모든 권리 등록이 유효한 content_asset_id를 갖도록 보장한다. 시즌/에피소드
-- 세분은 O-07 범위(다음 라운드)이고, MVP는 작품당 SERIES_ALL 자산 하나로
-- 충분하다.
CREATE OR REPLACE FUNCTION ensure_default_content_asset() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO content_asset (ip_id, asset_type, scope_type, title)
  VALUES (NEW.id, 'MAIN', 'SERIES_ALL', NEW.title);
  RETURN NEW;
END;
$$;

CREATE TRIGGER ip_default_content_asset
  AFTER INSERT ON ip
  FOR EACH ROW EXECUTE FUNCTION ensure_default_content_asset();

-- ─────────────────────────────────────────────────────────────
-- 6. 충돌 판정 2단 — 트리거 (D-05, D-30으로 조인키 갱신)
-- ─────────────────────────────────────────────────────────────
--
-- 담당: 독점/sole ↔ 비독점. 독점끼리는 EXCLUDE가 맡는다(01_schema.sql).
-- 담당을 XOR로 배타 분할해 "어느 층이 잡았는지"가 결정론적으로 구분되게 한다.
--
-- D-30 — ip_id가 content_asset_id로, status 필터가 'active' 단일값으로,
-- 조인에 g.contract_id <> n.contract_id가 추가됐다. EXCLUDE와 정확히 같은
-- 비교식이어야 XOR 분할이 성립한다 — 한쪽만 고치면 두 층 사이에 판정되지
-- 않는 틈이 생긴다. 격리수준 가드·advisory lock·STATEMENT 트리거 구조는
-- 스파이크 1~9로 실측된 그대로다.
CREATE OR REPLACE FUNCTION check_exclusivity_conflict() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  k   record;
  hit record;
BEGIN
  -- D-07 가드. 이 3행이 없으면 누구든 REPEATABLE READ로 판정을 무력화할 수 있고,
  -- 게다가 에러 없이 무력화된다.
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION
      '충돌 판정은 READ COMMITTED에서만 정확하다 (현재: %)',
      current_setting('transaction_isolation')
      USING ERRCODE = '25001';
  END IF;

  -- D-07·D-29 — 팬텀 차단. 설치 단위가 곧 회사 경계이므로 content_asset_id로 잠근다.
  FOR k IN
    SELECT DISTINCT content_asset_id FROM new_rows
    WHERE status = 'active'
    ORDER BY content_asset_id
  LOOP
    PERFORM pg_advisory_xact_lock(k.content_asset_id);
  END LOOP;

  SELECT n.id AS new_id, g.id AS old_id
    INTO hit
  FROM new_rows n
  JOIN rights_grant g
    ON  g.contract_id             <> n.contract_id
    AND g.content_asset_id        =  n.content_asset_id
    AND g.legal_right_span        && n.legal_right_span
    AND g.exploitation_mode_span  && n.exploitation_mode_span
    AND g.territory                =  n.territory
    AND g.period                   && n.period
    AND g.id <> n.id
  -- XOR — 정확히 한쪽만 비독점일 때. 양쪽 독점은 EXCLUDE, 양쪽 비독점은 정상.
  WHERE (g.exclusivity = 'non_exclusive') <> (n.exclusivity = 'non_exclusive')
    AND n.status = 'active' AND g.status = 'active'
  LIMIT 1;

  IF FOUND THEN
    -- SQLSTATE를 EXCLUDE와 같은 23P01로 맞추는 이유: 앱의 SFR-011 핸들러가
    -- ExclusionViolation 하나만 잡으면 되고, 어느 층이 잡았는지는
    -- diag.constraint_name으로 구분한다(constraint_reason_map으로 번역).
    RAISE EXCEPTION
      '독점권과 비독점권이 같은 대상에 겹친다 (신규 행 %, 기존 행 %)', hit.new_id, hit.old_id
      USING ERRCODE = '23P01', CONSTRAINT = 'no_exclusivity_conflict';
  END IF;

  RETURN NULL;
END;
$$;

CREATE TRIGGER rights_grant_conflict_ins
  AFTER INSERT ON rights_grant
  REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION check_exclusivity_conflict();

CREATE TRIGGER rights_grant_conflict_upd
  AFTER UPDATE ON rights_grant
  REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION check_exclusivity_conflict();

-- ─────────────────────────────────────────────────────────────
-- 7. 배치 INSERT 시도 — 내부 헬퍼 (D-30, §4.1)
-- ─────────────────────────────────────────────────────────────
--
-- 배치 전체를 한 INSERT 문으로 시도한다. 단일 다중행 INSERT는 원자적이라,
-- 배치 내 한 행이라도 no_exclusive_overlap에 걸리면 그 문장 전체가
-- 롤백된다 — all-or-nothing이 "공짜로" 보장된다(§2). validate_rights_batch()와
-- save_rights_batch() 둘 다 이 헬퍼를 공유해 판정 로직이 갈라지지 않게
-- 한다(기존 evaluate_candidate()를 양쪽이 공유하던 것과 같은 원칙).
--
-- 문법 메모 — RETURN QUERY는 함수를 즉시 종료시키지 않는다(PL/pgSQL의 흔한
-- 함정). try 경로와 except 경로 양쪽에서 RETURN QUERY를 각각 부르는 대신,
-- 결과를 변수에 담아뒀다가 블록 밖에서 정확히 한 번만 RETURN QUERY한다 —
-- D-28의 sentinel-rollback 패턴과 같은 이유로, 이 함수가 상위 서브트랜잭션
-- 롤백에 물려도 반환값이 안전하게 살아남게 하기 위해서다.
CREATE OR REPLACE FUNCTION attempt_rights_batch_insert(
    p_contract_id         bigint,
    p_contract_history_id bigint,
    p_default_asset_id    bigint,
    p_rights              jsonb
) RETURNS TABLE (inserted_ids bigint[], constraint_name text, exception_detail text)
LANGUAGE plpgsql AS $$
DECLARE
  v_ids        bigint[];
  v_constraint text := NULL;
  v_detail     text := NULL;
BEGIN
  BEGIN
    WITH ins AS (
      INSERT INTO rights_grant (
          contract_id, contract_history_id, content_asset_id, lineage_id,
          territory, legal_right, exploitation_mode, period, exclusivity,
          evidence, conditions_raw
      )
      SELECT p_contract_id, p_contract_history_id,
             COALESCE(r.content_asset_id, p_default_asset_id), r.lineage_id,
             r.territory, r.legal_right, r.exploitation_mode, r.period, r.exclusivity,
             r.evidence, r.conditions_raw
      FROM jsonb_to_recordset(p_rights) AS r(
          content_asset_id bigint, territory char(2), legal_right text,
          exploitation_mode text, period daterange, exclusivity exclusivity_kind,
          evidence jsonb, conditions_raw jsonb, lineage_id bigint)
      RETURNING id
    )
    SELECT array_agg(id) INTO v_ids FROM ins;
  EXCEPTION WHEN exclusion_violation THEN
    GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME, v_detail = PG_EXCEPTION_DETAIL;
    v_ids := NULL;
  END;

  RETURN QUERY SELECT v_ids, v_constraint, v_detail;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 8. 검증 — 배치 전체를 INSERT 후 강제 롤백 (D-28 계승, D-30, §4.2)
-- ─────────────────────────────────────────────────────────────
--
-- probe_rights()/evaluate_candidate()를 대체한다. D-28의 sentinel-rollback
-- 서브트랜잭션 패턴(SQLSTATE 'MXP01')을 그대로 계승하되, 단일 candidate가
-- 아니라 배치 전체에 적용한다. right_mapping이 삭제됐으므로 advisory 단계는
-- 없다 — 이 함수는 이제 APPLIED/CONFLICTED 둘 중 하나만 판정한다.
--
-- 부모 행(ip·contract·contract_history)도 같은 서브트랜잭션에서 만든다.
-- 지어내는 껍데기가 아니라 업로드·추출 단계에서 앱이 이미 들고 있는 값이며
-- 커밋만 되지 않은 상태다.
CREATE OR REPLACE FUNCTION validate_rights_batch(
    p_contract_id  bigint,           -- NULL이면 신규 계약
    p_counterparty text,
    p_ip_id        bigint,           -- NULL이면 신규 작품
    p_file_name    text,
    p_file_path    text,
    p_file_hash    text,
    p_rights       jsonb,
    p_mime_type    text DEFAULT 'application/pdf',
    p_raw_text     text DEFAULT NULL,
    p_document_kind contract_document_kind DEFAULT 'draft'
)
RETURNS TABLE (
    batch_result     text,           -- 'APPLIED' · 'CONFLICTED'
    constraint_name  text,
    conflict_report  jsonb
)
LANGUAGE plpgsql AS $$
DECLARE
  v_contract   bigint;
  v_ip         bigint;
  v_asset      bigint;
  v_version    int;
  v_history    bigint;
  v_ids        bigint[];
  v_constraint text;
  v_detail     text;
  v_report     jsonb;
  v_result     text;
BEGIN
  BEGIN  -- ← EXCEPTION 절이 서브트랜잭션을 연다. 이 블록의 쓰기는 전부 되돌아간다.

    IF p_ip_id IS NULL THEN
      INSERT INTO ip (title) VALUES ('(검증)') RETURNING id INTO v_ip;
    ELSE
      v_ip := p_ip_id;
    END IF;

    SELECT id INTO v_asset FROM content_asset
     WHERE ip_id = v_ip AND scope_type = 'SERIES_ALL'
     ORDER BY id LIMIT 1;

    IF p_contract_id IS NULL THEN
      INSERT INTO contract (counterparty) VALUES (p_counterparty) RETURNING id INTO v_contract;
      v_version := 1;
    ELSE
      v_contract := p_contract_id;
      SELECT COALESCE(MAX(version), 0) + 1 INTO v_version
        FROM contract_history WHERE contract_id = v_contract;
    END IF;

    INSERT INTO contract_history
      (contract_id, version, document_kind, status,
       file_name, file_path, file_hash, mime_type, raw_text)
    VALUES
      (v_contract, v_version, p_document_kind, 'applied',
       p_file_name, p_file_path, p_file_hash, p_mime_type, p_raw_text)
    RETURNING id INTO v_history;

    SELECT a.inserted_ids, a.constraint_name, a.exception_detail
      INTO v_ids, v_constraint, v_detail
    FROM attempt_rights_batch_insert(v_contract, v_history, v_asset, p_rights) a;

    IF v_constraint IS NOT NULL THEN
      v_result := 'CONFLICTED';

      SELECT jsonb_build_object(
               'constraint_name',  v_constraint,
               'exception_detail', v_detail,
               'conflicts', COALESCE(jsonb_agg(
                 jsonb_build_object(
                     'incoming', jsonb_build_object(
                         'legal_right',       r.legal_right,
                         'exploitation_mode', r.exploitation_mode,
                         'territory',         r.territory,
                         'period',            r.period::text,
                         'exclusivity',       r.exclusivity),
                     'existing_grant_id',    g.id,
                     'existing_contract_id', g.contract_id,
                     'overlap_period',       (g.period * r.period)::text,
                     'legal_right_relation',
                         CASE WHEN g.legal_right = r.legal_right THEN 'same'
                              WHEN g.legal_right_span @> lr.span THEN 'existing_is_broader'
                              WHEN lr.span @> g.legal_right_span THEN 'incoming_is_broader'
                              ELSE 'overlap' END,
                     'exploitation_mode_relation',
                         CASE WHEN g.exploitation_mode = r.exploitation_mode THEN 'same'
                              WHEN g.exploitation_mode_span @> em.span THEN 'existing_is_broader'
                              WHEN em.span @> g.exploitation_mode_span THEN 'incoming_is_broader'
                              ELSE 'overlap' END,
                     'blocking_layer',
                         CASE WHEN r.exclusivity <> 'non_exclusive' AND g.exclusivity <> 'non_exclusive'
                              THEN 'no_exclusive_overlap' ELSE 'no_exclusivity_conflict' END
                 )
               ), '[]'::jsonb)
             ) INTO v_report
      FROM jsonb_to_recordset(p_rights) AS r(
          content_asset_id bigint, territory char(2), legal_right text,
          exploitation_mode text, period daterange, exclusivity exclusivity_kind,
          evidence jsonb, conditions_raw jsonb, lineage_id bigint)
      JOIN legal_right lr ON lr.code = r.legal_right
      JOIN exploitation_mode em ON em.code = r.exploitation_mode
      JOIN rights_grant g
        ON  g.content_asset_id = COALESCE(r.content_asset_id, v_asset)
        AND g.legal_right_span && lr.span
        AND g.exploitation_mode_span && em.span
        AND g.territory = r.territory
        AND g.period && r.period
        AND g.status = 'active'
        AND g.contract_id <> v_contract
        AND NOT (r.exclusivity = 'non_exclusive' AND g.exclusivity = 'non_exclusive');
    ELSE
      v_result := 'APPLIED';
      v_report := NULL;
    END IF;

    -- 서브트랜잭션 강제 롤백. 호출자에게 커밋 선택지를 주지 않는다.
    RAISE EXCEPTION USING ERRCODE = 'MXP01', MESSAGE = 'PROBE_SENTINEL';

  EXCEPTION WHEN SQLSTATE 'MXP01' THEN
    NULL;  -- 여기 도달한 시점에 위 블록의 쓰기는 전부 되돌아갔다
  END;

  RETURN QUERY SELECT v_result, v_constraint, v_report;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 9. 등록 — 배치 저장 + 세대 전환 + lineage 승계 (D-30, §4.3)
-- ─────────────────────────────────────────────────────────────
--
-- register_candidate()를 대체한다. 화면의 `권리 등록` 버튼이 호출한다.
-- 호출부(앱)가 바깥 BEGIN/COMMIT을 관리하고, 이 함수는 PL/pgSQL
-- BEGIN/EXCEPTION 블록(= 내부 서브트랜잭션. SQL SAVEPOINT 문은 함수
-- 안에서 직접 실행할 수 없으므로, D-28과 동일하게 PL/pgSQL의 예외 블록이
-- 그 역할을 한다)만 관리한다.
--
-- 실패해도 이전 세대를 다시 active로 되돌리고(서브트랜잭션 롤백), 그
-- 사실 자체는 새 contract_history 행(status='conflicted')으로 커밋해
-- 남긴다 — "충돌 건은 처리 대상으로 커밋한다"는 D-28/D-30 예외 원칙이다.
CREATE OR REPLACE FUNCTION save_rights_batch(
    p_contract_id  bigint,           -- NULL이면 신규 계약
    p_counterparty text,
    p_ip_id        bigint,           -- NULL이면 신규 작품 (신규 계약일 때만 의미가 있다)
    p_file_name    text,
    p_file_path    text,
    p_file_hash    text,
    p_rights       jsonb,
    p_mime_type    text DEFAULT 'application/pdf',
    p_raw_text     text DEFAULT NULL,
    p_chunks       jsonb DEFAULT NULL,  -- 선택적 contract_chunk 배치 (04_vector.sql 의존)
    p_document_kind contract_document_kind DEFAULT 'final',
    p_source_tmpid uuid DEFAULT NULL    -- staging.extract_job.tmpid (D-33). NULL이면 기록 안 함.
                                         -- 값이 있는데 staging.extract_job에 없으면 FK 위반으로 걸러진다
)
RETURNS TABLE (
    batch_result     text,           -- 'APPLIED' · 'CONFLICTED'
    out_contract_id  bigint,
    out_history_id   bigint,
    constraint_name  text,
    conflict_report  jsonb
)
LANGUAGE plpgsql AS $$
DECLARE
  v_contract   bigint;
  v_ip         bigint;
  v_asset      bigint;
  v_version    int;
  v_history    bigint;
  v_rights_ln  jsonb;
  v_ids        bigint[];
  v_constraint text;
  v_detail     text;
  v_report     jsonb;
  v_result     text;
BEGIN
  IF p_document_kind IS NULL THEN
    RAISE EXCEPTION 'save_rights_batch의 document_kind는 NULL일 수 없다';
  END IF;

  -- ── 1. contract 확정 ─────────────────────────────────────────
  IF p_contract_id IS NULL THEN
    v_ip := p_ip_id;
    IF v_ip IS NULL THEN
      INSERT INTO ip (title) VALUES (p_counterparty || ' 관련 신규 작품') RETURNING id INTO v_ip;
    END IF;
    INSERT INTO contract (counterparty, source_tmpid)
    VALUES (p_counterparty, p_source_tmpid) RETURNING id INTO v_contract;
  ELSE
    v_contract := p_contract_id;
    v_ip := p_ip_id;
    -- 개정판도 같은 tmpid 이중 확정 방지 대상이다. source_tmpid UNIQUE가
    -- SAVEPOINT 밖(=이 문장)에서 걸리므로, 배치가 뒤에서 충돌해도
    -- 이 기록은 살아남는다 — 비동기 파이프라인 문서 §3 ⑧ 순서 그대로다.
    IF p_source_tmpid IS NOT NULL THEN
      UPDATE contract SET source_tmpid = p_source_tmpid WHERE id = v_contract;
    END IF;
  END IF;

  IF v_ip IS NOT NULL THEN
    SELECT id INTO v_asset FROM content_asset
     WHERE ip_id = v_ip AND scope_type = 'SERIES_ALL'
     ORDER BY id LIMIT 1;
  END IF;

  SELECT COALESCE(MAX(version), 0) + 1 INTO v_version
    FROM contract_history WHERE contract_id = v_contract;

  -- ── 2~6. 서브트랜잭션(BEGIN/EXCEPTION) — "SAVEPOINT sp_batch" ───
  -- 이 안에서 이전 세대를 종료하고 새 세대를 시도한다. 실패하면 이
  -- 블록 전체(이전 세대 종료 + 새 contract_history 'applied' 행 +
  -- 시도한 rights_grant INSERT)가 전부 원복된다 — 이전 세대는 자동으로
  -- 다시 active가 된다.
  BEGIN
    -- 3. 이전 세대 종료 + lineage 승계용 자연키 스냅샷
    WITH terminated AS (
      UPDATE rights_grant
         SET status = 'terminated', terminated_at = now(), terminated_reason = 'superseded'
       WHERE contract_id = v_contract AND status = 'active'
      RETURNING content_asset_id, territory, legal_right, exploitation_mode, lineage_id
    ),
    -- 자연키가 겹치는 이전 세대가 정확히 1건일 때만 lineage_id를 승계한다.
    -- 2건 이상(모호)이면 매칭하지 않는다 — 새 lineage로 조용히 시작하는
    -- 편이 잘못된 계보를 잇는 것보다 안전하다(§8 미결 대신 여기서 확정).
    prev_keyed AS (
      SELECT content_asset_id, territory, legal_right, exploitation_mode,
             MIN(lineage_id) AS lineage_id, count(*) AS n
      FROM terminated
      GROUP BY content_asset_id, territory, legal_right, exploitation_mode
    ),
    -- 4. 새 배치 각 행에 순번을 매기고 자연키로 이전 세대와 매칭
    incoming AS (
      SELECT r.*, row_number() OVER () AS ord
      FROM jsonb_to_recordset(p_rights) AS r(
          content_asset_id bigint, territory char(2), legal_right text,
          exploitation_mode text, period daterange, exclusivity exclusivity_kind,
          evidence jsonb, conditions_raw jsonb)
    )
    SELECT jsonb_agg(
             jsonb_build_object(
               'content_asset_id',  COALESCE(i.content_asset_id, v_asset),
               'territory',         i.territory,
               'legal_right',       i.legal_right,
               'exploitation_mode', i.exploitation_mode,
               'period',            i.period,
               'exclusivity',       i.exclusivity,
               'evidence',          i.evidence,
               'conditions_raw',    i.conditions_raw,
               'lineage_id',        CASE WHEN pk.n = 1 THEN pk.lineage_id ELSE NULL END
             ) ORDER BY i.ord
           ) INTO v_rights_ln
    FROM incoming i
    LEFT JOIN prev_keyed pk
      ON  pk.content_asset_id  = COALESCE(i.content_asset_id, v_asset)
      AND pk.territory         = i.territory
      AND pk.legal_right       = i.legal_right
      AND pk.exploitation_mode = i.exploitation_mode;

    -- 5. 이번 세대 contract_history — 우선 applied로 기록해둔다
    INSERT INTO contract_history
      (contract_id, version, document_kind, status,
       file_name, file_path, file_hash, mime_type, raw_text)
    VALUES
      (v_contract, v_version, p_document_kind, 'applied',
       p_file_name, p_file_path, p_file_hash, p_mime_type, p_raw_text)
    RETURNING id INTO v_history;

    -- 6. 배치 INSERT 시도 — 실제 EXCLUDE를 태워본다
    SELECT a.inserted_ids, a.constraint_name, a.exception_detail
      INTO v_ids, v_constraint, v_detail
    FROM attempt_rights_batch_insert(v_contract, v_history, v_asset, v_rights_ln) a;

    IF v_constraint IS NOT NULL THEN
      -- 이 서브트랜잭션(3~6단계) 전체를 원복시키기 위한 sentinel.
      -- probe_rights()와 다른 이유로 예외를 던진다 — 여기서는 "실패했으니
      -- 이전 세대 종료를 되돌려야 한다"는 뜻이고, 그 사실 자체는 이
      -- 블록 밖에서 새 contract_history 행으로 별도 커밋한다.
      RAISE EXCEPTION USING ERRCODE = 'MXP01', MESSAGE = 'BATCH_CONFLICT_SENTINEL';
    END IF;

  EXCEPTION WHEN SQLSTATE 'MXP01' THEN
    NULL;  -- 3~6단계 전부 원복 — 이전 세대는 자동으로 다시 active
  END;

  -- ── 7·8. 결과에 따라 분기 ─────────────────────────────────────
  IF v_constraint IS NOT NULL THEN
    -- 7. 실패 — 배치 전체 진단을 다시 계산해 conflict_report를 만들고,
    -- 그 사실 자체는 새 contract_history 행(conflicted)으로 커밋한다.
    SELECT jsonb_build_object(
             'constraint_name',  v_constraint,
             'exception_detail', v_detail,
             'conflicts', COALESCE(jsonb_agg(
               jsonb_build_object(
                   'incoming', jsonb_build_object(
                       'legal_right',       r.legal_right,
                       'exploitation_mode', r.exploitation_mode,
                       'territory',         r.territory,
                       'period',            r.period::text,
                       'exclusivity',       r.exclusivity),
                   'existing_grant_id',    g.id,
                   'existing_contract_id', g.contract_id,
                   'overlap_period',       (g.period * r.period)::text,
                   'legal_right_relation',
                       CASE WHEN g.legal_right = r.legal_right THEN 'same'
                            WHEN g.legal_right_span @> lr.span THEN 'existing_is_broader'
                            WHEN lr.span @> g.legal_right_span THEN 'incoming_is_broader'
                            ELSE 'overlap' END,
                   'exploitation_mode_relation',
                       CASE WHEN g.exploitation_mode = r.exploitation_mode THEN 'same'
                            WHEN g.exploitation_mode_span @> em.span THEN 'existing_is_broader'
                            WHEN em.span @> g.exploitation_mode_span THEN 'incoming_is_broader'
                            ELSE 'overlap' END,
                   'blocking_layer',
                       CASE WHEN r.exclusivity <> 'non_exclusive' AND g.exclusivity <> 'non_exclusive'
                            THEN 'no_exclusive_overlap' ELSE 'no_exclusivity_conflict' END
               )
             ), '[]'::jsonb)
           ) INTO v_report
    FROM jsonb_to_recordset(p_rights) AS r(
        content_asset_id bigint, territory char(2), legal_right text,
        exploitation_mode text, period daterange, exclusivity exclusivity_kind,
        evidence jsonb, conditions_raw jsonb)
    JOIN legal_right lr ON lr.code = r.legal_right
    JOIN exploitation_mode em ON em.code = r.exploitation_mode
    JOIN rights_grant g
      ON  g.content_asset_id = COALESCE(r.content_asset_id, v_asset)
      AND g.legal_right_span && lr.span
      AND g.exploitation_mode_span && em.span
      AND g.territory = r.territory
      AND g.period && r.period
      AND g.status = 'active'
      AND g.contract_id <> v_contract
      AND NOT (r.exclusivity = 'non_exclusive' AND g.exclusivity = 'non_exclusive');

    INSERT INTO contract_history
      (contract_id, version, document_kind, status,
       file_name, file_path, file_hash, mime_type, raw_text, conflict_report)
    VALUES
      (v_contract, v_version, p_document_kind, 'conflicted',
       p_file_name, p_file_path, p_file_hash, p_mime_type, p_raw_text, v_report)
    RETURNING id INTO v_history;

    v_result := 'CONFLICTED';
  ELSE
    -- 8. 성공 — contract를 이번 세대로 갱신한다. draft 저장도 rights_grant는
    -- active라 즉시 예약 효력을 가진다. 문서 종류가 final이면 contract는
    -- signed, draft면 draft가 된다.
    UPDATE contract
       SET current_history_id = v_history,
           status = CASE p_document_kind
                      WHEN 'final' THEN 'signed'::contract_status
                      ELSE 'draft'::contract_status
                    END,
           updated_at = now()
     WHERE id = v_contract;

    v_result := 'APPLIED';
    v_report := NULL;
  END IF;

  -- contract_chunk는 성공/실패 무관하게 삽입한다 — 검색엔 유용하다
  -- (04_vector.sql 의존. p_chunks가 NULL이면 아무 일도 하지 않는다).
  IF p_chunks IS NOT NULL THEN
    INSERT INTO contract_chunk (contract_id, contract_history_id, clause_no, chunk_text, lang, page, embedding)
    SELECT v_contract, v_history, c.clause_no, c.chunk_text, c.lang, c.page, c.embedding
    FROM jsonb_to_recordset(p_chunks) AS c(
        clause_no text, chunk_text text, lang char(2), page int, embedding vector(1024));
  END IF;

  RETURN QUERY SELECT v_result, v_contract, v_history, v_constraint, v_report;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 10. WAIVER/CANCELLED — 수동 종료 (D-30, §5)
-- ─────────────────────────────────────────────────────────────
--
-- conflict_resolution 테이블과 그 두 트리거(validate_resolution_target,
-- apply_waiver_termination)를 되살리지 않는다. conflict_report가 이미
-- existing_grant_id(=rights_grant.id, 안정적 PK)를 담고 있어 별도 안정
-- 식별자를 새로 만들 필요가 없다.
--
-- 워크플로: 배치 충돌 → 화면이 conflict_report.conflicts[].existing_grant_id
-- 표시 → 사람이 포기 결정 → terminate_rights_grant(id, 'waiver', note)
-- 호출(그 자체로 커밋) → 동일 배치를 save_rights_batch()로 재제출(특수
-- "waiver 저장 경로" 없음, 일반 재시도와 동일). EXCLUDE 우회 경로는
-- 여전히 없다. MUTUAL_AGREEMENT/MANUAL_OVERRIDE는 기존과 동일하게 미지원.
CREATE OR REPLACE FUNCTION terminate_rights_grant(
    p_grant_id bigint, p_reason terminated_reason_kind, p_note text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  IF p_reason NOT IN ('waiver', 'cancelled') THEN
    RAISE EXCEPTION '수동 종료는 waiver 또는 cancelled 사유만 허용한다 (받은 값: %)', p_reason;
  END IF;

  UPDATE rights_grant
     SET status = 'terminated', terminated_at = now(),
         terminated_reason = p_reason, termination_note = p_note
   WHERE id = p_grant_id AND status = 'active';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'rights_grant %는 이미 종료됐거나 존재하지 않는다', p_grant_id;
  END IF;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 11. contract 서명 완료 검증 (D-31)
-- ─────────────────────────────────────────────────────────────
--
-- candidate 상태 스캔(옛 3번째 체크)은 candidate 자체가 없어져 완전히
-- 사라진다. "등록된 세대 존재 여부"는 contract 테이블의 plain
-- CHECK(signed_requires_history, 01_schema.sql)로 이미 커버된다.
-- 남는 것은 "가리키는 current_history_id가 실제로 이 계약 소속이고
-- final/applied 상태인가" — 다른 테이블 조인이 필요해 CHECK로 못 하므로
-- 트리거로 남긴다.
--
CREATE OR REPLACE FUNCTION validate_contract_signing() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_hist_contract bigint;
  v_hist_status   contract_history_status;
  v_document_kind contract_document_kind;
BEGIN
  SELECT contract_id, status, document_kind
    INTO v_hist_contract, v_hist_status, v_document_kind
  FROM contract_history WHERE id = NEW.current_history_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'current_history_id %는 존재하지 않는다', NEW.current_history_id;
  END IF;
  IF v_hist_contract <> NEW.id THEN
    RAISE EXCEPTION 'current_history_id %는 이 계약(%) 소속이 아니다', NEW.current_history_id, NEW.id;
  END IF;
  IF v_hist_status <> 'applied' THEN
    RAISE EXCEPTION 'current_history_id %는 applied 상태가 아니다 (현재: %)', NEW.current_history_id, v_hist_status;
  END IF;
  IF v_document_kind <> 'final' THEN
    RAISE EXCEPTION 'current_history_id %는 final 문서가 아니다 (현재: %)', NEW.current_history_id, v_document_kind;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER contract_signing_check
  BEFORE UPDATE ON contract
  FOR EACH ROW
  WHEN (
    NEW.status = 'signed'
    AND (
      OLD.status IS DISTINCT FROM 'signed'
      OR NEW.current_history_id IS DISTINCT FROM OLD.current_history_id
    )
  )
  EXECUTE FUNCTION validate_contract_signing();

-- ─────────────────────────────────────────────────────────────
-- 12. 계약 취소 시 권리 예약 해제 (D-31)
-- ─────────────────────────────────────────────────────────────
-- rights_grant.active는 서명 여부와 무관한 "충돌 슬롯 점유"다. contract가
-- cancelled가 되면 그 점유를 cancelled로 종료해야 다른 계약이
-- 같은 권리를 등록할 수 있다. cancelled 계약은 종결 상태라 되돌릴 수 없으며,
-- 다시 협의하려면 새 contract 업무 건으로 시작해야 한다.
CREATE OR REPLACE FUNCTION prevent_cancelled_contract_reopen() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'cancelled 계약 %는 다른 상태로 되돌릴 수 없다', OLD.id;
END;
$$;

CREATE TRIGGER contract_cancelled_is_terminal
  BEFORE UPDATE OF status ON contract
  FOR EACH ROW
  WHEN (OLD.status = 'cancelled' AND NEW.status IS DISTINCT FROM 'cancelled')
  EXECUTE FUNCTION prevent_cancelled_contract_reopen();

CREATE OR REPLACE FUNCTION release_contract_rights() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE rights_grant
     SET status = 'terminated',
         terminated_at = now(),
         terminated_reason = 'cancelled',
         termination_note = 'contract status changed to ' || NEW.status::text
   WHERE contract_id = NEW.id
     AND status = 'active';

  RETURN NEW;
END;
$$;

CREATE TRIGGER contract_release_rights
  AFTER UPDATE OF status ON contract
  FOR EACH ROW
  WHEN (
    NEW.status = 'cancelled'
    AND OLD.status IS DISTINCT FROM NEW.status
  )
  EXECUTE FUNCTION release_contract_rights();

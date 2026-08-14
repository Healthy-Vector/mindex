-- 02_conflict_rules.sql — 충돌 판정 2단(트리거) + 충돌 리포트 (D-05·D-06·D-07, SFR-007·011)
--
-- 스파이크(../spike-p2/)에서 7건 전부 실행 확인한 뒤 옮긴 것이다.
-- 옮기면서 바뀐 것은 rights_code(text) → rights_type(enum) 하나뿐이다.

-- ─────────────────────────────────────────────────────────────
-- 충돌 판정 2단 — 트리거
-- ─────────────────────────────────────────────────────────────
--
-- 담당: 독점/sole ↔ 비독점. 독점끼리는 EXCLUDE가 맡는다(01_schema.sql).
--
-- 왜 XOR로 좁히는가: EXCLUDE는 인덱스 삽입이라 statement 실행 중에 터지고
-- AFTER 트리거는 statement 종료 후에 돈다. 즉 독점↔독점을 트리거에도 맡기면
-- 그 분기는 절대 실행되지 않는 죽은 코드다. 스파이크 4번에서 트리거 첫 줄
-- RAISE NOTICE가 아예 찍히지 않는 것으로 실측 확인했다.
-- 게다가 이 순서는 우연이라 EXCLUDE를 DEFERRABLE로 바꾸면 조용히 뒤집힌다.
CREATE OR REPLACE FUNCTION check_exclusivity_conflict() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  k   record;
  hit record;
BEGIN
  -- D-07 가드. 이 3행이 없으면 누구든 아래 한 줄로 판정을 무력화할 수 있고,
  --   SET TRANSACTION ISOLATION LEVEL REPEATABLE READ
  -- 게다가 에러 없이 무력화된다.
  --
  -- REPEATABLE READ는 스냅샷이 트랜잭션 시작 시점에 고정되므로, advisory lock을
  -- 기다렸다 풀려도 상대 트랜잭션이 방금 커밋한 행이 여전히 보이지 않는다.
  -- READ COMMITTED에서는 plpgsql의 각 SQL문이 새 스냅샷을 뜨기 때문에 안전하다.
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION
      '충돌 판정은 READ COMMITTED에서만 정확하다 (현재: %)',
      current_setting('transaction_isolation')
      USING ERRCODE = '25001';
  END IF;

  -- D-07 — 팬텀 차단.
  -- T1이 독점을 삽입(미커밋), T2가 비독점을 삽입하면 T2의 SELECT는 T1의 행을
  -- 볼 수 없어 둘 다 커밋되고 불변식이 깨진다. EXCLUDE는 인덱스라 이 문제가
  -- 없지만 트리거는 있다. (tenant_id, content_id) 단위로 정렬 취득해 데드락을 피한다.
  --
  -- 스파이크 6번 — 락 有: T2가 23P01로 거부 / 락 無(대조군): 둘 다 커밋되어 2행 잔존.
  -- D-17 — draft·review·terminated 행은 판정 대상이 아니므로 락도 필요 없다.
  FOR k IN
    SELECT DISTINCT tenant_id, content_id FROM new_rows
    WHERE status IN ('provisional', 'complete')
    ORDER BY tenant_id, content_id
  LOOP
    PERFORM pg_advisory_xact_lock(hashtext(k.tenant_id::text || ':' || k.content_id::text));
  END LOOP;

  SELECT n.id AS new_id, g.id AS old_id
    INTO hit
  FROM new_rows n
  JOIN rights_grant g
    ON  g.tenant_id   = n.tenant_id
    AND g.content_id  = n.content_id
    AND g.rights_type = n.rights_type
    AND g.territory   = n.territory
    AND g.period     && n.period
    AND g.id <> n.id
  -- XOR — 정확히 한쪽만 비독점일 때. 양쪽 독점은 EXCLUDE, 양쪽 비독점은 정상.
  WHERE (g.exclusivity = 'non_exclusive') <> (n.exclusivity = 'non_exclusive')
    -- D-17 — 양쪽 다 provisional·complete여야 "살아있는" 충돌이다.
    AND n.status IN ('provisional', 'complete')
    AND g.status IN ('provisional', 'complete')
  LIMIT 1;

  IF FOUND THEN
    -- plpgsql RAISE의 자리표시자는 % 하나뿐이다. %s를 쓰면 에러가 나는 게 아니라
    -- 'new=1s'처럼 조용히 깨진 메시지가 나온다 — 에러보다 나쁘다 (스파이크 3번).
    --
    -- SQLSTATE를 EXCLUDE와 같은 23P01로 맞추는 이유: 앱의 SFR-011 핸들러가
    -- ExclusionViolation 하나만 잡으면 되고, 어느 층이 잡았는지는
    -- diag.constraint_name으로 구분한다. 테스트가 두 층을 구분 검증하는 유일한 방법이다.
    RAISE EXCEPTION
      '독점권과 비독점권이 같은 구간에 겹친다 (신규 행 %, 기존 행 %)', hit.new_id, hit.old_id
      USING ERRCODE = '23P01', CONSTRAINT = 'no_exclusivity_conflict';
  END IF;

  RETURN NULL;
END;
$$;

-- D-06 — STATEMENT 트리거 + transition table.
--
-- BEFORE ROW는 안 된다: 같은 문이 방금 삽입한 행을 보지 못한다(command counter 미증가).
-- 계약 1건이 다중 행 INSERT이므로 문 내부 충돌을 통째로 놓친다.
-- 시나리오 KO-C03(한 트랜잭션에 grant 3개, 그중 AVOD 하나만 충돌)이 이 케이스다.
--
-- 복수 이벤트(AFTER INSERT OR UPDATE)에는 transition table을 붙일 수 없다 —
-- 'transition tables cannot be specified for triggers with more than one event'.
-- 스파이크 2번에서 실행 확인했다. 그래서 2개로 나눈다.
CREATE TRIGGER rights_grant_conflict_ins
  AFTER INSERT ON rights_grant
  REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION check_exclusivity_conflict();

CREATE TRIGGER rights_grant_conflict_upd
  AFTER UPDATE ON rights_grant
  REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION check_exclusivity_conflict();

-- ─────────────────────────────────────────────────────────────
-- SFR-011 — 충돌 리포트
-- ─────────────────────────────────────────────────────────────
--
-- 거부된 뒤 "무엇과 왜 부딪혔는지"를 사람에게 보여준다.
-- 충돌 상대 계약 · 겹치는 지역/기간 · 양측 근거 조항을 반환한다(요구사항 3항목).
--
-- 판정이 아니라 설명이다. 판정은 EXCLUDE와 트리거가 이미 끝냈다.
CREATE OR REPLACE FUNCTION rights_conflict_report(
    p_tenant_id   uuid,
    p_content_id  bigint,
    p_rights_type rights_type_kind,
    p_territory   char(2),
    p_period      daterange,
    p_exclusivity exclusivity_kind
)
RETURNS TABLE (
    conflict_layer     text,
    existing_grant_id  bigint,
    existing_contract  text,
    territory          char(2),
    overlap_period     daterange,
    overlap_days       int,
    existing_exclusivity exclusivity_kind,
    existing_clause    text,
    existing_quote     text
)
LANGUAGE sql STABLE AS $$
    SELECT
        -- 어느 층이 잡았을 조합인지 — D-05의 XOR 분할과 같은 기준이다
        CASE
          WHEN p_exclusivity <> 'non_exclusive' AND g.exclusivity <> 'non_exclusive'
            THEN 'no_exclusive_overlap'
          ELSE 'no_exclusivity_conflict'
        END,
        g.id,
        c.counterparty,
        g.territory,
        g.period * p_period,
        (upper(g.period * p_period) - lower(g.period * p_period))::int,
        g.exclusivity,
        g.source_clause,
        g.source_quote
    FROM rights_grant g
    JOIN contract c
      ON c.id = g.contract_id AND c.tenant_id = g.tenant_id
    WHERE g.tenant_id   = p_tenant_id
      AND g.content_id  = p_content_id
      AND g.rights_type = p_rights_type
      AND g.territory   = p_territory
      AND g.period     && p_period
      -- D-17 — draft·review·terminated 상대와는 애초에 충돌이 성립하지 않는다.
      AND g.status IN ('provisional', 'complete')
      -- 비독점끼리는 충돌이 아니다 (통과 조합)
      AND NOT (p_exclusivity = 'non_exclusive' AND g.exclusivity = 'non_exclusive')
    ORDER BY g.period;
$$;

-- ─────────────────────────────────────────────────────────────
-- 자문 경고 — 판정이 아니다 (데모 시나리오 1)
-- ─────────────────────────────────────────────────────────────
--
-- 같은 TV_LINEAR 권리라도 한국은 방송권, 일본은 공중송신권 범주로 다루고
-- 음악저작권 정산 관행이 다르다. 계약서 텍스트가 "정상"으로 보여도 이 차이는
-- 드러나지 않는다 — 겨울연가·NHK 유형의 분쟁이 여기서 나온다.
--
-- 저장을 거부하지 않는다. 관행 차이는 결정론적 판정의 대상이 아니며(P-2),
-- 이걸 EXCLUDE에 넣으면 판정이 오염된다. 사람에게 띄우는 경고까지가 시스템의 몫이다.
CREATE OR REPLACE FUNCTION rights_advisory(
    p_rights_type  rights_type_kind,
    p_territory    char(2)
)
RETURNS TABLE (
    statutory_code text,
    name_local     text,
    advisory       text
)
LANGUAGE sql STABLE AS $$
    SELECT m.statutory_code, s.name_local, m.advisory
    FROM right_mapping m
    JOIN statutory_right s ON s.code = m.statutory_code
    WHERE m.rights_type  = p_rights_type
      AND m.jurisdiction = p_territory
      AND m.advisory IS NOT NULL;
$$;

-- ─────────────────────────────────────────────────────────────
-- history 자동 기록 (D-17, D-18)
-- ─────────────────────────────────────────────────────────────
--
-- rights_grant의 모든 실제 변경(INSERT·UPDATE)을 DB가 기록한다 — 앱이 빠뜨려도
-- 로그가 비지 않는다는 change_log(05)와 같은 원칙(P-4)이다.
--
-- INSERT → 'registered'. UPDATE에서 status가 'terminated'로 바뀌면 'terminated',
-- 그 외 UPDATE는 'status_changed'.
--
-- source_history_id는 register_rights_grant()가 세션 로컬 GUC로 넘겨준다 — 트리거는
-- NEW/OLD 행만 보므로 "어느 parsed 행에서 등록됐는지"를 직접 알 방법이 없다.
-- 값이 없으면(=이 함수를 거치지 않은 직접 INSERT) NULL로 남는다.
CREATE OR REPLACE FUNCTION record_rights_grant_history() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_event text;
  v_src   bigint;
BEGIN
  IF TG_OP = 'INSERT' THEN
    v_event := 'registered';
    v_src := NULLIF(current_setting('mindex.source_history_id', true), '')::bigint;
  ELSIF NEW.status = 'terminated' AND OLD.status <> 'terminated' THEN
    v_event := 'terminated';
    v_src := NULL;
  ELSE
    v_event := 'status_changed';
    v_src := NULL;
  END IF;

  -- D-22 — history_seq 제거됨. id(bigserial)가 삽입 순서를 이미 보장한다.
  INSERT INTO rights_grant_history (
      tenant_id, contract_id, content_id, rights_grant_id,
      event_type, source_history_id, status_at_event,
      territory, rights_type, period, exclusivity,
      confidence, source_page, source_clause, source_quote
  ) VALUES (
      NEW.tenant_id, NEW.contract_id, NEW.content_id, NEW.id,
      v_event, v_src, NEW.status,
      NEW.territory, NEW.rights_type, NEW.period, NEW.exclusivity,
      NEW.confidence, NEW.source_page, NEW.source_clause, NEW.source_quote
  );

  RETURN NULL;
END;
$$;

CREATE TRIGGER rights_grant_history_ins
  AFTER INSERT ON rights_grant
  FOR EACH ROW EXECUTE FUNCTION record_rights_grant_history();

CREATE TRIGGER rights_grant_history_upd
  AFTER UPDATE ON rights_grant
  FOR EACH ROW EXECUTE FUNCTION record_rights_grant_history();

-- ─────────────────────────────────────────────────────────────
-- probe — INSERT 시도 후 무조건 롤백 (D-17)
-- ─────────────────────────────────────────────────────────────
--
-- "마스터 DB에 쿼리를 찔러서 충돌 여부를 확인한다"의 구현. rights_conflict_report()
-- 같은 별도 비교 로직을 다시 짜지 않고, 실제 EXCLUDE·트리거를 그대로 통과시켜
-- 결과를 얻는다 — 판정 로직이 두 곳에서 갈라지는 것(P-2 위반 소지)을 막는다.
--
-- plpgsql의 BEGIN ... EXCEPTION 블록은 진입 시 암묵적으로 SAVEPOINT를 찍고
-- 예외가 나면 그 지점으로 ROLLBACK한다 — 스파이크 9(spike-p2/16)에서 확인한
-- SQL 레벨 SAVEPOINT와 동일한 메커니즘이다(advisory lock도 같은 시점에 풀린다).
-- 성공(=충돌 없음)했을 때도 행을 남기면 안 되므로, 일부러 센티넬 예외를 던져
-- 무조건 서브트랜잭션을 되돌린다. INSERT가 만든 부수효과(history 트리거 기록 등)도
-- 이 롤백 범위 안에 있으므로 함께 사라진다.
CREATE OR REPLACE FUNCTION probe_rights_conflict(
    p_tenant_id   uuid,
    p_contract_id bigint,
    p_content_id  bigint,
    p_rights_type rights_type_kind,
    p_territory   char(2),
    p_period      daterange,
    p_exclusivity exclusivity_kind
)
RETURNS text  -- conflict_code. NULL이면 충돌 없음
LANGUAGE plpgsql AS $$
DECLARE
  v_conflict_code text;
BEGIN
  BEGIN
    INSERT INTO rights_grant
        (tenant_id, contract_id, content_id, status, territory, rights_type, period, exclusivity)
    VALUES
        (p_tenant_id, p_contract_id, p_content_id, 'provisional',
         p_territory, p_rights_type, p_period, p_exclusivity);

    -- 여기 도달 = 충돌 없이 INSERT가 통과했다는 뜻. probe이므로 무조건 되돌린다.
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = '__mindex_probe_rollback__';
  EXCEPTION
    WHEN exclusion_violation THEN
      -- no_exclusive_overlap(EXCLUDE) 또는 no_exclusivity_conflict(트리거) 둘 다
      -- SQLSTATE 23P01이라 이 한 분기로 잡힌다 (D-05의 설계 의도 그대로).
      GET STACKED DIAGNOSTICS v_conflict_code = CONSTRAINT_NAME;
    WHEN SQLSTATE 'P0001' THEN
      IF SQLERRM = '__mindex_probe_rollback__' THEN
        v_conflict_code := NULL;
      ELSE
        RAISE;
      END IF;
  END;

  RETURN v_conflict_code;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 등록 — history의 parsed 행을 실제 rights_grant로 (D-17)
-- ─────────────────────────────────────────────────────────────
--
-- probe와 시점이 다르므로 여기서 다시 진짜 판정을 받는다 — probe 이후 다른 등록이
-- 끼어들었으면 여기서 실제로 막힌다. 성공하면 트리거가 'registered' history 행을
-- 자동으로 남기고, source_history_id로 원본 parsed 행과 연결한다.
CREATE OR REPLACE FUNCTION register_rights_grant(
    p_history_id bigint,
    p_status     rights_grant_status DEFAULT 'provisional'
)
RETURNS bigint  -- 새 rights_grant.id
LANGUAGE plpgsql AS $$
DECLARE
  h rights_grant_history%ROWTYPE;
  v_new_id bigint;
BEGIN
  -- FOR UPDATE로 이 parsed 행에 대한 동시 등록 시도를 직렬화한다. D-22 — 이 행
  -- 자체는 더 이상 UPDATE하지 않지만(진짜 append-only), 행 잠금 자체는 여전히
  -- "같은 history_id로 동시에 register 호출" 경합을 막아 준다. 먼저 커밋된 쪽이
  -- 남긴 'registered' 이벤트를 뒤 트랜잭션이 잠금 해제 후 EXISTS로 보고 걸러낸다.
  SELECT * INTO h FROM rights_grant_history WHERE id = p_history_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'history 행 %를 찾을 수 없다', p_history_id;
  END IF;
  IF h.event_type <> 'parsed' THEN
    RAISE EXCEPTION 'history 행 %는 parsed 이벤트가 아니다 (event_type=%)', p_history_id, h.event_type;
  END IF;
  IF EXISTS (
      SELECT 1 FROM rights_grant_history
      WHERE source_history_id = p_history_id AND event_type = 'registered'
  ) THEN
    RAISE EXCEPTION 'history 행 %는 이미 등록됐다', p_history_id;
  END IF;
  IF p_status NOT IN ('provisional', 'complete', 'draft', 'review') THEN
    RAISE EXCEPTION '등록 상태로 쓸 수 없다: %', p_status;
  END IF;

  PERFORM set_config('mindex.source_history_id', p_history_id::text, true);

  INSERT INTO rights_grant (
      tenant_id, contract_id, content_id, status,
      territory, rights_type, period, exclusivity,
      confidence, source_page, source_clause, source_quote
  ) VALUES (
      h.tenant_id, h.contract_id, h.content_id, p_status,
      h.territory, h.rights_type, h.period, h.exclusivity,
      h.confidence, h.source_page, h.source_clause, h.source_quote
  )
  RETURNING id INTO v_new_id;

  -- D-22 — 원본 parsed 행은 건드리지 않는다. 방금 트리거가 자동 기록한
  -- 'registered' history 행의 source_history_id = p_history_id 연결만으로
  -- "이 parsed가 어느 rights_grant로 이어졌는지"가 충분히 추적된다.
  RETURN v_new_id;
END;
$$;

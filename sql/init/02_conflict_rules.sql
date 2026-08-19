-- 02_conflict_rules.sql — 충돌 판정 2단(트리거) + 감사 로그 + WAIVER + 후보 워크플로우
-- (D-05·D-06·D-07·D-24·D-25·D-27, SFR-007·011)
--
-- 이 파일이 담당하는 것:
--   1. sync_rights_grant_spans()          — 판정축 코드 → nested-set span 비정규화 (D-27)
--   2. guard_taxonomy_frozen()            — 데이터가 있는 상태의 taxonomy 좌표 변경 차단 (D-27)
--   3. check_exclusivity_conflict()       — 독점↔비독점 XOR 충돌 (D-05·D-06·D-07)
--   4. record_rights_grant_history()      — rights_grant 감사 로그 자동 기록
--   5. classify_candidate()               — candidate INSERT 시 검토 사유 자동 분류
--   6. evaluate_candidate()               — 판정 실행: rights_evaluation + 사유 N행 (D-27)
--   7. rights_advisory()                  — 자문 경고 (판정 아님)
--   8. register_candidate()               — candidate 승인 → rights_grant 실제 INSERT (최종 게이트)
--   9. validate_resolution_target()       — conflict_resolution 대상 사유 검증 (D-27)
--  10. apply_waiver_termination()         — WAIVER 승인 → 기존 rights_grant TERMINATED
--  11. validate_contract_finalize()       — contract.status='final' 전환 검증
--  12. probe_rights()                    — 검증 probe: INSERT 후 강제 롤백 (D-28)

-- ─────────────────────────────────────────────────────────────
-- 1. 판정축 span 비정규화 (D-27)
-- ─────────────────────────────────────────────────────────────
--
-- EXCLUDE의 키 표현식은 서브쿼리를 못 쓴다 — 참조 테이블에서 조인해 올 수
-- 없으므로 span이 rights_grant 행에 실물로 있어야 한다. 그 비정규화를 앱이
-- 아니라 DB가 한다: 앱이 span 컬럼에 무엇을 넣든 여기서 덮어쓴다.
--
-- 앱이 span을 직접 쓸 수 있게 두면 "코드는 SVOD인데 span은 THEATRICAL"인 행을
-- 만들 수 있고, 그러면 EXCLUDE가 정상 동작하면서 충돌을 조용히 놓친다.
-- 에러도 경고도 없는 그 실패 모드가 정확히 P-4가 막으려는 것이다.
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
-- 2. taxonomy 좌표 동결 (D-27)
-- ─────────────────────────────────────────────────────────────
--
-- 비정규화의 대가다. 참조 taxonomy의 lft/rgt가 바뀌면 이미 저장된
-- rights_grant.*_span이 전부 낡은 좌표계를 가리키게 되고, EXCLUDE는 그걸
-- 알아채지 못한 채 계속 "정상 동작"한다.
--
-- D-10(alembic 미도입, `docker compose down -v` 재생성 전제)과 같은 노선이다 —
-- taxonomy 변경은 마이그레이션이 아니라 재초기화로 처리한다.
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
-- 3. 충돌 판정 2단 — 트리거 (D-05·D-06·D-07)
-- ─────────────────────────────────────────────────────────────
--
-- 담당: 독점/sole ↔ 비독점. 독점끼리는 EXCLUDE가 맡는다(01_schema.sql).
-- 담당을 XOR로 배타 분할해 "어느 층이 잡았는지"가 결정론적으로 구분되게 한다.
--
-- D-27 — 유일하게 바뀐 것은 조인 조건이다. rights_type 동등비교 한 줄이
-- 두 판정축의 span 겹침 두 줄이 됐다. EXCLUDE와 정확히 같은 비교식이어야
-- XOR 분할이 성립한다 — 한쪽만 고치면 두 층 사이에 판정되지 않는 틈이 생긴다.
-- 격리수준 가드·advisory lock·STATEMENT 트리거 구조는 스파이크 1~9로 실측된 그대로다.
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

  -- D-07·D-29 — 팬텀 차단. 설치 단위가 곧 회사 경계이므로 ip_id로 잠근다.
  FOR k IN
    SELECT DISTINCT ip_id FROM new_rows
    WHERE status IN ('approved', 'final')
    ORDER BY ip_id
  LOOP
    PERFORM pg_advisory_xact_lock(k.ip_id);
  END LOOP;

  SELECT n.id AS new_id, g.id AS old_id
    INTO hit
  FROM new_rows n
  JOIN rights_grant g
    ON  g.ip_id                  =  n.ip_id
    AND g.legal_right_span       && n.legal_right_span
    AND g.exploitation_mode_span && n.exploitation_mode_span
    AND g.territory              =  n.territory
    AND g.period                 && n.period
    AND g.id <> n.id
  -- XOR — 정확히 한쪽만 비독점일 때. 양쪽 독점은 EXCLUDE, 양쪽 비독점은 정상.
  WHERE (g.exclusivity = 'non_exclusive') <> (n.exclusivity = 'non_exclusive')
    AND n.status IN ('approved', 'final')
    AND g.status IN ('approved', 'final')
  LIMIT 1;

  IF FOUND THEN
    -- SQLSTATE를 EXCLUDE와 같은 23P01로 맞추는 이유: 앱의 SFR-011 핸들러가
    -- ExclusionViolation 하나만 잡으면 되고, 어느 층이 잡았는지는
    -- diag.constraint_name으로 구분한다(constraint_reason_map으로 번역).
    RAISE EXCEPTION
      '독점권과 비독점권이 같은 구간에 겹친다 (신규 행 %, 기존 행 %)', hit.new_id, hit.old_id
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
-- 4. history 자동 기록 (D-18, D-24)
-- ─────────────────────────────────────────────────────────────
--
-- change_reason/changed_by는 세션 GUC(mindex.change_reason/mindex.changed_by)로
-- 넘겨받는다 — register_candidate()와 apply_waiver_termination()이 채운다.
-- D-27 — 스냅샷 컬럼 rights_type 하나가 판정축 2개로 늘었다. span은 파생값이라
-- 스냅샷하지 않는다.
CREATE OR REPLACE FUNCTION record_rights_grant_history() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_event text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    v_event := 'registered';
  ELSIF NEW.status = 'terminated' AND OLD.status <> 'terminated' THEN
    v_event := 'terminated';
  ELSIF NEW.status = 'final' AND OLD.status <> 'final' THEN
    v_event := 'finalized';
  ELSE
    v_event := 'status_changed';
  END IF;

  INSERT INTO rights_grant_history (
      rights_grant_id, contract_id, document_id,
      event_type, status_at_event,
      territory, legal_right, exploitation_mode, period, exclusivity,
      changed_by, change_reason
  ) VALUES (
      NEW.id, NEW.contract_id, NEW.document_id,
      v_event, NEW.status,
      NEW.territory, NEW.legal_right, NEW.exploitation_mode, NEW.period, NEW.exclusivity,
      NULLIF(current_setting('mindex.changed_by', true), ''),
      NULLIF(current_setting('mindex.change_reason', true), '')
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
-- 5. candidate 자동 분류 (D-25, D-27)
-- ─────────────────────────────────────────────────────────────
--
-- DB가 판단할 수 있는 것만 DB가 한다(P-2). 여기서 판단 가능한 것은
-- "컬럼이 NULL인가"와 "confidence가 임계치 미만인가" 둘뿐이다.
--
-- D-27 — MISSING과 UNRESOLVED를 구분한다. 이 트리거는 *_MISSING만 찍는다:
--   territory IS NULL          → TERRITORY_MISSING     (DB가 안다)
--   "Worldwide except Korea"   → TERRITORY_UNRESOLVED  (추출기만 안다)
-- 후자는 원문에 표현이 있는데 정규화에 실패한 경우라 DB로서는 구별할 방법이
-- 없다. 그래서 앱이 review_reason_code를 채워 INSERT하면 그 값을 존중한다 —
-- D-25부터 있던 "앱이 판단한 사유는 덮어쓰지 않는다" 규칙 그대로다.
-- 근거 원문은 candidate_evidence.source_quote에 남는다.
--
-- 여러 필드가 동시에 비면 severity가 가장 높은 사유 하나를 대표로 찍는다.
-- 나머지 필드의 사유는 evaluate_candidate()가 사유 행으로 전부 남긴다.
CREATE OR REPLACE FUNCTION classify_candidate() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_code text;
BEGIN
  IF NEW.review_reason_code IS NOT NULL THEN
    -- 앱이 이미 판단해서 넘긴 사유가 있으면 그대로 둔다. 다만 검토 사유로
    -- 쓸 수 없는 코드(CONFLICT 전용 등)를 넘긴 것은 앱 로직 에러다.
    IF NOT EXISTS (
        SELECT 1 FROM reason_code
        WHERE code = NEW.review_reason_code AND is_review_trigger AND active
    ) THEN
      RAISE EXCEPTION
        'review_reason_code %는 검토 사유로 쓸 수 없는 코드다 (is_review_trigger=false 또는 비활성)',
        NEW.review_reason_code;
    END IF;
    NEW.status := 'review';
    RETURN NEW;
  END IF;

  -- 비어 있는 필드 중 가장 중대한 사유 하나를 고른다.
  SELECT rc.code INTO v_code
  FROM reason_code rc
  WHERE rc.code = ANY (ARRAY[
        CASE WHEN NEW.legal_right       IS NULL THEN 'RIGHT_MISSING'             END,
        CASE WHEN NEW.exploitation_mode IS NULL THEN 'EXPLOITATION_MODE_MISSING' END,
        CASE WHEN NEW.territory         IS NULL THEN 'TERRITORY_MISSING'         END,
        CASE WHEN NEW.period            IS NULL THEN 'PERIOD_MISSING'            END,
        CASE WHEN NEW.exclusivity       IS NULL THEN 'EXCLUSIVITY_MISSING'       END
      ])
  ORDER BY rc.severity DESC
  LIMIT 1;

  IF v_code IS NOT NULL THEN
    NEW.status := 'review';
    NEW.review_reason_code := v_code;
  ELSIF NEW.confidence IS NOT NULL AND NEW.confidence < 0.85 THEN
    -- SFR-004 — 신뢰도 임계값 0.85. D-17 시절부터 쓰던 기준 그대로.
    NEW.status := 'review';
    NEW.review_reason_code := 'LOW_CONFIDENCE';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER candidate_classify
  BEFORE INSERT ON rights_grant_candidate
  FOR EACH ROW EXECUTE FUNCTION classify_candidate();

-- ─────────────────────────────────────────────────────────────
-- 6. 판정 — candidate ↔ 기존 rights_grant (D-27)
-- ─────────────────────────────────────────────────────────────
--
-- 옛 detect_candidate_conflicts()를 대체한다. 이름이 바뀐 이유는 이 함수가
-- 이제 충돌만 찾지 않기 때문이다 — NORMAL·CONFLICT·REVIEW_REQUIRED·WARNING
-- 네 결과를 모두 산출한다.
--
-- 산출물은 2층이다: rights_evaluation 1행(결과) + rights_evaluation_reason N행(사유).
-- 호출할 때마다 새 evaluation 행이 쌓이고, "현재 판정"은 candidate별 MAX(id)다.
-- WAIVER로 기존 권리를 정리한 뒤 재호출하면 새 판정이 NORMAL로 나오는 식이다.
--
-- D-24의 논리는 그대로 유효하다: 이 함수가 놓친 충돌이 있어도 최종 게이트인
-- register_candidate()의 rights_grant INSERT가 EXCLUDE로 잡는다. 여기가 틀리면
-- 미리보기가 부정확할 뿐 DB 무결성은 안 깨진다.
CREATE OR REPLACE FUNCTION evaluate_candidate(p_candidate_id bigint)
RETURNS result_kind
LANGUAGE plpgsql AS $$
DECLARE
  v_cand      rights_grant_candidate%ROWTYPE;
  v_eval_id   bigint;
  v_lr_span   int4range;
  v_em_span   int4range;
  v_result    result_kind;
  v_advisory  text;
BEGIN
  SELECT * INTO v_cand FROM rights_grant_candidate WHERE id = p_candidate_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate 행 %를 찾을 수 없다', p_candidate_id;
  END IF;

  INSERT INTO rights_evaluation (candidate_id, result_type)
  VALUES (v_cand.id, 'NORMAL')
  RETURNING id INTO v_eval_id;

  -- ── (a) 미확정 필드 — 필드별로 사유를 남긴다 ────────────────
  -- classify_candidate()는 대표 사유 하나만 찍지만 여기서는 전부 남긴다.
  -- 사용자는 무엇을 채워야 하는지 다 알아야 한다.
  INSERT INTO rights_evaluation_reason (evaluation_id, reason_code, deterministic_detail)
  SELECT v_eval_id, c.code, jsonb_build_object('field', c.field)
  FROM (VALUES
        ('legal_right',       'RIGHT_MISSING',             v_cand.legal_right IS NULL),
        ('exploitation_mode', 'EXPLOITATION_MODE_MISSING', v_cand.exploitation_mode IS NULL),
        ('territory',         'TERRITORY_MISSING',         v_cand.territory IS NULL),
        ('period',            'PERIOD_MISSING',            v_cand.period IS NULL),
        ('exclusivity',       'EXCLUSIVITY_MISSING',       v_cand.exclusivity IS NULL)
       ) AS c(field, code, is_missing)
  WHERE c.is_missing;

  -- ── (b) 앱/사람이 지정한 검토 사유 (*_UNRESOLVED · LOW_CONFIDENCE 등) ──
  --
  -- CONFLICT 계열은 여기서 옮기지 않는다. 충돌 사유는 반드시 (c)의 실제 비교로만
  -- 생성돼야 한다 — 지난 판정에서 붙었던 EXCLUSIVE_RIGHT_OVERLAP이 candidate에
  -- 남아 있다가 재판정 때 따라 들어오면, WAIVER로 충돌 원인을 없앤 뒤에도
  -- 판정이 영영 CONFLICT로 굳는다. candidate.review_reason_code는 "왜 검토가
  -- 필요했는지"의 이력이지 "지금도 충돌한다"는 사실이 아니다.
  --
  -- (a)에서 이미 같은 코드가 들어갔으면 중복시키지 않는다.
  IF v_cand.review_reason_code IS NOT NULL THEN
    INSERT INTO rights_evaluation_reason (evaluation_id, reason_code)
    SELECT v_eval_id, v_cand.review_reason_code
    WHERE EXISTS (
            SELECT 1 FROM reason_code
            WHERE code = v_cand.review_reason_code
              AND is_decision_reason AND active
              AND result_type <> 'CONFLICT'
          )
      AND NOT EXISTS (
            SELECT 1 FROM rights_evaluation_reason
            WHERE evaluation_id = v_eval_id AND reason_code = v_cand.review_reason_code
          );
  END IF;

  -- ── (c) 판정축이 전부 확정된 경우에만 실제 비교를 한다 ──────
  IF v_cand.legal_right IS NOT NULL AND v_cand.exploitation_mode IS NOT NULL
     AND v_cand.territory IS NOT NULL AND v_cand.period IS NOT NULL
     AND v_cand.exclusivity IS NOT NULL THEN

    SELECT span INTO v_lr_span FROM legal_right       WHERE code = v_cand.legal_right;
    SELECT span INTO v_em_span FROM exploitation_mode WHERE code = v_cand.exploitation_mode;

    -- R3·R4·R5·R6·R7 — EXCLUDE와 같은 비교식이다.
    INSERT INTO rights_evaluation_reason (
        evaluation_id, reason_code,
        conflicting_grant_id, overlap_period, deterministic_detail
    )
    SELECT
        v_eval_id, 'EXCLUSIVE_RIGHT_OVERLAP',
        g.id,
        g.period * v_cand.period,
        jsonb_build_object(
            'existing_grant_id',        g.id,
            'existing_contract_id',     g.contract_id,
            'territory',                g.territory,
            'existing_legal_right',     g.legal_right,
            'candidate_legal_right',    v_cand.legal_right,
            'existing_exploitation_mode',  g.exploitation_mode,
            'candidate_exploitation_mode', v_cand.exploitation_mode,
            -- 어느 축이 상위-하위 포함관계로 겹쳤는지 화면이 설명할 수 있게 남긴다
            'legal_right_relation',
                CASE WHEN g.legal_right = v_cand.legal_right THEN 'same'
                     WHEN g.legal_right_span @> v_lr_span    THEN 'existing_is_broader'
                     WHEN v_lr_span @> g.legal_right_span    THEN 'candidate_is_broader'
                     ELSE 'overlap' END,
            'exploitation_mode_relation',
                CASE WHEN g.exploitation_mode = v_cand.exploitation_mode THEN 'same'
                     WHEN g.exploitation_mode_span @> v_em_span          THEN 'existing_is_broader'
                     WHEN v_em_span @> g.exploitation_mode_span          THEN 'candidate_is_broader'
                     ELSE 'overlap' END,
            'overlap_period',        (g.period * v_cand.period)::text,
            'overlap_days',          (upper(g.period * v_cand.period) - lower(g.period * v_cand.period)),
            'existing_exclusivity',  g.exclusivity,
            'candidate_exclusivity', v_cand.exclusivity,
            -- 어느 층이 잡을 조합인지 — D-05의 XOR 분할과 같은 기준
            'blocking_layer',
                CASE WHEN v_cand.exclusivity <> 'non_exclusive' AND g.exclusivity <> 'non_exclusive'
                     THEN 'no_exclusive_overlap' ELSE 'no_exclusivity_conflict' END
        )
    FROM rights_grant g
    WHERE g.ip_id                  =  v_cand.ip_id
      AND g.legal_right_span       && v_lr_span
      AND g.exploitation_mode_span && v_em_span
      AND g.territory              =  v_cand.territory
      AND g.period                 && v_cand.period
      AND g.status IN ('approved', 'final')
      -- 비독점끼리는 충돌이 아니다 (통과 조합)
      AND NOT (v_cand.exclusivity = 'non_exclusive' AND g.exclusivity = 'non_exclusive');

    -- ── (d) 두 판정축 조합이 이 관할에서 통상적인가 (R3×R4 정합성) ──
    -- 없는 조합을 "틀렸다"고 판정하지 않는다 — 계약서가 실제로 그렇게 쓰였을
    -- 수 있다. 사람이 한 번 보라는 뜻으로만 올린다.
    IF NOT EXISTS (
        SELECT 1 FROM right_mapping m
        WHERE m.legal_right       = v_cand.legal_right
          AND m.exploitation_mode = v_cand.exploitation_mode
          AND m.jurisdiction      = v_cand.territory
          AND m.is_typical
    ) AND NOT EXISTS (
        SELECT 1 FROM rights_evaluation_reason
        WHERE evaluation_id = v_eval_id AND reason_code = 'AMBIGUOUS_CLAUSE'
    ) THEN
      INSERT INTO rights_evaluation_reason (evaluation_id, reason_code, deterministic_detail)
      VALUES (v_eval_id, 'AMBIGUOUS_CLAUSE',
              jsonb_build_object(
                  'legal_right',       v_cand.legal_right,
                  'exploitation_mode', v_cand.exploitation_mode,
                  'jurisdiction',      v_cand.territory,
                  'note', '해당 관할에서 통상 성립하는 조합으로 등록돼 있지 않다'));
    END IF;

    -- ── (e) 자문 경고 — 판정이 아니라 업무 리스크 (WARNING) ────
    SELECT m.advisory INTO v_advisory
    FROM right_mapping m
    WHERE m.legal_right       = v_cand.legal_right
      AND m.exploitation_mode = v_cand.exploitation_mode
      AND m.jurisdiction      = v_cand.territory
      AND m.advisory IS NOT NULL;

    IF v_advisory IS NOT NULL THEN
      INSERT INTO rights_evaluation_reason (evaluation_id, reason_code, deterministic_detail)
      VALUES (v_eval_id, 'CROSS_BORDER_MUSIC_CLEARANCE',
              jsonb_build_object('advisory', v_advisory, 'jurisdiction', v_cand.territory));
    END IF;
  END IF;

  -- ── (f) 결과 확정 — 가장 중대한 사유의 result_type이 판정 결과다 ──
  -- result_kind ENUM의 정의 순서('NORMAL','CONFLICT','REVIEW_REQUIRED','WARNING')가
  -- 곧 중대도 순이라 MIN()이 가장 중대한 결과를 고른다. 사유가 하나도 없으면
  -- NULL이 되고 COALESCE가 NORMAL로 떨어뜨린다.
  SELECT COALESCE(MIN(rc.result_type), 'NORMAL') INTO v_result
  FROM rights_evaluation_reason r
  JOIN reason_code rc ON rc.code = r.reason_code
  WHERE r.evaluation_id = v_eval_id;

  UPDATE rights_evaluation SET result_type = v_result WHERE id = v_eval_id;

  -- ── (g) 대표 사유 — 화면이 크게 보여줄 하나 ──────────────────
  UPDATE rights_evaluation_reason
     SET is_primary = true
   WHERE id = (
       SELECT r.id
       FROM rights_evaluation_reason r
       JOIN reason_code rc ON rc.code = r.reason_code
       WHERE r.evaluation_id = v_eval_id
       ORDER BY rc.severity DESC, r.id
       LIMIT 1
   );

  -- ── (h) 후보의 검토 상태를 이번 판정 결과에 맞춘다 ──────────
  --
  -- 등록을 막는 사유가 있으면 검토 큐로 보내고, 없으면 검토 큐에서 빼낸다.
  -- 후자가 중요하다 — WAIVER로 충돌을 해소한 뒤 재판정하면 후보가 스스로
  -- 검토 상태를 벗어나야 register_candidate()가 통과한다. 여기서 안 풀면
  -- 해소된 후보가 영영 review에 갇힌다.
  --
  -- WARNING만 있는 경우는 검토 큐로 보내지 않는다 — 등록을 막지 않는 사유다.
  -- 이미 붙어 있던 review_reason_code는 덮어쓰지 않는다(먼저 잡힌 사유가 대개
  -- 더 근본적이다). 검토 상태를 벗어날 때도 코드 자체는 지우지 않는다 —
  -- "왜 한 번 검토가 필요했는지"의 이력이다(D-25).
  IF EXISTS (
      SELECT 1 FROM rights_evaluation_reason r
      JOIN reason_code rc ON rc.code = r.reason_code
      WHERE r.evaluation_id = v_eval_id AND r.status = 'detected' AND rc.is_blocking
  ) THEN
    UPDATE rights_grant_candidate c
       SET status = 'review',
           review_reason_code = COALESCE(
               c.review_reason_code,
               (SELECT r.reason_code
                FROM rights_evaluation_reason r
                JOIN reason_code rc ON rc.code = r.reason_code
                WHERE r.evaluation_id = v_eval_id
                  AND r.status = 'detected' AND rc.is_blocking AND rc.is_review_trigger
                ORDER BY rc.severity DESC, r.id
                LIMIT 1))
     WHERE c.id = p_candidate_id
       AND c.status = 'extracted';
  ELSE
    UPDATE rights_grant_candidate c
       SET status = 'extracted'
     WHERE c.id = p_candidate_id
       AND c.status = 'review';
  END IF;

  RETURN v_result;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 7. 자문 경고 — 판정이 아니다 (데모 시나리오 1)
-- ─────────────────────────────────────────────────────────────
--
-- D-27 — 시그니처가 판정축 2개 + 관할로 바뀌었다. advisory는 이제
-- right_mapping의 (legal_right × exploitation_mode × jurisdiction) 조합에 붙고,
-- 화면에 보여줄 조문명은 statutory_right에서 legal_right_code로 조인해 얻는다.
CREATE OR REPLACE FUNCTION rights_advisory(
    p_legal_right       text,
    p_exploitation_mode text,
    p_territory         char(2)
)
RETURNS TABLE (
    statutory_code text,
    name_local     text,
    advisory       text
)
LANGUAGE sql STABLE AS $$
    SELECT s.code, s.name_local, m.advisory
    FROM right_mapping m
    JOIN statutory_right s
      ON s.jurisdiction     = m.jurisdiction
     AND s.legal_right_code = m.legal_right
    WHERE m.legal_right       = p_legal_right
      AND m.exploitation_mode = p_exploitation_mode
      AND m.jurisdiction      = p_territory
      AND m.advisory IS NOT NULL;
$$;

-- ─────────────────────────────────────────────────────────────
-- 8. 등록 — candidate 승인 → rights_grant 실제 INSERT (D-24, 최종 게이트)
-- ─────────────────────────────────────────────────────────────
--
-- 이 INSERT가 EXCLUDE·트리거를 실제로 통과해야 하는 유일한 지점이다.
-- evaluate_candidate()가 놓친 게 있어도 여기서 진짜로 막힌다.
--
-- D-27 — 게이트 조건이 "미해결 충돌이 있으면 거부"에서 "등록을 막는 사유가
-- 있으면 거부"로 바뀌었다. WARNING(is_blocking=false)만 있는 후보는 통과한다 —
-- 업무 리스크 경고이지 권리 충돌이 아니기 때문이다.
-- 판단 대상은 최신 판정(MAX(id))뿐이다. 지난 판정의 사유가 남아 있어도
-- 재판정으로 해소됐다면 막지 않는다.
CREATE OR REPLACE FUNCTION register_candidate(
    p_candidate_id bigint,
    p_verified_by  text
)
RETURNS bigint  -- 새 rights_grant.id
LANGUAGE plpgsql AS $$
DECLARE
  c rights_grant_candidate%ROWTYPE;
  v_new_id  bigint;
  v_blocker text;
BEGIN
  -- FOR UPDATE로 같은 candidate에 대한 동시 승인 시도를 직렬화한다.
  SELECT * INTO c FROM rights_grant_candidate WHERE id = p_candidate_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'candidate 행 %를 찾을 수 없다', p_candidate_id;
  END IF;
  IF c.status = 'approved' THEN
    RAISE EXCEPTION 'candidate 행 %는 이미 승인됐다', p_candidate_id;
  END IF;
  IF c.status = 'rejected' THEN
    RAISE EXCEPTION 'candidate 행 %는 이미 거부됐다', p_candidate_id;
  END IF;
  IF c.legal_right IS NULL OR c.exploitation_mode IS NULL OR c.territory IS NULL
     OR c.period IS NULL OR c.exclusivity IS NULL THEN
    RAISE EXCEPTION 'candidate 행 %는 필수 필드가 비어 있어 등록할 수 없다', p_candidate_id;
  END IF;
  IF NOT EXISTS (
      SELECT 1 FROM candidate_evidence WHERE candidate_id = p_candidate_id
  ) THEN
    RAISE EXCEPTION 'candidate 행 %는 인용 근거가 없어 등록할 수 없다', p_candidate_id;
  END IF;

  -- 검토 상태인 후보는 등록하지 않는다. 사유가 해소됐다면 evaluate_candidate()를
  -- 다시 돌려야 하고, 그러면 (h)가 상태를 extracted로 되돌린다.
  -- 판정을 거치지 않는 MANUAL_REVIEW·AMBIGUOUS_CLAUSE 지정도 이 관문이 잡는다.
  IF c.status = 'review' THEN
    RAISE EXCEPTION
      'candidate 행 %는 검토 상태다 (사유: %). 값을 보완하거나 충돌을 해소한 뒤 evaluate_candidate()를 다시 실행할 것',
      p_candidate_id, c.review_reason_code;
  END IF;

  SELECT r.reason_code INTO v_blocker
  FROM rights_evaluation e
  JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
  JOIN reason_code rc ON rc.code = r.reason_code
  WHERE e.candidate_id = p_candidate_id
    AND e.id = (SELECT MAX(id) FROM rights_evaluation WHERE candidate_id = p_candidate_id)
    AND r.status = 'detected'
    AND rc.is_blocking
  ORDER BY rc.severity DESC
  LIMIT 1;

  IF v_blocker IS NOT NULL THEN
    RAISE EXCEPTION
      'candidate 행 %에 미해결 사유가 있다: % (conflict_resolution으로 먼저 처리하거나 값을 보완할 것)',
      p_candidate_id, v_blocker;
  END IF;

  -- change_reason은 명시적으로 비운다 — 같은 트랜잭션에서 WAIVER 승인 직후
  -- register_candidate()를 호출하면 apply_waiver_termination()이 남긴
  -- 'mindex.change_reason'(transaction-local GUC)이 이 정상 등록 이벤트에도
  -- 잘못 붙을 수 있다.
  PERFORM set_config('mindex.changed_by', p_verified_by, true);
  PERFORM set_config('mindex.change_reason', '', true);

  -- legal_right_span/exploitation_mode_span은 넘기지 않는다 —
  -- sync_rights_grant_spans()가 BEFORE INSERT에서 코드로부터 유도해 채운다.
  -- BEFORE 트리거는 NOT NULL 검사보다 먼저 돌기 때문에 컬럼을 생략해도 된다.
  INSERT INTO rights_grant (
      contract_id, document_id, source_candidate_id, ip_id,
      territory, legal_right, exploitation_mode,
      period, exclusivity, verified_by
  ) VALUES (
      c.contract_id, c.document_id, c.id, c.ip_id,
      c.territory, c.legal_right, c.exploitation_mode,
      c.period, c.exclusivity, p_verified_by
  )
  RETURNING id INTO v_new_id;

  UPDATE rights_grant_candidate
     SET status = 'approved', decided_by = p_verified_by, decided_at = now()
   WHERE id = p_candidate_id;

  RETURN v_new_id;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 9. conflict_resolution 대상 검증 (D-27)
-- ─────────────────────────────────────────────────────────────
--
-- 해소 대상은 "실제 충돌 사유"여야 한다. REVIEW_REQUIRED(값이 없다)나
-- WARNING(업무 리스크)에 WAIVER를 걸 수는 없다 — 포기시킬 기존 권리 자체가 없다.
-- 다른 테이블을 봐야 해서 CHECK로는 표현할 수 없다.
CREATE OR REPLACE FUNCTION validate_resolution_target() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_result_type result_kind;
  v_grant_id    bigint;
BEGIN
  SELECT rc.result_type, r.conflicting_grant_id
    INTO v_result_type, v_grant_id
  FROM rights_evaluation_reason r
  JOIN reason_code rc ON rc.code = r.reason_code
  WHERE r.id = NEW.evaluation_reason_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION '판정 사유 %를 찾을 수 없다', NEW.evaluation_reason_id;
  END IF;
  IF v_result_type <> 'CONFLICT' THEN
    RAISE EXCEPTION
      '판정 사유 %는 CONFLICT가 아니라 %다 — 충돌 해소 대상이 될 수 없다',
      NEW.evaluation_reason_id, v_result_type;
  END IF;
  IF NEW.resolution_type = 'waiver' AND v_grant_id IS NULL THEN
    RAISE EXCEPTION
      '판정 사유 %에 충돌 상대 rights_grant가 없어 WAIVER를 적용할 수 없다',
      NEW.evaluation_reason_id;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER conflict_resolution_target_check
  BEFORE INSERT OR UPDATE ON conflict_resolution
  FOR EACH ROW EXECUTE FUNCTION validate_resolution_target();

-- ─────────────────────────────────────────────────────────────
-- 10. WAIVER — 승인 시 기존 권리 정리 (D-24)
-- ─────────────────────────────────────────────────────────────
--
-- 충돌을 무시하지 않는다. WAIVER는 "기존 권리자가 권리를 포기했다"는 근거이지
-- "겹쳐도 통과시켜라"가 아니다. conflict_resolution.status가 'approved'로
-- 바뀌는 순간(그리고 resolution_type='waiver'일 때만) 이 트리거가 자동으로
-- 사유 행의 conflicting_grant_id가 가리키는 기존 rights_grant를 TERMINATED로
-- UPDATE한다. 그 UPDATE는 record_rights_grant_history() 트리거를 그대로 타서
-- event_type='terminated' 감사 기록이 자동으로 남는다.
--
-- 그 다음 앱이 evaluate_candidate()를 재호출하고, 통과하면 register_candidate()로
-- 신규 rights_grant를 INSERT한다 — 이 INSERT는 다른 모든 INSERT와 동일하게
-- EXCLUDE를 통과해야 한다. 이 트리거는 EXCLUDE를 우회하지 않는다 — 우회 경로
-- 자체가 존재하지 않는다.
--
-- D-27 — 조회 경로가 conflict_result에서 rights_evaluation_reason으로 바뀌었다.
-- 사유별로 상대 grant가 다를 수 있으므로 정확히 그 사유 하나의 상대만 정리한다.
CREATE OR REPLACE FUNCTION apply_waiver_termination() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_grant_id bigint;
BEGIN
  SELECT r.conflicting_grant_id INTO v_grant_id
  FROM rights_evaluation_reason r
  WHERE r.id = NEW.evaluation_reason_id;

  IF v_grant_id IS NULL THEN
    RAISE EXCEPTION '판정 사유 %에 충돌 상대 rights_grant가 없다', NEW.evaluation_reason_id;
  END IF;

  PERFORM set_config('mindex.changed_by', COALESCE(NEW.approved_by, ''), true);
  PERFORM set_config('mindex.change_reason', 'WAIVER: ' || NEW.reason, true);

  -- 이미 terminated인 행에는 손대지 않는다(멱등) — 같은 WAIVER가 재확인 UPDATE로
  -- 다시 이 트리거를 태워도 두 번째부터는 조용히 0행 UPDATE로 끝난다.
  UPDATE rights_grant
     SET status = 'terminated'
   WHERE id = v_grant_id AND status <> 'terminated';

  UPDATE rights_evaluation_reason
     SET status = 'waived'
   WHERE id = NEW.evaluation_reason_id;

  RETURN NEW;
END;
$$;

CREATE TRIGGER conflict_resolution_waiver
  AFTER INSERT OR UPDATE ON conflict_resolution
  FOR EACH ROW
  WHEN (NEW.status = 'approved' AND NEW.resolution_type = 'waiver')
  EXECUTE FUNCTION apply_waiver_termination();

-- ─────────────────────────────────────────────────────────────
-- 11. contract 최종화 검증 (D-25)
-- ─────────────────────────────────────────────────────────────
--
-- contract.status='final'(계약 업무 확정)과 contract_document.status='final'
-- (여러 PDF 중 실제 체결본 표시)은 서로 다른 의미다 — 자동으로 동기화하지
-- 않는다. 이 트리거는 검증만 하고 다른 테이블의 상태를 바꾸지 않는다:
--   1. final_document_id가 같은 contract_id 소속인지
--   2. 그 문서가 파싱/검토 완료 단계(approved 또는 final)인지
--   3. 이 계약에 미해결(extracted/review) candidate가 안 남아 있는지
-- 충돌·EXCLUDE는 여기서 재검사하지 않는다 — rights_grant INSERT 시점에
-- 이미 통과했어야만 존재하는 것들이라 다시 볼 필요가 없다(이중 판정 방지,
-- D-19와 같은 원칙).
CREATE OR REPLACE FUNCTION validate_contract_finalize() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_doc_status   document_status;
  v_doc_contract bigint;
BEGIN
  IF NEW.final_document_id IS NULL THEN
    RAISE EXCEPTION '계약 %를 final로 전환하려면 final_document_id가 필요하다', NEW.id;
  END IF;

  SELECT status, contract_id INTO v_doc_status, v_doc_contract
  FROM contract_document
  WHERE id = NEW.final_document_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'final_document_id %는 존재하지 않는다', NEW.final_document_id;
  END IF;
  IF v_doc_contract <> NEW.id THEN
    RAISE EXCEPTION 'final_document_id %는 이 계약(%) 소속이 아니다', NEW.final_document_id, NEW.id;
  END IF;
  IF v_doc_status NOT IN ('approved', 'final') THEN
    RAISE EXCEPTION '최종 문서(%)가 아직 파싱/검토 완료 상태가 아니다 (현재: %)', NEW.final_document_id, v_doc_status;
  END IF;

  IF EXISTS (
      SELECT 1 FROM rights_grant_candidate
      WHERE contract_id = NEW.id AND status IN ('extracted', 'review')
  ) THEN
    RAISE EXCEPTION '계약 %에 아직 결론나지 않은 권리 후보가 남아 있다', NEW.id;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER contract_finalize_check
  BEFORE UPDATE ON contract
  FOR EACH ROW
  WHEN (NEW.status = 'final' AND OLD.status IS DISTINCT FROM 'final')
  EXECUTE FUNCTION validate_contract_finalize();

-- ─────────────────────────────────────────────────────────────
-- 12. 검증 probe — 실제로 INSERT하고 전부 되돌린다 (D-28)
-- ─────────────────────────────────────────────────────────────
--
-- 화면의 `검증` 버튼이 호출한다. 사용자가 아직 `권리 등록`을 누르지 않았으므로
-- 커밋되는 것이 하나도 없어야 한다.
--
-- 왜 읽기 전용 SELECT로 재구현하지 않는가:
--   1. EXCLUDE를 진짜로 검증한다. 같은 조건의 SELECT는 EXCLUDE의 재구현일 뿐이라
--      언젠가 갈라진다. 여기서는 rights_grant에 실제 INSERT를 시도한다.
--   2. RFP §6.3.2가 시연에서 제약명(no_exclusive_overlap) 노출을 요구한다(D-08).
--      진짜 위반이라야 diag의 CONSTRAINT_NAME을 받을 수 있다.
--   3. 판정 로직이 한 벌로 유지된다 — evaluate_candidate()를 그대로 부른다.
--
-- 롤백을 앱 규약에 맡기지 않는다. 예외 경로에서 ROLLBACK이 누락되거나 나중에
-- 누가 "이력이 남아야지" 하고 고치면 조용히 쌓인다. EXCEPTION 절이 여는
-- 서브트랜잭션 안에서 sentinel 예외를 던져 되돌리므로 **호출자는 커밋 여부를
-- 고를 수 없다.** PL/pgSQL 변수는 트랜잭션 대상이 아니라서 수집한 결과만 살아남는다.
--
-- 부모 행(ip·contract·contract_document)도 같은 서브트랜잭션에서 만든다.
-- 지어내는 껍데기가 아니라 업로드·추출 단계에서 앱이 이미 들고 있는 값이며
-- 커밋만 되지 않은 상태다. p_ip_id가 NULL이면 신규 작품이라 비교 대상이 없다.
--
-- 부작용: BIGSERIAL 시퀀스는 롤백해도 되돌아가지 않아 ID에 구멍이 생긴다.
-- bigint라 실무상 무해하다. check_exclusivity_conflict()가 잡는
-- pg_advisory_xact_lock은 최상위 트랜잭션이 끝날 때까지 유지되므로,
-- 호출자는 probe 직후 트랜잭션을 오래 열어두지 않는다.
CREATE OR REPLACE FUNCTION probe_rights(
    p_ip_id              bigint,            -- NULL이면 신규 작품
    p_territory          char(2),
    p_legal_right        text,
    p_exploitation_mode  text,
    p_period             daterange,
    p_exclusivity        exclusivity_kind,
    p_confidence         numeric  DEFAULT NULL,
    p_evidence           jsonb    DEFAULT '[{"page_start":1,"source_quote":"(검증 단계 — 미저장)"}]'::jsonb,
    p_review_reason_code text     DEFAULT NULL
)
RETURNS TABLE (
    result_type          result_kind,
    reason_code          text,
    is_primary           boolean,
    conflicting_grant_id bigint,
    overlap_period       daterange,
    detail               jsonb,
    constraint_name      text     -- EXCLUDE/트리거가 실제로 잡았을 때의 제약명
)
LANGUAGE plpgsql AS $$
DECLARE
  v_ip         bigint;
  v_contract   bigint;
  v_document   bigint;
  v_cand       bigint;
  v_result     result_kind;
  v_rows       jsonb;
  v_constraint text;
BEGIN
  BEGIN  -- ← EXCEPTION 절이 서브트랜잭션을 연다. 이 블록의 쓰기는 전부 되돌아간다.

    IF p_ip_id IS NULL THEN
      INSERT INTO ip (title_ko) VALUES ('(검증)')
      RETURNING id INTO v_ip;
    ELSE
      v_ip := p_ip_id;
    END IF;

    INSERT INTO contract (counterparty) VALUES ('(검증)')
    RETURNING id INTO v_contract;

    INSERT INTO contract_document
      (contract_id, version, file_name, storage_key, file_hash)
    VALUES (v_contract, 1, '(검증)', '(검증)', '(검증)')
    RETURNING id INTO v_document;

    INSERT INTO rights_grant_candidate (
        contract_id, document_id, ip_id,
        territory, legal_right, exploitation_mode, period, exclusivity,
        confidence, review_reason_code
    ) VALUES (
        v_contract, v_document, v_ip,
        p_territory, p_legal_right, p_exploitation_mode, p_period, p_exclusivity,
        p_confidence, p_review_reason_code
    ) RETURNING id INTO v_cand;

    IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'array'
       OR jsonb_array_length(p_evidence) = 0 THEN
      RAISE EXCEPTION '검증할 candidate에는 evidence 배열이 한 건 이상 필요하다';
    END IF;

    INSERT INTO candidate_evidence
      (candidate_id, page_start, page_end, source_clause, source_quote)
    SELECT v_cand, e.page_start, e.page_end, e.source_clause, e.source_quote
    FROM jsonb_to_recordset(p_evidence) AS e(
      page_start int, page_end int, source_clause text, source_quote text
    );

    v_result := evaluate_candidate(v_cand);

    SELECT jsonb_agg(
             jsonb_build_object(
               'reason_code',          r.reason_code,
               'is_primary',           r.is_primary,
               'conflicting_grant_id', r.conflicting_grant_id,
               'overlap_period',       r.overlap_period::text,
               'detail',               r.deterministic_detail
             ) ORDER BY rc.severity DESC, r.id
           ) INTO v_rows
    FROM rights_evaluation e
    JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
    JOIN reason_code rc             ON rc.code = r.reason_code
    WHERE e.candidate_id = v_cand;

    -- ── EXCLUDE 실검증 ────────────────────────────────────────
    -- register_candidate()를 거치지 않고 직접 INSERT한다. 그 함수는 blocking
    -- 사유가 있으면 INSERT 전에 예외를 던지므로, 정작 확인하려는 EXCLUDE가
    -- 한 번도 실행되지 않는다. 여기서 보려는 것은 게이트가 아니라 제약조건이다.
    --
    -- EXCLUDE와 check_exclusivity_conflict()는 둘 다 SQLSTATE 23P01에
    -- CONSTRAINT를 실어 보낸다(D-08). 한 핸들러로 양쪽을 받고 제약명으로 구분한다.
    IF p_territory IS NOT NULL AND p_legal_right IS NOT NULL
       AND p_exploitation_mode IS NOT NULL AND p_period IS NOT NULL
       AND p_exclusivity IS NOT NULL THEN
      BEGIN
        INSERT INTO rights_grant (
            contract_id, document_id, source_candidate_id, ip_id,
            territory, legal_right, exploitation_mode, period, exclusivity, verified_by
        ) VALUES (
            v_contract, v_document, v_cand, v_ip,
            p_territory, p_legal_right, p_exploitation_mode, p_period, p_exclusivity,
            '(probe)'
        );
      EXCEPTION WHEN exclusion_violation THEN
        GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
      END;
    END IF;

    -- 서브트랜잭션 강제 롤백. 호출자에게 커밋 선택지를 주지 않는다.
    RAISE EXCEPTION USING ERRCODE = 'MXP01', MESSAGE = 'PROBE_SENTINEL';

  EXCEPTION WHEN SQLSTATE 'MXP01' THEN
    NULL;  -- 여기 도달한 시점에 위 블록의 쓰기는 전부 되돌아갔다
  END;

  IF v_rows IS NULL THEN
    -- 사유가 하나도 없다 = NORMAL. 결과 한 줄은 돌려줘야 화면이 구분할 수 있다.
    RETURN QUERY SELECT v_result, NULL::text, NULL::boolean, NULL::bigint,
                        NULL::daterange, NULL::jsonb, v_constraint;
  ELSE
    RETURN QUERY
    SELECT v_result,
           x->>'reason_code',
           (x->>'is_primary')::boolean,
           (x->>'conflicting_grant_id')::bigint,
           (x->>'overlap_period')::daterange,
           x->'detail',
           v_constraint
    FROM jsonb_array_elements(v_rows) AS x;
  END IF;
END;
$$;

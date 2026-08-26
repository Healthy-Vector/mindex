-- 03_reference_data.sql — 참조 데이터 시드 (D-15 · D-27 · D-30)
--
-- 테이블 정의는 01_schema.sql에 있다. 여기는 값만 넣는다.
--
-- D-30으로 바뀐 것: country.name_ko/name_en → country_label, territory_group.
-- name_ko → territory_group_label로 i18n 정규화(§1.8). statutory_right ·
-- right_mapping 시드를 완전히 제거했다(§1.9, 둘 다 테이블째 삭제). reason_code
-- 시드에서 is_blocking · is_review_trigger 컬럼과 값을 뺐고, AMBIGUOUS_CLAUSE ·
-- CROSS_BORDER_MUSIC_CLEARANCE는 산출 엔진(rights_advisory · right_mapping)이
-- 사라졌으므로 implemented=false로 되돌렸다.
--
-- legal_right/exploitation_mode의 nested-set 좌표 시드와 자기검증 DO 블록은
-- 이번 재설계에서 변경하지 않는다(§ Context — 2축 판정 구조 유지 결정).

-- ─────────────────────────────────────────────────────────────
-- 국가
-- ─────────────────────────────────────────────────────────────
--
-- in_scope 8개국이 WORLDWIDE 전개 대상이다 (SRS DAR-001).
-- 시나리오 EN-C03(Worldwide 극장권)이 이 8개 기준으로 US·JP·TW 3중 충돌을 기대한다.
-- 8개를 늘리거나 줄이면 그 시나리오의 기대 결과가 바뀐다.
INSERT INTO country (code, in_scope) VALUES
    ('KR', true), ('JP', true), ('US', true), ('CN', true),
    ('TW', true), ('TH', true), ('VN', true), ('SG', true),
    -- 전개 대상 밖. 계약서에 등장할 수 있으므로 어휘로는 유지한다.
    ('GB', false), ('FR', false), ('DE', false), ('ID', false),
    ('MY', false), ('PH', false), ('HK', false), ('AU', false);

INSERT INTO country_label (country_code, lang, label) VALUES
    ('KR', 'ko', '대한민국'),        ('KR', 'en', 'South Korea'),
    ('JP', 'ko', '일본'),            ('JP', 'en', 'Japan'),
    ('US', 'ko', '미국'),            ('US', 'en', 'United States'),
    ('CN', 'ko', '중국'),            ('CN', 'en', 'China'),
    ('TW', 'ko', '대만'),            ('TW', 'en', 'Taiwan'),
    ('TH', 'ko', '태국'),            ('TH', 'en', 'Thailand'),
    ('VN', 'ko', '베트남'),          ('VN', 'en', 'Vietnam'),
    ('SG', 'ko', '싱가포르'),        ('SG', 'en', 'Singapore'),
    ('GB', 'ko', '영국'),            ('GB', 'en', 'United Kingdom'),
    ('FR', 'ko', '프랑스'),          ('FR', 'en', 'France'),
    ('DE', 'ko', '독일'),            ('DE', 'en', 'Germany'),
    ('ID', 'ko', '인도네시아'),      ('ID', 'en', 'Indonesia'),
    ('MY', 'ko', '말레이시아'),      ('MY', 'en', 'Malaysia'),
    ('PH', 'ko', '필리핀'),          ('PH', 'en', 'Philippines'),
    ('HK', 'ko', '홍콩'),            ('HK', 'en', 'Hong Kong'),
    ('AU', 'ko', '호주'),            ('AU', 'en', 'Australia');

-- ─────────────────────────────────────────────────────────────
-- 지역 그룹 — 전개용 참조. 저장 단위가 아니다 (D-15)
-- ─────────────────────────────────────────────────────────────
--
-- 계약서의 '아시아 전역', 'Worldwide', '동남아' 같은 표현을 앱이 여기서 국가로
-- 펼쳐 rights_grant에 국가 수만큼 행을 넣는다.
--
-- 데모 시나리오 2가 이것으로 성립한다 — 웨이브(KR 독점)와 Viu(아시아 전역 독점)가
-- 텍스트만 보면 겹치는지 알 수 없지만, APAC을 펼치면 KR이 나와 충돌이 드러난다.
INSERT INTO territory_group (code, note) VALUES
    ('WORLDWIDE', 'in_scope 국가 8개로 전개한다'),
    ('APAC',      '"아시아 전역" 표현이 여기로 매핑된다'),
    ('SEA',       NULL),
    ('NA',        NULL),
    ('EU',        '전개 대상 밖 국가를 포함한다');

INSERT INTO territory_group_label (group_code, lang, label) VALUES
    ('WORLDWIDE', 'ko', '전 세계'),
    ('APAC',      'ko', '아시아·태평양'),
    ('SEA',       'ko', '동남아시아'),
    ('NA',        'ko', '북미'),
    ('EU',        'ko', '유럽');

INSERT INTO territory_group_member (group_code, country_code)
    SELECT 'WORLDWIDE', code FROM country WHERE in_scope;

INSERT INTO territory_group_member (group_code, country_code) VALUES
    ('APAC', 'KR'), ('APAC', 'JP'), ('APAC', 'CN'), ('APAC', 'TW'),
    ('APAC', 'TH'), ('APAC', 'VN'), ('APAC', 'SG'), ('APAC', 'HK'),
    ('APAC', 'ID'), ('APAC', 'MY'), ('APAC', 'PH'), ('APAC', 'AU'),

    ('SEA', 'TH'), ('SEA', 'VN'), ('SEA', 'SG'),
    ('SEA', 'ID'), ('SEA', 'MY'), ('SEA', 'PH'),

    ('NA', 'US'),

    ('EU', 'GB'), ('EU', 'FR'), ('EU', 'DE');

-- ─────────────────────────────────────────────────────────────
-- 판정축 1 — 법적 권리 (R3). nested-set preorder 좌표 (변경 없음)
-- ─────────────────────────────────────────────────────────────
--
-- 관할 중립 어휘다. 좌표는 손으로 박는다 — 7행짜리 정적 taxonomy라 자동
-- 계산 함수보다 명시 좌표가 검증하기 쉽고, 아래 자가검증 블록이 오타를
-- 즉시 잡는다.
--
--   code                      lft rgt  span     계층
--   PUBLIC_TRANSMISSION        1   6   [1,7)    공중송신권
--     BROADCAST                2   3   [2,4)      └ 방송권
--     TRANSMISSION             4   5   [4,6)      └ 전송권
--   PUBLIC_PERFORMANCE         7   8   [7,9)
--   DISTRIBUTION               9  10   [9,11)
--   REPRODUCTION              11  12   [11,13)
--   DERIVATIVE_WORK_CREATION  13  14   [13,15)
INSERT INTO legal_right (code, parent_code, name_ko, lft, rgt, note) VALUES
    ('PUBLIC_TRANSMISSION', NULL, '공중송신권', 1, 6,
     '방송·전송을 포괄하는 상위 권리. 일본 公衆送信権이 이 층위다'),
    ('BROADCAST',    'PUBLIC_TRANSMISSION', '방송권', 2, 3,
     '동시·비주문형 송신. 선형 TV가 여기 해당한다'),
    ('TRANSMISSION', 'PUBLIC_TRANSMISSION', '전송권', 4, 5,
     '주문형(이용자 선택 시점) 송신. 일본 自動公衆送信·送信可能化権이 여기로 정규화된다'),
    ('PUBLIC_PERFORMANCE', NULL, '공연·상영권', 7, 8,
     '극장 상영이 여기 해당한다'),
    ('DISTRIBUTION', NULL, '배포권', 9, 10,
     '복제물의 양도·대여. 미국 Distribution Right가 여기 대응한다'),
    ('REPRODUCTION', NULL, '복제권', 11, 12, NULL),
    ('DERIVATIVE_WORK_CREATION', NULL, '2차적저작물작성권', 13, 14,
     '리메이크·포맷·시퀄이 이 아래에 있으나 표준계약서가 세분하지 않는 경우가 많다');

-- ─────────────────────────────────────────────────────────────
-- 판정축 2 — 사업적 이용형태 (R4). nested-set preorder 좌표 (변경 없음)
-- ─────────────────────────────────────────────────────────────
--
--   code             lft rgt  span     계층
--   VOD               1   8   [1,9)    주문형 전반
--     SVOD            2   3   [2,4)      └ 구독형
--     AVOD            4   5   [4,6)      └ 광고형
--     TVOD            6   7   [6,8)      └ 건별과금
--   TV_LINEAR         9  10   [9,11)
--   THEATRICAL       11  12   [11,13)
--   AUDIO_STREAMING  13  14   [13,15)
INSERT INTO exploitation_mode (code, parent_code, name_ko, lft, rgt, note) VALUES
    ('VOD', NULL, '주문형 VOD 전반', 1, 8,
     '창구를 특정하지 않은 넓은 부여("all on-demand streaming")를 받는 노드'),
    ('SVOD', 'VOD', '구독형 VOD',    2, 3, NULL),
    ('AVOD', 'VOD', '광고형 VOD',    4, 5, NULL),
    ('TVOD', 'VOD', '건별 과금 VOD',  6, 7, NULL),
    ('TV_LINEAR',       NULL, '선형 TV 방송',   9, 10, NULL),
    ('THEATRICAL',      NULL, '극장 상영·배급', 11, 12, NULL),
    ('AUDIO_STREAMING', NULL, '오디오 스트리밍', 13, 14, 'OST 등 음원 단독 이용');

-- ─────────────────────────────────────────────────────────────
-- 좌표 자가검증 — 여기서 실패하면 EXCLUDE 판정 전체가 조용히 틀린다 (변경 없음)
-- ─────────────────────────────────────────────────────────────
--
-- nested-set은 좌표를 하나만 잘못 박아도 에러 없이 "충돌을 안 잡는" 상태가 된다.
-- CI는 psql -v ON_ERROR_STOP=1로 돌므로 이 블록이 곧 회귀 테스트다.
DO $verify$
DECLARE
  v_bad text;
BEGIN
  -- 1. 부모 span이 자식 span을 진짜로 포함하는가
  FOR v_bad IN
      SELECT c.code FROM legal_right c JOIN legal_right p ON p.code = c.parent_code
      WHERE NOT (p.span @> c.span)
    UNION ALL
      SELECT c.code FROM exploitation_mode c JOIN exploitation_mode p ON p.code = c.parent_code
      WHERE NOT (p.span @> c.span)
  LOOP
    RAISE EXCEPTION 'nested-set 좌표 오류: %의 span이 부모 span에 포함되지 않는다', v_bad;
  END LOOP;

  -- 2. 포함관계 없이 부분적으로 겹치는 쌍이 있는가.
  -- 형제끼리 겹치면 무관한 두 권리가 충돌로 잡히고, 서로 다른 트리끼리 겹치면
  -- 판정이 통째로 엉킨다. 정상적인 nested-set에서 두 노드의 span 관계는
  -- "완전 포함" 아니면 "완전 분리" 둘 중 하나뿐이다.
  FOR v_bad IN
      SELECT a.code || ' / ' || b.code FROM legal_right a JOIN legal_right b ON a.code < b.code
      WHERE a.span && b.span
        AND NOT (a.span @> b.span) AND NOT (b.span @> a.span)
    UNION ALL
      SELECT a.code || ' / ' || b.code FROM exploitation_mode a JOIN exploitation_mode b ON a.code < b.code
      WHERE a.span && b.span
        AND NOT (a.span @> b.span) AND NOT (b.span @> a.span)
  LOOP
    RAISE EXCEPTION 'nested-set 좌표 오류: %의 span이 포함관계 없이 부분적으로 겹친다', v_bad;
  END LOOP;

  -- 3. 좌표상 포함관계와 parent_code 계통이 일치하는가.
  -- 조상-자손이면 포함, 아니면 분리여야 한다. 3단 이상으로 깊어져도 성립하도록
  -- 재귀로 조상 집합을 만들어 비교한다 — 직계 부모만 보면 손자 관계를 오탐한다.
  FOR v_bad IN
    WITH RECURSIVE lr_anc AS (
        SELECT code AS node, parent_code AS anc FROM legal_right WHERE parent_code IS NOT NULL
      UNION ALL
        SELECT a.node, p.parent_code FROM lr_anc a
        JOIN legal_right p ON p.code = a.anc WHERE p.parent_code IS NOT NULL
    ), em_anc AS (
        SELECT code AS node, parent_code AS anc FROM exploitation_mode WHERE parent_code IS NOT NULL
      UNION ALL
        SELECT a.node, p.parent_code FROM em_anc a
        JOIN exploitation_mode p ON p.code = a.anc WHERE p.parent_code IS NOT NULL
    )
      SELECT a.code || ' ⊃ ' || b.code FROM legal_right a JOIN legal_right b ON a.code <> b.code
      WHERE a.span @> b.span
        AND NOT EXISTS (SELECT 1 FROM lr_anc WHERE node = b.code AND anc = a.code)
    UNION ALL
      SELECT a.code || ' ⊃ ' || b.code FROM exploitation_mode a JOIN exploitation_mode b ON a.code <> b.code
      WHERE a.span @> b.span
        AND NOT EXISTS (SELECT 1 FROM em_anc WHERE node = b.code AND anc = a.code)
  LOOP
    RAISE EXCEPTION 'nested-set 좌표 오류: %가 좌표상 포함관계인데 계통상 조상-자손이 아니다', v_bad;
  END LOOP;
END;
$verify$;

-- ─────────────────────────────────────────────────────────────
-- 판정 사유 어휘 마스터 (D-27, D-30에서 축소)
-- ─────────────────────────────────────────────────────────────
--
-- D-30 — is_blocking/is_review_trigger 컬럼이 삭제됐으므로 그 값도 없다.
-- 이 테이블은 이제 워크플로우를 구동하지 않는 순수 어휘다 — conflict_report,
-- constraint_reason_map 번역, 그리고 앱 레이어가 참고할 공용 사유 코드다.
--
-- right_mapping 삭제로 그 표에서 파생되던 AMBIGUOUS_CLAUSE(조합 통상성
-- 검증)와 CROSS_BORDER_MUSIC_CLEARANCE(자문 경고)를 산출하는 엔진이 이제
-- 없다 — 둘 다 implemented=false로 되돌린다. EXCLUSIVE_RIGHT_OVERLAP은
-- constraint_reason_map이 실제로 참조하므로 implemented=true를 유지한다.
-- *_MISSING/*_UNRESOLVED 계열은 DB가 더 이상 산출하지 않지만(그 값을 찍던
-- classify_candidate()/evaluate_candidate()가 사라졌다), 같은 어휘를 앱
-- 레이어가 계속 쓸 수 있도록 코드 자체는 유지한다.
INSERT INTO reason_code (
    code, category, result_type, rule_code, severity,
    is_decision_reason,
    name_ko, template_ko, template_en, implemented
) VALUES
-- ── CONFLICT ────────────────────────────────────────────────
('EXCLUSIVE_RIGHT_OVERLAP', 'SCOPE', 'CONFLICT', 'R7', 95, true,
 '기존 독점권과 중첩',
 '동일한 작품·지역·기간에 대해 이미 부여된 독점 권리와 범위가 겹칩니다.',
 'Overlaps an exclusive right already granted for the same work, territory, and period.', true),

('CONTENT_SCOPE_OVERLAP', 'SCOPE', 'CONFLICT', 'R2', 90, true,
 '계약 대상 범위 중첩',
 '상위 범위(시리즈·시즌) 계약이 이 계약의 대상 범위를 이미 포함하고 있습니다.',
 'A broader content scope (series or season) already covers this grant.', false),

('AUTHORITY_SCOPE_EXCEEDED', 'AUTHORITY', 'CONFLICT', 'R8', 92, true,
 '재허락 권한 범위 초과',
 '허락자가 상위 계약에서 받은 권리 범위를 넘어서 권리를 부여하고 있습니다.',
 'The grantor is conveying rights broader than what it holds upstream.', false),

('AUTHORITY_PERIOD_EXCEEDED', 'AUTHORITY', 'CONFLICT', 'R8', 91, true,
 '재허락 권한 기간 초과',
 '허락자가 상위 계약에서 받은 권리 기간을 넘어서 권리를 부여하고 있습니다.',
 'The grant period extends beyond the upstream license term held by the grantor.', false),

('UNAUTHORIZED_SUBLICENSE', 'AUTHORITY', 'CONFLICT', 'R8', 93, true,
 '재허락 금지 위반',
 '상위 계약이 재허락을 금지하고 있는데 재허락이 이뤄졌습니다.',
 'Sublicensing occurred although the upstream agreement prohibits it.', false),

('DERIVATIVE_RIGHT_OVERLAP', 'SCOPE', 'CONFLICT', 'R9', 85, true,
 '2차적 권리 중첩',
 '리메이크·포맷·OST 등 파생 권리가 기존 부여와 겹칩니다.',
 'Derivative rights (remake, format, OST) overlap an existing grant.', false),

('HOLDBACK_VIOLATION', 'SCOPE', 'CONFLICT', 'R7', 88, true,
 'Holdback 위반',
 '기존 계약이 설정한 holdback 기간 안에 이용이 시작됩니다.',
 'Exploitation begins inside a holdback window set by an existing agreement.', false),

-- ── REVIEW_REQUIRED — 값이 아예 없음. DB가 더 이상 산출하지 않는다
-- (rights_grant의 NOT NULL·evidence CHECK가 그 역할을 이제 직접 한다).
-- 앱 레이어가 등록 이전 자체 검증에 같은 어휘를 쓸 수 있도록 코드는 유지.
('RIGHT_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R3', 78, true,
 '법적 권리 미추출',
 '어떤 법적 권리를 부여하는 계약인지 추출되지 않았습니다.',
 'No legal right was extracted from the document.', false),

('EXPLOITATION_MODE_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R4', 77, true,
 '이용형태 미추출',
 '어떤 이용형태(SVOD·방송 등)인지 추출되지 않았습니다.',
 'No exploitation mode was extracted from the document.', false),

('TERRITORY_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R5', 76, true,
 '지역 미추출',
 '권리가 미치는 지역이 추출되지 않았습니다.',
 'No territory was extracted from the document.', false),

('PERIOD_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R6', 75, true,
 '기간 미추출',
 '권리 존속 기간이 추출되지 않았습니다.',
 'No license period was extracted from the document.', false),

('EXCLUSIVITY_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R7', 74, true,
 '독점 여부 미추출',
 '독점·비독점 여부가 추출되지 않았습니다.',
 'Exclusivity was not extracted from the document.', false),

-- ── REVIEW_REQUIRED — 표현은 있으나 정규화 실패 ────────────────
('RIGHT_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R3', 68, true,
 '법적 권리 확정 불가',
 '권리 문구는 있으나 표준 법적 권리로 정규화하지 못했습니다.',
 'A rights clause exists but could not be normalized to a standard legal right.', false),

('EXPLOITATION_MODE_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R4', 67, true,
 '이용형태 확정 불가',
 '이용형태 문구는 있으나 표준값으로 정규화하지 못했습니다.',
 'An exploitation clause exists but could not be normalized to a standard mode.', false),

('TERRITORY_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R5', 66, true,
 '지역 확정 불가',
 '지역 표현은 있으나 국가 목록으로 확정하지 못했습니다(별지 누락, except 조건 등).',
 'A territory clause exists but could not be resolved to a country list.', false),

('PERIOD_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R6', 65, true,
 '기간 확정 불가',
 '기간 표현은 있으나 확정 날짜로 계산하지 못했습니다(상대기간·자동갱신 등).',
 'A term clause exists but could not be resolved to concrete dates.', false),

('EXCLUSIVITY_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R7', 64, true,
 '독점 여부 확정 불가',
 '독점 관련 문구는 있으나 독점·비독점 중 어느 쪽인지 단정할 수 없습니다.',
 'An exclusivity clause exists but is not decisive.', false),

('CONTENT_IDENTITY_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R1', 72, true,
 '작품 동일성 확정 불가',
 '계약서의 작품명이 기존 등록 작품과 동일한지 확정할 수 없습니다.',
 'Cannot determine whether the titled work matches an existing registered work.', false),

('SUBLICENSE_CONSENT_UNVERIFIED', 'AUTHORITY', 'REVIEW_REQUIRED', 'R8', 71, true,
 '재허락 동의 미확인',
 '재허락에 상위 권리자의 동의가 필요한데 동의 여부를 확인할 수 없습니다.',
 'Sublicensing requires upstream consent that could not be verified.', false),

('DERIVATIVE_SCOPE_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R9', 63, true,
 '2차적 권리 범위 확정 불가',
 '파생 권리(리메이크·포맷·OST)의 범위가 계약서에서 명확하지 않습니다.',
 'The scope of derivative rights is not clearly defined in the agreement.', false),

-- ── REVIEW_REQUIRED — 추출 품질. right_mapping 삭제로 산출 엔진이 없어졌다 ──
('AMBIGUOUS_CLAUSE', 'AI_QUALITY', 'REVIEW_REQUIRED', NULL, 62, true,
 '조항 해석 모호',
 '조항 해석이 모호해 값을 단정할 수 없습니다.',
 'The clause is ambiguous and cannot be interpreted decisively.', false),

-- D-28에서 is_blocking=false로 내렸던 배경(사람 확인이 필수 단계라 등록을
-- 막을 이유가 없다)은 D-30에서 구조적으로 확정됐다 — confidence 자체가
-- 이제 DB로 넘어오지 않는다(앱 레이어에서 필터링). 어휘로만 유지한다.
('LOW_CONFIDENCE', 'AI_QUALITY', 'REVIEW_REQUIRED', NULL, 60, true,
 '추출 신뢰도 미달',
 '값은 채워졌으나 추출 신뢰도가 임계치(0.85) 미만입니다.',
 'All fields were extracted but confidence is below the 0.85 threshold.', false),

('MANUAL_REVIEW', 'AI_QUALITY', 'REVIEW_REQUIRED', NULL, 55, false,
 '수동 검토 지정',
 '담당자가 수동으로 재검토를 지정했습니다.',
 'Flagged for manual review by an operator.', true),

-- ── WARNING — right_mapping 삭제로 산출 엔진이 없어졌다 (AMBIGUOUS_CLAUSE와 동일 사유) ──
('CROSS_BORDER_MUSIC_CLEARANCE', 'EXTERNAL', 'WARNING', 'R9', 30, true,
 '국경 간 음악 clearance 확인',
 '해당 관할에서 삽입 음악의 저작권 처리 방식이 달라 별도 확인이 필요합니다.',
 'Music clearance practice differs in this jurisdiction; verify separately.', false),

('PRIOR_NEGOTIATION_OBLIGATION', 'EXTERNAL', 'WARNING', 'R9', 25, false,
 '우선협상 의무 존재',
 '기존 계약에 우선협상권이 있어 제3자와 계약하기 전에 절차를 밟아야 합니다.',
 'An existing agreement carries a first-negotiation right that must be honored first.', false);

-- D-08 보존 — DB 제약명을 사용자에게 보여줄 코드로 번역한다.
-- 두 제약명이 같은 코드로 귀결되는 것은 의도된 것이다: 사용자 입장에서 둘 다
-- "기존 독점권과 겹친다"는 같은 사건이고, 어느 층(EXCLUDE / 트리거)이 잡았는지는
-- 내부 구현 세부라 화면에 노출할 이유가 없다.
INSERT INTO constraint_reason_map (constraint_name, reason_code) VALUES
    ('no_exclusive_overlap',    'EXCLUSIVE_RIGHT_OVERLAP'),
    ('no_exclusivity_conflict', 'EXCLUSIVE_RIGHT_OVERLAP');

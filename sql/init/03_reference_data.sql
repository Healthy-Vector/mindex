-- 03_reference_data.sql — 참조 데이터 시드 (D-15 · D-27)
--
-- 테이블 정의는 01_schema.sql에 있다. 여기는 값만 넣는다.
--
-- D-27로 바뀐 것: 판정축 taxonomy 2종(legal_right · exploitation_mode)의
-- nested-set 좌표 시드가 추가됐고, statutory_right·right_mapping이 그 위에
-- 다시 얹혔으며, conflict_code 2행이 reason_code 25행으로 대체됐다.

-- ─────────────────────────────────────────────────────────────
-- 국가
-- ─────────────────────────────────────────────────────────────
--
-- in_scope 8개국이 WORLDWIDE 전개 대상이다 (SRS DAR-001).
-- 시나리오 EN-C03(Worldwide 극장권)이 이 8개 기준으로 US·JP·TW 3중 충돌을 기대한다.
-- 8개를 늘리거나 줄이면 그 시나리오의 기대 결과가 바뀐다.
INSERT INTO country (code, name_ko, name_en, in_scope) VALUES
    ('KR', '대한민국',   'South Korea',  true),
    ('JP', '일본',       'Japan',        true),
    ('US', '미국',       'United States',true),
    ('CN', '중국',       'China',        true),
    ('TW', '대만',       'Taiwan',       true),
    ('TH', '태국',       'Thailand',     true),
    ('VN', '베트남',     'Vietnam',      true),
    ('SG', '싱가포르',   'Singapore',    true),
    -- 전개 대상 밖. 계약서에 등장할 수 있으므로 어휘로는 유지한다.
    ('GB', '영국',       'United Kingdom', false),
    ('FR', '프랑스',     'France',       false),
    ('DE', '독일',       'Germany',      false),
    ('ID', '인도네시아', 'Indonesia',    false),
    ('MY', '말레이시아', 'Malaysia',     false),
    ('PH', '필리핀',     'Philippines',  false),
    ('HK', '홍콩',       'Hong Kong',    false),
    ('AU', '호주',       'Australia',    false);

-- ─────────────────────────────────────────────────────────────
-- 지역 그룹 — 전개용 참조. 저장 단위가 아니다 (D-15)
-- ─────────────────────────────────────────────────────────────
--
-- 계약서의 '아시아 전역', 'Worldwide', '동남아' 같은 표현을 앱이 여기서 국가로
-- 펼쳐 rights_grant에 국가 수만큼 행을 넣는다.
--
-- 데모 시나리오 2가 이것으로 성립한다 — 웨이브(KR 독점)와 Viu(아시아 전역 독점)가
-- 텍스트만 보면 겹치는지 알 수 없지만, APAC을 펼치면 KR이 나와 충돌이 드러난다.
INSERT INTO territory_group (code, name_ko, note) VALUES
    ('WORLDWIDE', '전 세계',   'in_scope 국가 8개로 전개한다'),
    ('APAC',      '아시아·태평양', '"아시아 전역" 표현이 여기로 매핑된다'),
    ('SEA',       '동남아시아', NULL),
    ('NA',        '북미',       NULL),
    ('EU',        '유럽',       '전개 대상 밖 국가를 포함한다');

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
-- 판정축 1 — 법적 권리 (R3). nested-set preorder 좌표
-- ─────────────────────────────────────────────────────────────
--
-- 관할 중립 어휘다. 관할별 실제 조문은 아래 statutory_right가 담는다.
--
-- 좌표는 손으로 박는다 — 7행짜리 정적 taxonomy라 자동 계산 함수보다 명시
-- 좌표가 검증하기 쉽고, 아래 자가검증 블록이 오타를 즉시 잡는다.
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
-- 판정축 2 — 사업적 이용형태 (R4). nested-set preorder 좌표
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
--
-- VOD 노드가 있어야 "all on-demand audiovisual streaming rights" 같은 넓은
-- 부여를 그대로 저장하면서도 개별 창구(AVOD/TVOD)와의 겹침을 EXCLUDE가 잡는다.
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
-- 좌표 자가검증 — 여기서 실패하면 EXCLUDE 판정 전체가 조용히 틀린다
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
-- 관할별 법정 지분권 — 자문축. 판정에 직접 쓰지 않는다
-- ─────────────────────────────────────────────────────────────
--
-- 한국은 방송권과 전송권을 구분하고, 일본은 둘을 공중송신권(公衆送信権) 하나로
-- 통합해 다룬다. parent_code가 관할 내부의 그 포함관계다.
--
-- D-27 — legal_right_code가 관할 중립 판정축으로의 연결이다. JP_TRANSMISSION
-- (送信可能化権)과 KR_TRANSMISSION(전송권)이 둘 다 TRANSMISSION으로 정규화되기
-- 때문에 JA-C05의 한일 교차 충돌이 성립한다. 이 컬럼이 없으면 두 코드가 서로
-- 다른 문자열이라 영영 안 겹친다.
INSERT INTO statutory_right (code, jurisdiction, legal_right_code, name_local, name_ko, parent_code, note) VALUES
    ('KR_PUBLIC_TRANSMISSION', 'KR', 'PUBLIC_TRANSMISSION', '공중송신권', '공중송신권', NULL,
     '한국 저작권법상 방송권·전송권·디지털음성송신권의 상위 개념'),
    ('KR_BROADCAST',    'KR', 'BROADCAST',    '방송권', '방송권', 'KR_PUBLIC_TRANSMISSION', NULL),
    ('KR_TRANSMISSION', 'KR', 'TRANSMISSION', '전송권', '전송권', 'KR_PUBLIC_TRANSMISSION',
     '주문형 스트리밍이 여기 해당한다'),
    ('KR_PERFORMANCE',  'KR', 'PUBLIC_PERFORMANCE', '공연권', '공연권', NULL, '극장 상영이 여기 해당한다'),
    ('KR_DERIVATIVE',   'KR', 'DERIVATIVE_WORK_CREATION', '2차적저작물작성권', '2차적저작물작성권', NULL,
     '리메이크·포맷·시퀄·상품화가 이 아래에 있으나 표준계약서가 세분하지 않는 경우가 많다'),

    ('JP_PUBLIC_TRANSMISSION', 'JP', 'PUBLIC_TRANSMISSION', '公衆送信権', '공중송신권', NULL,
     '한국과 달리 방송·전송을 하나로 묶는다. 곡별 개별 정산이 필요한 경우가 있다'),
    ('JP_BROADCAST',    'JP', 'BROADCAST',    '放送権',       '방송권',       'JP_PUBLIC_TRANSMISSION', NULL),
    ('JP_TRANSMISSION', 'JP', 'TRANSMISSION', '送信可能化権', '송신가능화권', 'JP_PUBLIC_TRANSMISSION',
     '自動公衆送信(주문형 송신)이 이 권리로 다뤄진다 — JA-C05의 정규화 대상'),
    ('JP_PERFORMANCE',  'JP', 'PUBLIC_PERFORMANCE', '上映権', '상영권', NULL, NULL),

    ('US_PUBLIC_PERFORMANCE', 'US', 'PUBLIC_PERFORMANCE', 'Public Performance Right', '공연권', NULL, NULL),
    ('US_DISTRIBUTION',       'US', 'DISTRIBUTION',       'Distribution Right',       '배포권', NULL, NULL);

-- ─────────────────────────────────────────────────────────────
-- 두 판정축 조합의 자문/검증표 (D-27로 역할 재정의)
-- ─────────────────────────────────────────────────────────────
--
-- **자동 변환표가 아니다.** "SVOD니까 legal_right는 TRANSMISSION"으로 채우는
-- 코드를 만들지 않는다 — 계약서에 안 쓰인 법적 권리를 시스템이 창작하는 것이라
-- P-1이 금지한다. 여기 없는 조합은 "틀렸다"가 아니라 "사람이 봐야 한다"이며,
-- evaluate_candidate()가 AMBIGUOUS_CLAUSE 사유로 review 큐에 올린다.
--
-- advisory가 있는 행만 rights_advisory()가 경고로 띄운다.
-- 데모 시나리오 1(겨울연가·NHK 유형)의 근거가 JP 행들이다.
INSERT INTO right_mapping (legal_right, exploitation_mode, jurisdiction, is_typical, advisory) VALUES
    ('TRANSMISSION',        'SVOD',       'KR', true, NULL),
    ('TRANSMISSION',        'AVOD',       'KR', true, NULL),
    ('TRANSMISSION',        'TVOD',       'KR', true, NULL),
    ('TRANSMISSION',        'VOD',        'KR', true, NULL),
    ('PUBLIC_TRANSMISSION', 'VOD',        'KR', true,
     '공중송신권으로 포괄 부여된 경우다. 방송권까지 포함하는지 계약서에서 확인할 것.'),
    ('PUBLIC_TRANSMISSION', 'TV_LINEAR',  'KR', true, NULL),
    ('BROADCAST',           'TV_LINEAR',  'KR', true, NULL),
    ('PUBLIC_PERFORMANCE',  'THEATRICAL', 'KR', true, NULL),

    ('TRANSMISSION',        'SVOD',       'JP', true,
     '"음악저작권 별도 처리" 조항이 한국과 일본에서 요구하는 정산 방식·비용 규모가 다르다. 예산 반영 전 확인 필요.'),
    ('TRANSMISSION',        'AVOD',       'JP', true,
     '"음악저작권 별도 처리" 조항이 한국과 일본에서 요구하는 정산 방식·비용 규모가 다르다. 예산 반영 전 확인 필요.'),
    ('TRANSMISSION',        'TVOD',       'JP', true, NULL),
    ('TRANSMISSION',        'VOD',        'JP', true, NULL),
    ('PUBLIC_TRANSMISSION', 'TV_LINEAR',  'JP', true,
     '일본은 방송권·전송권을 공중송신권 하나로 통합해 다룬다. 음악저작권이 신탁관리단체 일괄 정산이 아니라 곡별 개별 정산으로 요구될 수 있으므로, 방영 일정 확정 전에 상대측 정산 방식과 규모를 확인할 것.'),
    ('BROADCAST',           'TV_LINEAR',  'JP', true, NULL),
    ('PUBLIC_PERFORMANCE',  'THEATRICAL', 'JP', true, NULL),

    ('PUBLIC_PERFORMANCE',  'THEATRICAL', 'US', true, NULL),
    ('DISTRIBUTION',        'SVOD',       'US', true,
     '미국은 온라인 유통을 배포권 계열로 구성하는 계약이 많다. 전송권 개념과 1:1로 대응하지 않으므로 원문 문구를 확인할 것.'),
    ('DISTRIBUTION',        'VOD',        'US', true, NULL);

-- ─────────────────────────────────────────────────────────────
-- 판정 사유 마스터 (D-27)
-- ─────────────────────────────────────────────────────────────
--
-- 출처: 합성데이터 시나리오 문서의 Reason Code 15종. 거기에 없던 필드별
-- *_MISSING 5종을 추가했다 — 문서의 *_UNRESOLVED는 "표현은 있는데 정규화
-- 실패"이고, "컬럼이 아예 NULL"은 DB가 결정론적으로 판단할 수 있는 다른
-- 사건이라 코드를 나눠야 한다(D-25의 MISSING_FIELD 하나로 뭉치면 KO-R01의
-- 정답 코드 TERRITORY_UNRESOLVED를 표현할 수 없다).
--
-- implemented=false는 "코드는 정의됐지만 판정 엔진이 아직 방출하지 않는다"는
-- 뜻이다. R1(작품 동일성)·R2(EIDR 계층)·R8(권리사슬)·R9(파생 IP)은 그 판정에
-- 필요한 스키마(시즌/에피소드 계층, grantor/grantee 체인)가 아직 없다(O-07).
INSERT INTO reason_code (
    code, category, result_type, rule_code, severity,
    is_blocking, is_review_trigger, is_decision_reason,
    name_ko, template_ko, template_en, implemented
) VALUES
-- ── CONFLICT ────────────────────────────────────────────────
-- CONFLICT 코드도 is_review_trigger=true다. 충돌이 잡힌 후보는 사람이 판단해야
-- 하고, candidate.review_reason_code에 그 코드가 그대로 들어가는 게 가장 정확한
-- 표시이기 때문이다(review_requires_reason CHECK도 사유를 요구한다).
('EXCLUSIVE_RIGHT_OVERLAP', 'SCOPE', 'CONFLICT', 'R7', 95, true, true, true,
 '기존 독점권과 중첩',
 '동일한 작품·지역·기간에 대해 이미 부여된 독점 권리와 범위가 겹칩니다.',
 'Overlaps an exclusive right already granted for the same work, territory, and period.', true),

('CONTENT_SCOPE_OVERLAP', 'SCOPE', 'CONFLICT', 'R2', 90, true, true, true,
 '계약 대상 범위 중첩',
 '상위 범위(시리즈·시즌) 계약이 이 계약의 대상 범위를 이미 포함하고 있습니다.',
 'A broader content scope (series or season) already covers this grant.', false),

('AUTHORITY_SCOPE_EXCEEDED', 'AUTHORITY', 'CONFLICT', 'R8', 92, true, true, true,
 '재허락 권한 범위 초과',
 '허락자가 상위 계약에서 받은 권리 범위를 넘어서 권리를 부여하고 있습니다.',
 'The grantor is conveying rights broader than what it holds upstream.', false),

('AUTHORITY_PERIOD_EXCEEDED', 'AUTHORITY', 'CONFLICT', 'R8', 91, true, true, true,
 '재허락 권한 기간 초과',
 '허락자가 상위 계약에서 받은 권리 기간을 넘어서 권리를 부여하고 있습니다.',
 'The grant period extends beyond the upstream license term held by the grantor.', false),

('UNAUTHORIZED_SUBLICENSE', 'AUTHORITY', 'CONFLICT', 'R8', 93, true, true, true,
 '재허락 금지 위반',
 '상위 계약이 재허락을 금지하고 있는데 재허락이 이뤄졌습니다.',
 'Sublicensing occurred although the upstream agreement prohibits it.', false),

('DERIVATIVE_RIGHT_OVERLAP', 'SCOPE', 'CONFLICT', 'R9', 85, true, true, true,
 '2차적 권리 중첩',
 '리메이크·포맷·OST 등 파생 권리가 기존 부여와 겹칩니다.',
 'Derivative rights (remake, format, OST) overlap an existing grant.', false),

('HOLDBACK_VIOLATION', 'SCOPE', 'CONFLICT', 'R7', 88, true, true, true,
 'Holdback 위반',
 '기존 계약이 설정한 holdback 기간 안에 이용이 시작됩니다.',
 'Exploitation begins inside a holdback window set by an existing agreement.', false),

-- ── REVIEW_REQUIRED — 값이 아예 없음 (DB가 결정론적으로 판단) ──
('RIGHT_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R3', 78, true, true, true,
 '법적 권리 미추출',
 '어떤 법적 권리를 부여하는 계약인지 추출되지 않았습니다.',
 'No legal right was extracted from the document.', true),

('EXPLOITATION_MODE_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R4', 77, true, true, true,
 '이용형태 미추출',
 '어떤 이용형태(SVOD·방송 등)인지 추출되지 않았습니다.',
 'No exploitation mode was extracted from the document.', true),

('TERRITORY_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R5', 76, true, true, true,
 '지역 미추출',
 '권리가 미치는 지역이 추출되지 않았습니다.',
 'No territory was extracted from the document.', true),

('PERIOD_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R6', 75, true, true, true,
 '기간 미추출',
 '권리 존속 기간이 추출되지 않았습니다.',
 'No license period was extracted from the document.', true),

('EXCLUSIVITY_MISSING', 'DATA_QUALITY', 'REVIEW_REQUIRED', 'R7', 74, true, true, true,
 '독점 여부 미추출',
 '독점·비독점 여부가 추출되지 않았습니다.',
 'Exclusivity was not extracted from the document.', true),

-- ── REVIEW_REQUIRED — 표현은 있으나 정규화 실패 (추출기가 지정) ──
('RIGHT_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R3', 68, true, true, true,
 '법적 권리 확정 불가',
 '권리 문구는 있으나 표준 법적 권리로 정규화하지 못했습니다.',
 'A rights clause exists but could not be normalized to a standard legal right.', true),

('EXPLOITATION_MODE_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R4', 67, true, true, true,
 '이용형태 확정 불가',
 '이용형태 문구는 있으나 표준값으로 정규화하지 못했습니다.',
 'An exploitation clause exists but could not be normalized to a standard mode.', true),

('TERRITORY_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R5', 66, true, true, true,
 '지역 확정 불가',
 '지역 표현은 있으나 국가 목록으로 확정하지 못했습니다(별지 누락, except 조건 등).',
 'A territory clause exists but could not be resolved to a country list.', true),

('PERIOD_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R6', 65, true, true, true,
 '기간 확정 불가',
 '기간 표현은 있으나 확정 날짜로 계산하지 못했습니다(상대기간·자동갱신 등).',
 'A term clause exists but could not be resolved to concrete dates.', true),

('EXCLUSIVITY_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R7', 64, true, true, true,
 '독점 여부 확정 불가',
 '독점 관련 문구는 있으나 독점·비독점 중 어느 쪽인지 단정할 수 없습니다.',
 'An exclusivity clause exists but is not decisive.', true),

('CONTENT_IDENTITY_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R1', 72, true, true, true,
 '작품 동일성 확정 불가',
 '계약서의 작품명이 기존 등록 작품과 동일한지 확정할 수 없습니다.',
 'Cannot determine whether the titled work matches an existing registered work.', false),

('SUBLICENSE_CONSENT_UNVERIFIED', 'AUTHORITY', 'REVIEW_REQUIRED', 'R8', 71, true, true, true,
 '재허락 동의 미확인',
 '재허락에 상위 권리자의 동의가 필요한데 동의 여부를 확인할 수 없습니다.',
 'Sublicensing requires upstream consent that could not be verified.', false),

('DERIVATIVE_SCOPE_UNRESOLVED', 'SCOPE', 'REVIEW_REQUIRED', 'R9', 63, true, true, true,
 '2차적 권리 범위 확정 불가',
 '파생 권리(리메이크·포맷·OST)의 범위가 계약서에서 명확하지 않습니다.',
 'The scope of derivative rights is not clearly defined in the agreement.', false),

-- ── REVIEW_REQUIRED — 추출 품질 ──────────────────────────────
('AMBIGUOUS_CLAUSE', 'AI_QUALITY', 'REVIEW_REQUIRED', NULL, 62, true, true, true,
 '조항 해석 모호',
 '조항 해석이 모호해 값을 단정할 수 없습니다.',
 'The clause is ambiguous and cannot be interpreted decisively.', true),

-- D-28 — is_blocking=false. 화면 프로세스에서 사람 확인은 선택이 아니라 필수
-- 단계라("사람이 눈으로 확인 및 오타 수정" → `검증`), "신뢰도가 낮으니 사람을
-- 부르자"는 취지가 등록 시점에 이미 충족돼 있다. true로 두면 사람이 이미 검수한
-- 후보가 영영 등록되지 않는다 — register_candidate()는 review 상태를 거부하고,
-- evaluate_candidate()는 이 사유를 매번 다시 옮겨 review로 되돌리며, 해제 수단인
-- rights_evaluation_reason.status='resolved'는 세팅하는 코드가 없다(O-09).
('LOW_CONFIDENCE', 'AI_QUALITY', 'REVIEW_REQUIRED', NULL, 60, false, true, true,
 '추출 신뢰도 미달',
 '값은 채워졌으나 추출 신뢰도가 임계치(0.85) 미만입니다.',
 'All fields were extracted but confidence is below the 0.85 threshold.', true),

('MANUAL_REVIEW', 'AI_QUALITY', 'REVIEW_REQUIRED', NULL, 55, true, true, false,
 '수동 검토 지정',
 '담당자가 수동으로 재검토를 지정했습니다.',
 'Flagged for manual review by an operator.', true),

-- ── WARNING — 등록을 막지 않는다 (is_blocking = false) ────────
('CROSS_BORDER_MUSIC_CLEARANCE', 'EXTERNAL', 'WARNING', 'R9', 30, false, false, true,
 '국경 간 음악 clearance 확인',
 '해당 관할에서 삽입 음악의 저작권 처리 방식이 달라 별도 확인이 필요합니다.',
 'Music clearance practice differs in this jurisdiction; verify separately.', true),

('PRIOR_NEGOTIATION_OBLIGATION', 'EXTERNAL', 'WARNING', 'R9', 25, false, false, true,
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

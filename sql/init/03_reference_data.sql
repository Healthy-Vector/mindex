-- 03_reference_data.sql — 참조 데이터 시드 (D-13 · D-15 · D-18)
--
-- 테이블 정의는 01_schema.sql에 있다. 여기는 값만 넣는다.

-- ─────────────────────────────────────────────────────────────
-- 충돌 코드 — probe_rights_conflict()가 반환하는 constraint_name과 1:1 대응 (D-18)
-- ─────────────────────────────────────────────────────────────
INSERT INTO conflict_code (code, template_ko, template_en) VALUES
    ('no_exclusive_overlap',
     '동일한 지역·기간·권리유형에 대해 이미 독점권이 부여되어 있습니다.',
     'An exclusive right already exists for the same territory, period, and rights type.'),
    ('no_exclusivity_conflict',
     '동일한 지역·기간·권리유형에 독점권과 비독점권이 함께 존재할 수 없습니다.',
     'An exclusive and a non-exclusive right cannot coexist for the same territory, period, and rights type.');

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
-- 법정 지분권 — 자문축. 판정에 쓰지 않는다
-- ─────────────────────────────────────────────────────────────
--
-- 한국은 방송권과 전송권을 구분하고, 일본은 둘을 공중송신권(公衆送信権) 하나로
-- 통합해 다룬다. parent_code가 그 포함관계다.
--
-- 이 계층 구조는 statutory_right 축에만 존재한다. 판정축인 rights_type 5종은
-- 평면이며 상위-하위가 없다 — 두 축을 섞으면 판정이 결정론을 잃는다.
INSERT INTO statutory_right (code, jurisdiction, name_local, name_ko, parent_code, note) VALUES
    ('KR_PUBLIC_TRANSMISSION', 'KR', '공중송신권', '공중송신권', NULL,
     '한국 저작권법상 방송권·전송권·디지털음성송신권의 상위 개념'),
    ('KR_BROADCAST',    'KR', '방송권',   '방송권',   'KR_PUBLIC_TRANSMISSION', NULL),
    ('KR_TRANSMISSION', 'KR', '전송권',   '전송권',   'KR_PUBLIC_TRANSMISSION',
     '주문형 스트리밍이 여기 해당한다'),
    ('KR_PERFORMANCE',  'KR', '공연권',   '공연권',   NULL, '극장 상영이 여기 해당한다'),
    ('KR_DERIVATIVE',   'KR', '2차적저작물작성권', '2차적저작물작성권', NULL,
     '리메이크·포맷·시퀄·상품화가 이 아래에 있으나 표준계약서가 세분하지 않는 경우가 많다'),

    ('JP_PUBLIC_TRANSMISSION', 'JP', '公衆送信権', '공중송신권', NULL,
     '한국과 달리 방송·전송을 하나로 묶는다. 곡별 개별 정산이 필요한 경우가 있다'),
    ('JP_BROADCAST',    'JP', '放送権',       '방송권',   'JP_PUBLIC_TRANSMISSION', NULL),
    ('JP_TRANSMISSION', 'JP', '送信可能化権', '송신가능화권', 'JP_PUBLIC_TRANSMISSION', NULL),
    ('JP_PERFORMANCE',  'JP', '上映権',       '상영권',   NULL, NULL),

    ('US_PUBLIC_PERFORMANCE', 'US', 'Public Performance Right', '공연권', NULL, NULL),
    ('US_DISTRIBUTION',       'US', 'Distribution Right',       '배포권', NULL, NULL);

-- ─────────────────────────────────────────────────────────────
-- 유통창구 ↔ 법정 지분권 매핑 + 자문 문구
-- ─────────────────────────────────────────────────────────────
--
-- advisory가 있는 행만 rights_advisory()가 경고로 띄운다.
-- 데모 시나리오 1(겨울연가·NHK 유형)의 근거가 JP_PUBLIC_TRANSMISSION 행들이다.
INSERT INTO right_mapping (rights_type, jurisdiction, statutory_code, advisory) VALUES
    ('TV_LINEAR',  'KR', 'KR_BROADCAST',    NULL),
    ('SVOD',       'KR', 'KR_TRANSMISSION', NULL),
    ('AVOD',       'KR', 'KR_TRANSMISSION', NULL),
    ('TVOD',       'KR', 'KR_TRANSMISSION', NULL),
    ('THEATRICAL', 'KR', 'KR_PERFORMANCE',  NULL),

    ('TV_LINEAR',  'JP', 'JP_PUBLIC_TRANSMISSION',
     '일본은 방송권·전송권을 공중송신권 하나로 통합해 다룬다. 음악저작권이 신탁관리단체 일괄 정산이 아니라 곡별 개별 정산으로 요구될 수 있으므로, 방영 일정 확정 전에 상대측 정산 방식과 규모를 확인할 것.'),
    ('SVOD',       'JP', 'JP_TRANSMISSION',
     '"음악저작권 별도 처리" 조항이 한국과 일본에서 요구하는 정산 방식·비용 규모가 다르다. 예산 반영 전 확인 필요.'),
    ('AVOD',       'JP', 'JP_TRANSMISSION',
     '"음악저작권 별도 처리" 조항이 한국과 일본에서 요구하는 정산 방식·비용 규모가 다르다. 예산 반영 전 확인 필요.'),
    ('TVOD',       'JP', 'JP_TRANSMISSION', NULL),
    ('THEATRICAL', 'JP', 'JP_PERFORMANCE',  NULL),

    ('THEATRICAL', 'US', 'US_PUBLIC_PERFORMANCE', NULL),
    ('SVOD',       'US', 'US_DISTRIBUTION',       NULL);

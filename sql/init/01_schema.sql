-- 01_schema.sql — 핵심 테이블 · EXCLUDE 제약 · 인덱스 (DAR-001, SFR-007)
--
-- 이 파일은 테이블 정의만 담는다. 참조 데이터 적재는 03_reference_data.sql,
-- 트리거·리포트 함수는 02_conflict_rules.sql이다.
--
-- 설계 근거는 docs/DECISIONS.md — D-03(지역 행 정규화) · D-04(3값 enum) ·
-- D-05(2단 판정) · D-09(복합 FK) · D-13(권리유형 5종) · D-15(국가코드만 저장) ·
-- D-16(검수 행 분리).

-- ─────────────────────────────────────────────────────────────
-- 타입
-- ─────────────────────────────────────────────────────────────

-- D-13 — 권리유형은 유통창구(distribution window) 5종.
-- 법정 지분권(공중송신권 등)이 아니다. 그쪽은 statutory_right 축에서 다루며
-- 판정이 아니라 자문·경고 용도다. 두 축을 섞지 않는다.
CREATE TYPE rights_type_kind AS ENUM (
    'SVOD',         -- 구독형 VOD
    'AVOD',         -- 광고형 VOD
    'TVOD',         -- 건별 과금 VOD
    'TV_LINEAR',    -- 선형 TV 방송
    'THEATRICAL'    -- 극장 상영·배급
);

-- D-04 — 독점은 boolean이 아니라 3값.
-- 'sole'은 제3자에게는 배타적이나 라이선서 본인은 계속 이용할 수 있는 형태다.
-- 판정에서는 'exclusive'와 동일하게 취급한다 (둘 다 제3자 배타).
--
-- 'unresolved'가 없는 것은 의도적이다 — D-16에 따라 독점 여부가 미확정인 행은
-- 애초에 이 테이블에 들어오지 않는다. 표현할 상태가 없다.
CREATE TYPE exclusivity_kind AS ENUM ('exclusive', 'sole', 'non_exclusive');

-- D-17 이전 D-16 — 검수로 보내는 사유. rights_grant.review_reason이 참조한다.
-- 앞의 셋은 EXCLUDE 키 컬럼이 비어 판정 자체가 불가능한 경우다.
CREATE TYPE review_reason_kind AS ENUM (
    'TERRITORY_UNRESOLVED',      -- 별지 국가목록 누락 등 (시나리오 KO-R01)
    'PERIOD_UNRESOLVED',         -- 기준 사건 부재 "release + 3Y" (EN-R01)
    'EXCLUSIVITY_UNRESOLVED',    -- 독점 여부 문구 없음 (JA-R01)
    'RIGHTS_SCOPE_UNSPECIFIED',  -- 2차적저작물권 세부유형 미명시 (데모 시나리오 3)
    'LOW_CONFIDENCE'             -- SFR-004 신뢰도 0.85 미만
);

-- D-17 — 업로드→파싱→probe→history저장→등록 워크플로우의 권리 행 상태.
-- 판정(EXCLUDE/트리거) 대상은 provisional·complete 뿐이다. draft·review·terminated는
-- "아직 살아있는 권리가 아니다"이므로 같은 구간에 다른 권리가 들어와도 막지 않는다.
CREATE TYPE rights_grant_status AS ENUM (
    'draft',        -- 파싱 직후, 아직 저장(history)도 안 한 상태
    'review',       -- 구 D-16 검수 스테이징 흡수. 필드가 비어 있을 수 있다
    'provisional',  -- 가확정 — 판정 대상
    'complete',     -- 완료 — 판정 대상
    'terminated'    -- 계약 종료. period 만료와 별개로 명시적으로 닫힌 상태
);

-- ─────────────────────────────────────────────────────────────
-- 참조 테이블 (시드는 03_reference_data.sql)
-- ─────────────────────────────────────────────────────────────

-- D-15 — 국가코드. rights_grant.territory가 참조하는 유일한 지역 어휘다.
CREATE TABLE country (
    code       char(2) PRIMARY KEY,
    name_ko    text NOT NULL,
    name_en    text NOT NULL,
    in_scope   boolean NOT NULL DEFAULT false   -- WORLDWIDE 전개 대상 8개국 여부
);

-- D-15 — 지역·대륙 그룹. "아시아", "동남아", "WORLDWIDE" 같은 표현이 여기 산다.
-- 저장 계층이 아니라 전개용 참조다. rights_grant는 이 테이블을 참조하지 않는다.
--
-- 왜 저장 단위로 쓰면 안 되는가: EXCLUDE는 territory를 동등 비교한다.
-- 태국 권리가 한쪽은 'TH', 다른 쪽은 'SEA'로 저장되면 두 값이 같지 않아
-- 겹치는데도 인덱스가 충돌을 보지 못한다. 그리고 에러도 나지 않는다.
CREATE TABLE territory_group (
    code       text PRIMARY KEY,        -- 'WORLDWIDE', 'APAC', 'SEA', 'NA'
    name_ko    text NOT NULL,
    note       text
);

CREATE TABLE territory_group_member (
    group_code   text    NOT NULL REFERENCES territory_group(code) ON DELETE CASCADE,
    country_code char(2) NOT NULL REFERENCES country(code),
    PRIMARY KEY (group_code, country_code)
);

-- 법정 지분권 어휘 (한국 저작권법 / 일본 著作権法).
-- 판정에 쓰지 않는다. 데모 시나리오 1(겨울연가·NHK 유형)의 경고 근거다.
CREATE TABLE statutory_right (
    code            text PRIMARY KEY,   -- 'KR_BROADCAST', 'JP_PUBLIC_TRANSMISSION'
    jurisdiction    char(2) NOT NULL REFERENCES country(code),
    name_local      text NOT NULL,
    name_ko         text NOT NULL,
    parent_code     text REFERENCES statutory_right(code),  -- 상위-하위 포함관계
    note            text
);

-- 유통창구(판정축) ↔ 법정 지분권(자문축) 매핑.
--
-- 이 테이블이 존재하는 이유: 같은 'TV_LINEAR' 권리라도 한국에서는 방송권,
-- 일본에서는 공중송신권 범주로 다뤄지고 정산 관행이 다르다. 계약서 텍스트가
-- 정상으로 보여도 국가 간 관행 차이는 드러나지 않는다.
--
-- advisory 컬럼이 사람에게 띄울 경고 문구다. 저장을 거부하지 않는다 —
-- 관행 차이는 결정론적 판정의 대상이 아니다 (원칙 P-2).
CREATE TABLE right_mapping (
    rights_type      rights_type_kind NOT NULL,
    jurisdiction     char(2)          NOT NULL REFERENCES country(code),
    statutory_code   text             NOT NULL REFERENCES statutory_right(code),
    advisory         text,
    PRIMARY KEY (rights_type, jurisdiction, statutory_code)
);

-- D-18 — 충돌 리포트 코드. 값은 EXCLUDE/트리거의 constraint_name과 동일하게 맞춘다.
-- 새 어휘를 만들지 않고 D-05가 이미 만든 결정론적 구분(no_exclusive_overlap ↔
-- no_exclusivity_conflict)을 그대로 재사용한다. AI는 template 문구에 첨언만 한다.
CREATE TABLE conflict_code (
    code         text PRIMARY KEY,
    template_ko  text NOT NULL,
    template_en  text NOT NULL
);

-- ─────────────────────────────────────────────────────────────
-- 테넌트(팀) — D-20
-- ─────────────────────────────────────────────────────────────
--
-- 지금까지 tenant_id는 각 테이블에 UUID로만 떠돌고 실체 테이블이 없었다.
-- 여기서 공식 테이블로 만든다. content·contract·rights_grant 등의 tenant_id는
-- 아래에서 이 테이블에 대한 단일 컬럼 FK를 추가로 받는다(기존 (id, tenant_id)
-- 복합 FK 구조(D-09)는 그대로 유지 — 이건 그 위에 얹는 참조 무결성이다).
--
-- access_key_hash — 팀 공유 API 인증 키. 평문을 저장하지 않는다. crypt()로
-- 해싱한 값만 들어오고, CHECK로 bcrypt 형식이 아니면 INSERT 자체를 거부한다 —
-- 앱이 해싱을 빠뜨려도 DB가 막는다(P-4와 같은 논리).
--
-- 삽입 예: INSERT INTO tenant (id, name, access_key_hash)
--          VALUES (gen_random_uuid(), 'A사', crypt('발급한-키', gen_salt('bf')));
-- 인증 예: SELECT id FROM tenant WHERE access_key_hash = crypt('입력값', access_key_hash);
CREATE TABLE tenant (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    access_key_hash text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT access_key_hash_is_bcrypt CHECK (access_key_hash ~ '^\$2[aby]?\$')
);

-- ─────────────────────────────────────────────────────────────
-- 도메인 테이블
-- ─────────────────────────────────────────────────────────────

-- 콘텐츠(IP). 언어가 달라도 같은 IP면 같은 행이다 —
-- '겨울의 신호' / 'Signal of Winter' / '冬のシグナル' → 모두 같은 content.
-- 다국어 충돌(시나리오 JA-C02)이 성립하는 근거가 이것이다.
CREATE TABLE content (
    id          bigserial PRIMARY KEY,
    tenant_id   uuid NOT NULL REFERENCES tenant(id),  -- D-20
    title_ko    text,
    title_en    text,
    title_ja    text,
    kind        text,                    -- '드라마' · '영화'
    created_at  timestamptz NOT NULL DEFAULT now(),

    -- D-09 — 복합 FK의 참조 대상. 이게 없으면 자식이 (id, tenant_id)를 못 건다.
    UNIQUE (id, tenant_id)
);

CREATE TABLE contract (
    id            bigserial PRIMARY KEY,
    tenant_id     uuid NOT NULL REFERENCES tenant(id),  -- D-20
    counterparty  text NOT NULL,
    signed_date   date,
    lang          char(2),               -- 'ko' · 'en' · 'ja'
    version       int  NOT NULL DEFAULT 1,
    created_at    timestamptz NOT NULL DEFAULT now(),

    -- SER-006 계층1 암호화 대상 (D-14). OpenCrypto는 OpenSQL 전용이라
    -- Docker 검증 환경에서는 평문으로 남는다. 실물 배포 시 ARIA/SEED 적용.
    raw_text      text,
    amount        numeric,

    UNIQUE (id, tenant_id)
);

-- SFR-006 — 메타데이터·버전 관리. 수정 시 이전 버전을 보존한다.
CREATE TABLE contract_version (
    id            bigserial PRIMARY KEY,
    tenant_id     uuid NOT NULL REFERENCES tenant(id),  -- D-20
    contract_id   bigint NOT NULL,
    version       int    NOT NULL,
    changed_by    text,
    changed_at    timestamptz NOT NULL DEFAULT now(),
    snapshot      jsonb  NOT NULL,       -- 변경 시점의 계약 필드 전체

    FOREIGN KEY (contract_id, tenant_id) REFERENCES contract (id, tenant_id) ON DELETE CASCADE,
    UNIQUE (contract_id, version)
);

-- ─────────────────────────────────────────────────────────────
-- 권리 레코드 — 플랫폼의 심장 (DAR-001)
-- ─────────────────────────────────────────────────────────────
--
-- D-03 · D-15 — 지역 1개당 1행. 여러 지역을 커버하는 권리는 지역 수만큼 행이 된다.
-- 'WORLDWIDE'는 앱이 등록 시점에 in_scope 국가 8개로 전개해 8행으로 넣는다.
--
-- 계약 1건이 여러 행이 되므로 PER-001 측정 단위는 "계약 1건 등록 트랜잭션"이어야
-- 한다. 현 SRS 문면("INSERT 트랜잭션 소요 시간")은 1행 INSERT로 읽힌다 → O-04 인접 항목.
CREATE TABLE rights_grant (
    id            bigserial PRIMARY KEY,
    tenant_id     uuid   NOT NULL REFERENCES tenant(id),  -- D-20
    contract_id   bigint NOT NULL,
    content_id    bigint NOT NULL,

    -- D-17 — 워크플로우 상태. provisional·complete만 판정(EXCLUDE·트리거) 대상이다.
    status        rights_grant_status NOT NULL DEFAULT 'draft',

    -- D-17 — nullable로 바뀌었다. status='review'(구 D-16 검수 스테이징) 행은
    -- 값이 없어도 이 테이블에 존재해야 한다. 대신 아래 resolved_fields_when_live가
    -- provisional·complete 상태에서는 반드시 채워져 있도록 강제한다.
    territory     char(2)          REFERENCES country(code),
    rights_type   rights_type_kind,
    period        daterange,
    exclusivity   exclusivity_kind,

    -- D-17 — review 상태로 보내는 사유. status<>'review'면 NULL이다.
    review_reason review_reason_kind,

    -- SFR-004 — 신뢰도. 여기 들어온 행은 이미 검수를 통과했거나 임계값 이상이다.
    confidence    numeric(3,2),
    verified_by   text,
    verified_at   timestamptz,

    -- P-3 Evidence Anchoring — 모든 추출값은 원문 인용을 동반한다 (SFR-002·003)
    source_page   int,
    source_clause text,
    source_quote  text,                  -- SER-006 계층1 암호화 대상 (D-14)

    created_at    timestamptz NOT NULL DEFAULT now(),

    -- D-09 — 복합 FK.
    -- 단일 컬럼 FK면 A테넌트 계약에 B테넌트 tenant_id를 단 행을 넣을 수 있고,
    -- 그러면 EXCLUDE 키가 겹치지 않아 충돌 판정이 통째로 우회된다.
    -- RLS는 테이블마다 자기 컬럼이 있어야 걸리고 EXCLUDE는 조인을 못 하므로
    -- tenant_id를 제거할 수 없다. 대신 복합 FK로 불일치를 DB가 거부하게 한다.
    FOREIGN KEY (contract_id, tenant_id) REFERENCES contract (id, tenant_id) ON DELETE CASCADE,
    FOREIGN KEY (content_id,  tenant_id) REFERENCES content  (id, tenant_id),

    -- 기간은 반열림 구간이어야 한다. 종료 12/31 다음 날 시작(2027-01-01)이
    -- 겹치지 않는다는 것이 시나리오 EN-B01의 판정 근거다. NULL은 허용(review 상태).
    CONSTRAINT period_not_empty CHECK (period IS NULL OR NOT isempty(period)),

    -- D-17 — "판정 가능한 완결 행"이라는 원래 전제를 provisional·complete로 좁혀 유지한다.
    -- 판정할 수 없는 행을 판정 대상 상태로 두지 않는다는 원칙(D-16의 논리)은 그대로다.
    CONSTRAINT resolved_fields_when_live CHECK (
        status NOT IN ('provisional', 'complete')
        OR (territory IS NOT NULL AND rights_type IS NOT NULL
            AND period IS NOT NULL AND exclusivity IS NOT NULL)
    )
);

-- ─────────────────────────────────────────────────────────────
-- 충돌 판정 1단 — EXCLUDE (D-05, SFR-007)
-- ─────────────────────────────────────────────────────────────
--
-- 담당: 독점/sole ↔ 독점/sole. 비독점이 낀 조합은 트리거가 맡는다(02_conflict_rules.sql).
-- 담당을 XOR로 배타 분할해 "어느 층이 잡았는지"가 결정론적으로 구분되게 한다.
--
-- 제약명을 바꾸지 않는다 (D-08) — RFP §6.3.2가 시연 구간 C에서 이 에러 문구를
-- 화면에 크게 노출하라고 규정하고 README도 이 이름을 문서화하고 있다.
-- D-17 — status 필터 추가. draft·review·terminated는 "살아있는" 권리가 아니므로
-- 같은 구간에 다른 권리가 들어와도 막지 않는다. 스파이크 8(spike-p2/14~15)에서
-- 5개 상태 조합 전부 실측 확인했다.
ALTER TABLE rights_grant
ADD CONSTRAINT no_exclusive_overlap
EXCLUDE USING gist (
    tenant_id   WITH =,
    content_id  WITH =,
    rights_type WITH =,
    territory   WITH =,
    period      WITH &&
)
WHERE (exclusivity <> 'non_exclusive' AND status IN ('provisional', 'complete'));

CREATE INDEX rights_grant_lookup
    ON rights_grant (tenant_id, content_id, rights_type, territory);

CREATE INDEX rights_grant_period
    ON rights_grant USING gist (period);

-- 만료 감시(SFR-012)용. 선택 항목이지만 인덱스는 지금 만들어 두는 편이 싸다.
CREATE INDEX rights_grant_expiry
    ON rights_grant (tenant_id, (upper(period)));

-- ─────────────────────────────────────────────────────────────
-- 검수 — D-16의 rights_grant_staging은 D-17로 대체됐다
-- ─────────────────────────────────────────────────────────────
--
-- 판정할 수 없는 행을 판정 테이블에 넣지 않는다는 원칙(D-16)은 유지되지만,
-- 별도 테이블 대신 rights_grant.status='review'로 흡수했다. territory·period·
-- exclusivity가 nullable이 됐고, resolved_fields_when_live CHECK가 provisional·
-- complete 상태에서만 완결값을 강제한다. 큐 조회는 부분 인덱스로 지원한다.
CREATE INDEX rights_grant_review_queue
    ON rights_grant (tenant_id, created_at)
    WHERE status = 'review';

-- ─────────────────────────────────────────────────────────────
-- history — append-only 원장 (D-17, D-18)
-- ─────────────────────────────────────────────────────────────
--
-- 두 가지 이벤트가 이 테이블에 쌓인다:
--   1. 'parsed'    — 파싱+probe 직후 "저장" 버튼. rights_grant_id는 아직 NULL이다.
--                    아직 마스터에 아무 행도 없을 수 있다.
--   2. 'registered'/'status_changed'/'terminated' — rights_grant 실제 변경 시
--      AFTER ROW 트리거(02_conflict_rules.sql)가 자동 기록한다.
--
-- rights_grant는 status로 UPDATE(현재 시점만 관리), history는 오직 INSERT다.
-- 기존 change_log(05)는 P1 재색인 워커용 기술 로그이고 이것과 목적이 다르다 —
-- 둘 다 유지한다.
CREATE TABLE rights_grant_history (
    id               bigserial PRIMARY KEY,
    tenant_id        uuid   NOT NULL REFERENCES tenant(id),  -- D-20
    contract_id      bigint NOT NULL,
    content_id       bigint NOT NULL,
    history_seq      int    NOT NULL,      -- 계약 내 순번

    rights_grant_id  bigint REFERENCES rights_grant(id),  -- 등록 전이면 NULL
    event_type       text   NOT NULL
                     CHECK (event_type IN ('parsed', 'registered', 'status_changed', 'terminated')),
    source_history_id bigint REFERENCES rights_grant_history(id),  -- registered가 가리키는 원본 parsed 행

    -- rights_grant와 동일한 타입의 스냅샷 컬럼 (probe 결과 그대로 반영)
    status_at_event  rights_grant_status NOT NULL,
    territory        char(2),
    rights_type      rights_type_kind,
    period           daterange,
    exclusivity      exclusivity_kind,
    confidence       numeric(3,2),
    source_page      int,
    source_clause    text,
    source_quote     text,

    -- D-18 — probe 결과. 충돌 없으면 NULL. conflict_code는 필터·집계용 요약값이고
    -- conflict_report가 화면에 뿌릴 전체 내용이다 — 상대 계약·겹침 기간·근거 조항·
    -- AI 첨언까지 하나의 JSON으로 묶는다(D-21). 화면 렌더링은 프런트가 이 JSON을 그대로 쓴다.
    conflict_code    text REFERENCES conflict_code(code),
    conflict_report  jsonb,

    recorded_at      timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (contract_id, tenant_id) REFERENCES contract (id, tenant_id) ON DELETE CASCADE,
    FOREIGN KEY (content_id,  tenant_id) REFERENCES content  (id, tenant_id),
    UNIQUE (contract_id, history_seq)
);

CREATE INDEX rights_grant_history_by_grant
    ON rights_grant_history (rights_grant_id)
    WHERE rights_grant_id IS NOT NULL;

CREATE INDEX rights_grant_history_pending
    ON rights_grant_history (tenant_id, contract_id, recorded_at)
    WHERE event_type = 'parsed' AND rights_grant_id IS NULL;

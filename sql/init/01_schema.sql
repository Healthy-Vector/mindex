-- 01_schema.sql — 핵심 테이블 · EXCLUDE 제약 · 인덱스 (DAR-001, SFR-007)
--
-- D-30으로 리마스터된 스키마다 (docs/mindex_remastered.dbml).
-- D-19~D-29 세대의 candidate 스테이징 계층(rights_grant_candidate,
-- candidate_evidence, rights_evaluation, rights_evaluation_reason,
-- conflict_resolution, rights_grant_history, contract_version,
-- statutory_right, right_mapping)을 전부 걷어내고, "PDF 한 건 = 판정 한 건"
-- 계약서 단위 all-or-nothing 모델로 교체한다 — 새 init이다(D-10, alembic
-- 미도입 + `docker compose down -v` 재생성 전제).
--
-- 이 파일은 테이블 정의만 담는다. 참조 데이터 적재는 03_reference_data.sql,
-- 트리거·판정 함수는 02_conflict_rules.sql이다.
--
-- **단, 2축 판정(legal_right × exploitation_mode, D-27)의 EXCLUDE `&&` 비교
-- 구조는 그대로 유지한다.** JA-C05류 상위-하위 포함관계 버그를 다시 열지
-- 않기 위함이다 — legal_right/exploitation_mode nested-set taxonomy와 그
-- 자기검증 DO 블록은 이번 라운드에서 변경하지 않는다.
--
-- 설계 근거는 docs/DECISIONS.md — D-27(2축 판정, EXCLUDE `&&` 유지) ·
-- D-29(온프레미스 단일 회사, tenant 제거는 유지) · D-30(이번 재설계:
-- candidate 계층 삭제, 계약서 단위 all-or-nothing, content_asset/ip_alias/
-- team/contract_history 신설, rights_grant 재정의).

-- ─────────────────────────────────────────────────────────────
-- 타입
-- ─────────────────────────────────────────────────────────────

-- D-27 — 유지. reason_code.result_type이 여전히 쓴다(conflict_report/진단
-- 출력의 어휘). candidate 워크플로우가 사라지면서 이 값을 직접 산출하는
-- DB 함수는 없어졌지만, 코드 자체는 앱 레이어 참고용 어휘로 유지한다(D-30).
CREATE TYPE result_kind AS ENUM ('NORMAL', 'CONFLICT', 'REVIEW_REQUIRED', 'WARNING');

-- D-04 — 독점은 boolean이 아니라 3값. 유지.
-- 'sole'은 제3자에게는 배타적이나 라이선서 본인은 계속 이용할 수 있는 형태다.
-- 판정에서는 'exclusive'와 동일하게 취급한다 (둘 다 제3자 배타).
CREATE TYPE exclusivity_kind AS ENUM ('exclusive', 'sole', 'non_exclusive');

-- D-31 — 계약 업무 상태는 협의 중(draft), 서명 완료(signed), 종결(cancelled)
-- 세 단계다. draft도 권리를 예약할 수 있으며 그 여부는 rights_grant.active로
-- 표현한다. 취소·해지·협의 결렬은 모두 cancelled로 수렴한다.
CREATE TYPE contract_status AS ENUM ('draft', 'signed', 'cancelled');

-- D-31 — 업로드 문서의 성격과 DB 적용 결과는 서로 다른 축이다.
CREATE TYPE contract_document_kind AS ENUM ('draft', 'final');
CREATE TYPE contract_history_status AS ENUM ('applied', 'conflicted');

-- D-30 — rights_grant는 이제 2단계 상태 모델이다. candidate 승인이라는
-- 중간 단계가 없다 — 배치가 통과하면 곧바로 active다.
CREATE TYPE rights_grant_status AS ENUM ('active', 'terminated');

-- D-30 — 수동 종료 사유. superseded는 같은 계약의 새 세대가 자동으로 이전
-- 세대를 대체할 때, waiver/cancelled는 사람이 terminate_rights_grant()를
-- 직접 호출할 때, expired는 만료 배치(향후 확장)가 쓴다.
CREATE TYPE terminated_reason_kind AS ENUM ('superseded', 'expired', 'waiver', 'cancelled');

-- D-30 — content_asset의 대상 범위 종류. 시리즈 전체/시즌/에피소드/에디션.
CREATE TYPE asset_scope_kind AS ENUM ('SERIES_ALL', 'SEASON', 'EPISODE', 'EDITION');

-- 프런트 필터 전용. 판정 로직·EXCLUDE·트리거 어디에도 관여하지 않는다.
CREATE TYPE ip_activity_kind AS ENUM ('active', 'deactive');

-- ─────────────────────────────────────────────────────────────
-- 참조 테이블 (시드는 03_reference_data.sql)
-- ─────────────────────────────────────────────────────────────

-- D-15 — 국가코드. rights_grant.territory가 참조하는 유일한 지역 어휘다.
-- D-30 — name_ko/name_en 컬럼을 country_label로 정규화했다(§1.8).
CREATE TABLE country (
    code       char(2) PRIMARY KEY,
    in_scope   boolean NOT NULL DEFAULT false   -- WORLDWIDE 전개 대상 8개국 여부
);

-- 국가명 i18n. 라벨 하나당 (국가, 언어) 조합 1행.
CREATE TABLE country_label (
    country_code char(2) NOT NULL REFERENCES country(code),
    lang         char(2) NOT NULL,
    label        text    NOT NULL,
    PRIMARY KEY (country_code, lang)
);

-- D-15 — 지역·대륙 그룹. 저장 계층이 아니라 전개용 참조다.
-- EXCLUDE는 territory를 동등 비교하므로, 태국 권리가 한쪽은 'TH' 다른 쪽은
-- 'SEA'로 저장되면 겹치는데도 인덱스가 충돌을 못 본다 — 저장 단위로 쓰면 안 된다.
-- D-30 — name_ko 컬럼을 territory_group_label로 정규화했다(§1.8).
CREATE TABLE territory_group (
    code       text PRIMARY KEY,        -- 'WORLDWIDE', 'APAC', 'SEA', 'NA'
    note       text
);

CREATE TABLE territory_group_label (
    group_code text NOT NULL REFERENCES territory_group(code) ON DELETE CASCADE,
    lang       char(2) NOT NULL,
    label      text NOT NULL,
    PRIMARY KEY (group_code, lang)
);

CREATE TABLE territory_group_member (
    group_code   text    NOT NULL REFERENCES territory_group(code) ON DELETE CASCADE,
    country_code char(2) NOT NULL REFERENCES country(code),
    PRIMARY KEY (group_code, country_code)
);

-- ── 판정축 1: 법적 권리 (R3) — 변경 없음 (D-27 그대로 유지) ──────
--
-- D-30 — 이번 재설계에서 legal_right/exploitation_mode 두 taxonomy와 그
-- nested-set 좌표·자기검증 DO 블록은 손대지 않는다. JA-C05류 상위-하위
-- 포함관계 버그를 다시 열지 않기 위한 명시적 결정이다.
--
-- lft/rgt는 nested-set 좌표(preorder)다. span은 그로부터 생성되는 반열림
-- 구간이며, EXCLUDE가 이 구간을 && 로 비교해 계층 포함관계를 판정한다:
--   PUBLIC_TRANSMISSION [1,7) && BROADCAST [2,4)  → 겹침 (상위가 하위를 포함)
--   BROADCAST           [2,4) && TRANSMISSION [4,6) → 안 겹침 (형제)
-- 생성 컬럼이라 lft/rgt와 어긋날 수 없다.
CREATE TABLE legal_right (
    code        text PRIMARY KEY,
    parent_code text REFERENCES legal_right(code),
    name_ko     text NOT NULL,
    lft         int  NOT NULL,
    rgt         int  NOT NULL,
    span        int4range GENERATED ALWAYS AS (int4range(lft, rgt + 1)) STORED,
    note        text,

    CONSTRAINT legal_right_span_sane CHECK (rgt > lft)
);

-- ── 판정축 2: 사업적 이용형태 (R4) — 변경 없음 ──────────────────
CREATE TABLE exploitation_mode (
    code        text PRIMARY KEY,
    parent_code text REFERENCES exploitation_mode(code),
    name_ko     text NOT NULL,
    lft         int  NOT NULL,
    rgt         int  NOT NULL,
    span        int4range GENERATED ALWAYS AS (int4range(lft, rgt + 1)) STORED,
    note        text,

    CONSTRAINT exploitation_mode_span_sane CHECK (rgt > lft)
);

-- ── 판정 사유 어휘 마스터 (D-27, D-30에서 축소) ─────────────────
--
-- D-30 — is_blocking/is_review_trigger 컬럼을 삭제한다. 두 컬럼을 소비하던
-- register_candidate()/classify_candidate()가 이번 재설계로 사라졌기
-- 때문이다. 이 테이블은 이제 워크플로우를 구동하지 않는다 — conflict_report/
-- 진단 출력과 앱 레이어가 참고할 공용 어휘일 뿐이다(§1.9).
--
-- right_mapping 삭제로 AMBIGUOUS_CLAUSE·CROSS_BORDER_MUSIC_CLEARANCE는
-- implemented=false로 되돌아간다 — 그 조합을 산출하던 자문표 자체가 없다.
CREATE TABLE reason_code (
    code               text PRIMARY KEY,
    category           text NOT NULL,          -- DATA_QUALITY/AI_QUALITY/SCOPE/AUTHORITY/EXTERNAL
    result_type        result_kind NOT NULL,   -- 이 사유가 유발하는(했던) 판정 결과
    rule_code          text,                   -- 'R3' · 'R7' — 시나리오 문서의 판정 규칙 번호
    severity           smallint NOT NULL DEFAULT 50,  -- 클수록 중대. 대표 사유 선택 정렬용
    is_decision_reason boolean NOT NULL,       -- conflict_report 등 판정 산출물 사유로 쓸 수 있는가
    name_ko            text NOT NULL,
    template_ko        text NOT NULL,          -- 화면 표시 기본 문구
    template_en        text NOT NULL,
    implemented        boolean NOT NULL DEFAULT false,  -- 판정 엔진이 실제로 방출하는가
    active             boolean NOT NULL DEFAULT true,

    -- NORMAL은 "사유 없음"이라 코드가 존재할 수 없다.
    CONSTRAINT reason_code_not_normal CHECK (result_type <> 'NORMAL')
);

-- D-08 보존 — EXCLUDE/트리거가 던지는 constraint_name을 사용자에게 보여줄
-- reason_code로 번역한다. 제약명 2개가 같은 코드 하나로 귀결되는 N:1이라
-- reason_code의 컬럼으로는 표현할 수 없어 별도 표로 둔다.
CREATE TABLE constraint_reason_map (
    constraint_name text PRIMARY KEY,
    reason_code     text NOT NULL REFERENCES reason_code(code)
);

-- ─────────────────────────────────────────────────────────────
-- 도메인 테이블
-- ─────────────────────────────────────────────────────────────

-- 작품(IP). 언어가 달라도 같은 IP면 같은 행이다 — 다국어 충돌(JA-C02)의 근거.
-- D-30 — title_ko/title_en/title_ja 3컬럼을 ip_alias로 정규화했다(§1.1).
CREATE TABLE ip (
    id          bigserial PRIMARY KEY,
    title       text NOT NULL,
    kind        text,                    -- '드라마' · '영화'
    activity    ip_activity_kind NOT NULL DEFAULT 'active',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- D-30 신설(§1.1) — 작품의 다국어/이명 표현.
CREATE TABLE ip_alias (
    id          bigserial PRIMARY KEY,
    ip_id       bigint NOT NULL REFERENCES ip(id) ON DELETE CASCADE,
    alias_text  text NOT NULL,
    lang        char(2),
    alias_type  text NOT NULL DEFAULT 'title',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ip_id, alias_text, lang)
);

CREATE INDEX idx_ip_alias_ip ON ip_alias (ip_id);

-- D-30 신설(§1.2) — 권리 판정의 실제 대상 단위. 시리즈 전체/시즌/에피소드/
-- 에디션을 표현한다. 상위/하위 대상 간 겹침(시리즈 전체 ↔ 시즌2)은 이번
-- 라운드에서 DB가 판정하지 않는다 — content_asset_id 완전 일치만 EXCLUDE
-- 키로 쓴다(MVP 제한, O-07과 연결되는 후속 과제).
CREATE TABLE content_asset (
    id           bigserial PRIMARY KEY,
    ip_id        bigint NOT NULL REFERENCES ip(id),
    parent_id    bigint REFERENCES content_asset(id),
    asset_type   text NOT NULL DEFAULT 'MAIN',
    scope_type   asset_scope_kind NOT NULL DEFAULT 'SERIES_ALL',
    season_no    int,
    episode_no   int,
    edition_code text,
    title        text,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT content_asset_season_scope  CHECK (season_no  IS NULL OR scope_type IN ('SEASON','EPISODE')),
    CONSTRAINT content_asset_episode_scope CHECK (episode_no IS NULL OR scope_type = 'EPISODE'),
    CONSTRAINT content_asset_edition_scope CHECK (edition_code IS NULL OR scope_type = 'EDITION')
);

CREATE INDEX idx_content_asset_ip     ON content_asset (ip_id);
CREATE INDEX idx_content_asset_parent ON content_asset (parent_id);

-- D-30 신설(§1.3) — PIN 기반 팀 관리용 독립 테이블. tenant의 리네이밍이
-- 아니다 — 다른 테이블에 team_id를 전파하지 않고 EXCLUDE 키에도 넣지
-- 않는다(RLS 연동은 SER-002 범위, 이번 라운드 밖).
CREATE TABLE team (
    id         bigserial PRIMARY KEY,
    name       text NOT NULL,
    pin_hash   text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- D-30 — contract는 이제 "하나의 계약 업무 건(case)"이다. PDF/버전/판정
-- 결과는 contract_history로 옮겼다(§1.4). current_history_id의 FK는
-- contract_history 생성 뒤 ALTER로 붙인다 — 두 테이블이 서로를 참조하는
-- 순환이라 한쪽을 먼저 완성할 수 없다.
--
-- uploaded_by/changed_by 등 개인식별 컬럼은 두지 않는다(D-29 정신 연장).
CREATE TABLE contract (
    id                  bigserial PRIMARY KEY,
    title               text,                  -- 계약 목록 화면 표시용 라벨. IP.title과 별개(계약 자체의 사람이 읽는 이름)
    grantor             text NOT NULL,         -- 권리를 주는 쪽(갑)
    grantee             text NOT NULL,         -- 권리를 받는 쪽(을)
    signed_date         date,
    lang                char(2),               -- 'ko' · 'en' · 'ja'
    amount              numeric,               -- SER-006 계층1 암호화 대상 (D-14, 미적용)
    currency            char(4),               -- 'KRW' · 'USD' · 'JPY'
    status              contract_status NOT NULL DEFAULT 'draft',
    current_history_id  bigint,                -- 등록된 최신 세대. FK는 아래서 ALTER로
    source_tmpid        uuid UNIQUE,           -- staging.extract_job.tmpid 참조. FK는
                                                -- 06_staging_schema.sql에서 staging 스키마
                                                -- 생성 후 ALTER로 붙는다 (D-33)

    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),

    -- signed인데 등록된 세대가 없는 행은 존재할 수 없다. 이 CHECK는
    -- contract 자기 컬럼만 보므로 plain CHECK로 충분하다. current_history_id가
    -- 가리키는 세대 자체의 상태·소속 검증은 02_conflict_rules.sql의
    -- validate_contract_signing() 트리거가 한다(다른 테이블 참조가 필요해서).
    CONSTRAINT signed_requires_history
        CHECK (status <> 'signed' OR current_history_id IS NOT NULL)
);

-- D-30 — contract_document + contract_version을 흡수해 대체한다(§1.4).
-- "PDF 한 건 = 판정 한 건"이므로 버전(세대) 하나가 곧 하나의 all-or-nothing
-- 판정 단위다. applied면 그 세대의 rights_grant가 실제로 존재하고,
-- conflicted면 존재하지 않으며 conflict_report에 왜 막혔는지가 남는다.
CREATE TABLE contract_history (
    id               bigserial PRIMARY KEY,
    contract_id      bigint NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    version          int NOT NULL,
    document_kind    contract_document_kind NOT NULL DEFAULT 'draft',
    status           contract_history_status NOT NULL,

    file_name        text NOT NULL,
    file_path        text NOT NULL,          -- S3/Object Storage key. PDF binary는 DB에 안 둠
    file_hash        text NOT NULL,          -- SHA-256 권장. 동일 파일 재업로드 탐지
    mime_type        text NOT NULL DEFAULT 'application/pdf',
    raw_text         text,                   -- PDF 파싱 원문 — SER-006 암호화 대상 (D-14, 미적용)

    conflict_report  jsonb,                  -- status='conflicted'일 때만 채워진다

    uploaded_at      timestamptz NOT NULL DEFAULT now(),

    UNIQUE (contract_id, version),
    CONSTRAINT conflict_report_only_when_conflicted CHECK (status = 'conflicted' OR conflict_report IS NULL),
    CONSTRAINT conflicted_requires_report            CHECK (status <> 'conflicted' OR conflict_report IS NOT NULL)
);

CREATE INDEX idx_contract_history_hash     ON contract_history (file_hash);
CREATE INDEX idx_contract_history_contract ON contract_history (contract_id);
CREATE INDEX idx_contract_history_kind     ON contract_history (document_kind);

-- contract.current_history_id FK. contract_history가 방금 완성됐으므로
-- 이제 붙일 수 있다. ON DELETE SET NULL — 세대가 지워지면 링크만 풀리고,
-- 그 결과 signed_requires_history CHECK가 signed 행에 대해
-- 이 UPDATE 자체를 거부한다(같은 트랜잭션의 SET NULL이 CHECK를 다시 태운다).
ALTER TABLE contract
    ADD FOREIGN KEY (current_history_id)
    REFERENCES contract_history (id)
    ON DELETE SET NULL;

-- ─────────────────────────────────────────────────────────────
-- 권리 레코드 — 현재 점유 중이거나 종료된 권리의 Single Source of Truth
-- (DAR-001, D-30, D-31)
-- ─────────────────────────────────────────────────────────────
--
-- D-30 — candidate 스테이징을 거치지 않는다. save_rights_batch()가 계약서
-- 한 건의 권리 배치를 한 문장으로 INSERT하고, EXCLUDE가 실패하면 전체가
-- 원자적으로 롤백된다(all-or-nothing이 "공짜로" 보장된다, §2).
--
-- lineage_id는 FK가 없는 값 전용 컬럼이다 — 같은 논리적 권리가 개정판을
-- 거치며 이어진다는 것을 표시할 뿐, 참조 무결성이 필요한 관계가 아니다.
-- 최초 등록 시 자기 id로 시작하고(default_lineage_id() 트리거), 개정판에서는
-- save_rights_batch()가 자연키 매칭으로 승계하거나 새로 시작한다(§4.3).
CREATE TABLE rights_grant (
    id                     bigserial PRIMARY KEY,

    contract_id            bigint NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    contract_history_id    bigint NOT NULL REFERENCES contract_history(id) ON DELETE CASCADE,
    content_asset_id       bigint NOT NULL REFERENCES content_asset(id),

    lineage_id             bigint NOT NULL,   -- FK 없음, 값으로만 사용

    status                 rights_grant_status NOT NULL DEFAULT 'active',
    territory               char(2) NOT NULL REFERENCES country(code),

    -- D-27 — 판정축 2개. 유지.
    legal_right              text NOT NULL REFERENCES legal_right(code),
    exploitation_mode        text NOT NULL REFERENCES exploitation_mode(code),

    -- D-27 — 비정규화된 nested-set 구간. EXCLUDE의 키 표현식은 서브쿼리를
    -- 못 쓰므로 참조 테이블에서 조인해 올 수 없다 — 행에 실물로 있어야
    -- 한다. sync_rights_grant_spans() 트리거가 채우며, 앱이 넘긴 값은
    -- 무조건 덮어쓴다(앱이 span을 직접 쓰는 경로를 열면 P-4가 깨진다).
    legal_right_span         int4range NOT NULL,
    exploitation_mode_span   int4range NOT NULL,

    period                   daterange NOT NULL,
    exclusivity               exclusivity_kind NOT NULL,

    -- D-30 — candidate_evidence N행을 대체한다(§1.5). 필드별 근거 위치를
    -- JSONB 한 컬럼에 담되, P-3(원문 인용 필수)는 CHECK로 강제한다.
    -- evidence_quotes_present는 is_valid_evidence() 함수가 필요해
    -- 02_conflict_rules.sql에서 ALTER TABLE로 붙인다.
    evidence                  jsonb NOT NULL,
    conditions_raw             jsonb,           -- 계약서 원문 조건절(정형화 안 된 부가 조건)

    terminated_at              timestamptz,
    terminated_reason          terminated_reason_kind,
    termination_note           text,

    created_at                  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT period_not_empty CHECK (NOT isempty(period)),
    CONSTRAINT terminated_fields_consistent CHECK (
        (status = 'active'     AND terminated_at IS NULL     AND terminated_reason IS NULL) OR
        (status = 'terminated' AND terminated_at IS NOT NULL AND terminated_reason IS NOT NULL)
    ),
    CONSTRAINT evidence_has_required_keys CHECK (
        evidence ?& ARRAY['legal_right','exploitation_mode','territory','period','exclusivity']
    )
);

CREATE INDEX idx_rights_grant_status    ON rights_grant (status);
CREATE INDEX idx_rights_grant_history   ON rights_grant (contract_history_id);
CREATE INDEX idx_rights_grant_lineage   ON rights_grant (lineage_id);
CREATE INDEX idx_rights_grant_contract  ON rights_grant (contract_id);

-- D-27 — 판정키 조회용. 구간 축이 섞여 있어 btree가 아니라 GiST.
CREATE INDEX idx_rights_grant_conflict_key ON rights_grant
    USING gist (content_asset_id, territory, legal_right_span, exploitation_mode_span, period);

-- 만료 감시(SFR-012)용. 선택 항목이지만 인덱스는 지금 만들어 두는 편이 싸다.
CREATE INDEX rights_grant_expiry ON rights_grant ((upper(period)));

-- ─────────────────────────────────────────────────────────────
-- 충돌 판정 1단 — EXCLUDE (D-05, D-27, SFR-007)
-- ─────────────────────────────────────────────────────────────
--
-- 담당: 독점/sole ↔ 독점/sole. 비독점이 낀 조합은 트리거가 맡는다
-- (02_conflict_rules.sql). 담당을 XOR로 배타 분할해 "어느 층이 잡았는지"가
-- 결정론적으로 구분되게 한다.
--
-- 제약명을 바꾸지 않는다(D-08) — RFP §6.3.2가 시연 구간 C에서 이 에러 문구를
-- 화면에 크게 노출하라고 규정하고 README도 이 이름을 문서화하고 있다.
--
-- D-30 — ip_id가 content_asset_id로, status 필터가 'approved'/'final' 2값
-- 판정에서 'active' 단일값으로 바뀌었다. contract_id WITH <>가 새로
-- 추가됐다 — 같은 계약(같은 세대 포함)의 두 행끼리는 EXCLUDE 대상이 아니다
-- (한 배치 내부의 행끼리 서로를 충돌로 잡는 것을 막는다. 배치 내부 중복은
-- 애초에 앱이 같은 세대에 겹치는 권리를 넣지 않는다는 전제이며, 같은
-- INSERT 문 안에서는 GiST EXCLUDE가 신규 행끼리도 서로 비교하므로 이
-- 조건이 없으면 정상적인 배치조차 자기 자신과 충돌 처리될 수 있다).
ALTER TABLE rights_grant
ADD CONSTRAINT no_exclusive_overlap
EXCLUDE USING gist (
    contract_id             WITH <>,
    content_asset_id        WITH =,
    legal_right_span        WITH &&,
    exploitation_mode_span  WITH &&,
    territory               WITH =,
    period                  WITH &&
)
WHERE (exclusivity <> 'non_exclusive' AND status = 'active');

-- D-31 — rights_grant.status='active'는 계약 확정 여부가 아니라 충돌 판정의
-- 현재 점유 여부다. 확정된 권리만 필요한 조회는 contract.status를 함께 봐야
-- 하므로 공용 view로 고정한다. draft 계약의 active grant는 예약을 차지하지만
-- 이 view에는 나타나지 않는다.
CREATE VIEW confirmed_rights_grant AS
SELECT g.*
FROM rights_grant g
JOIN contract c ON c.id = g.contract_id
WHERE g.status = 'active'
  AND c.status = 'signed';

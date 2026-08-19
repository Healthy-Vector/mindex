-- 01_schema.sql — 핵심 테이블 · EXCLUDE 제약 · 인덱스 (DAR-001, SFR-007)
--
-- D-24·D-25로 리마스터된 스키마다 (docs/mindex_remastered.dbml).
-- 이전 세대(draft/review/provisional/complete/terminated 5-status rights_grant
-- 단일 테이블 + probe/register 함수)를 완전히 대체한다 — 증분 ALTER가 아니라
-- 새 init이다(D-10, alembic 미도입 + `docker compose down -v` 재생성 전제).
--
-- 이 파일은 테이블 정의만 담는다. 참조 데이터 적재는 03_reference_data.sql,
-- 트리거·리포트 함수는 02_conflict_rules.sql이다.
--
-- 테이블 생성 순서는 FK 의존성을 따른다: ip/contract → contract_document →
-- rights_grant_candidate → candidate_evidence → rights_grant(candidate가
-- source_candidate_id로 필요) → rights_evaluation(candidate 필요) →
-- rights_evaluation_reason(evaluation·rights_grant 둘 다 필요) →
-- conflict_resolution → rights_grant_history. contract와
-- contract_document는 서로를 참조하는 순환이라 final_document_id의 FK만
-- contract_document 생성 뒤 ALTER로 붙인다.
--
-- 설계 근거는 docs/DECISIONS.md — D-03(지역 행 정규화) · D-04(3값 enum) ·
-- D-05(2단 판정) · D-08(제약명 유지) · D-13(권리유형 5종) ·
-- D-15(국가코드만 저장) · D-24(candidate/판정결과/
-- conflict_resolution 분리, WAIVER=충돌 원인 제거) · D-25(candidate_status
-- 4값+review_reason 분리·
-- contract/document 상태 비동기화).
--
-- D-27 — 판정축을 legal_right × exploitation_mode 2축으로 분리하고(둘 다
-- nested-set 계층), 판정 사유를 reason_code 단일 마스터로 정규화했다.
-- rights_type_kind·review_reason_kind ENUM과 conflict_code 테이블이 사라졌고
-- conflict_result가 rights_evaluation + rights_evaluation_reason으로 쪼개졌다.
-- D-29 — 설치당 단일 회사인 온프레미스 제품 경계를 반영해 tenant와 tenant_id를
-- 제거했다. 후보 근거는 candidate_evidence N행으로 분리한다.

-- ─────────────────────────────────────────────────────────────
-- 타입
-- ─────────────────────────────────────────────────────────────

-- D-27 — D-13의 rights_type_kind ENUM(유통창구 5종)을 폐기한다.
-- 판정축이 하나가 아니라 둘이기 때문이다:
--   legal_right       — 법적으로 무엇을 할 권리인가 (R3)
--   exploitation_mode — 그 권리를 사업적으로 어떻게 이용하는가 (R4)
-- 둘 다 상위-하위 포함관계를 갖는 계층이라 ENUM으로는 표현할 수 없다.
-- 참조 테이블 + nested-set 구간(span)으로 아래에 정의한다.
--
-- D-13이 "두 축을 섞으면 판정이 결정론을 잃는다"고 우려했던 것은 두 축을
-- 하나의 어휘에 뭉쳐 넣는 경우다. 여기서는 섞지 않는다 — 서로 독립적인
-- 두 개의 결정론적 축이고, EXCLUDE가 둘을 각각 && 로 비교한다.

-- D-27 — 판정 결과 4종. 시나리오 문서의 expected_result와 같은 값이다.
CREATE TYPE result_kind AS ENUM ('NORMAL', 'CONFLICT', 'REVIEW_REQUIRED', 'WARNING');

-- D-04 — 독점은 boolean이 아니라 3값.
-- 'sole'은 제3자에게는 배타적이나 라이선서 본인은 계속 이용할 수 있는 형태다.
-- 판정에서는 'exclusive'와 동일하게 취급한다 (둘 다 제3자 배타).
CREATE TYPE exclusivity_kind AS ENUM ('exclusive', 'sole', 'non_exclusive');

-- D-24 — 계약 건(case) 자체의 워크플로우 상태.
CREATE TYPE contract_status AS ENUM (
    'draft',       -- 계약 건 생성/문서 업로드 전후
    'review',      -- AI 분석 및 사용자 검토 중
    'approved',    -- 1차 승인 완료. 최종 계약 등록 전
    'final',       -- 최종 계약으로 등록 완료
    'rejected',    -- 사용자가 계약 진행을 파기/거절
    'terminated'   -- 최종 계약 이후 해지/종료
);

-- D-24 — 계약 건에 업로드된 PDF/문서 한 버전의 상태.
CREATE TYPE document_status AS ENUM (
    'uploaded', 'parsing', 'parsed', 'review', 'approved', 'rejected', 'final', 'failed'
);

-- D-25 — 상태(candidate_status)와 원인(review_reason)을 분리한다.
-- extracted: AI 추출 직후, 아직 사람이 안 본 상태.
-- review: 사람의 확인/수정이 필요 — review_reason이 왜인지 말한다.
CREATE TYPE candidate_status AS ENUM ('extracted', 'review', 'approved', 'rejected');

-- D-27 — D-25의 review_reason_kind ENUM을 폐기한다.
-- "왜 검토가 필요한가"(후보 단계)와 "왜 이 판정이 나왔는가"(판정 단계)가
-- 사실상 같은 축인데 ENUM과 conflict_code 두 군데서 따로 관리되고 있었다 —
-- 실제로 드리프트가 일어났다(D-25가 TERRITORY_UNRESOLVED를 MISSING_FIELD로
-- 뭉갰지만 시나리오 문서는 여전히 TERRITORY_UNRESOLVED를 정답 코드로 쓴다).
-- 둘 다 아래 reason_code 마스터 하나를 FK로 참조한다.

-- D-24 — rights_grant는 이제 "승인된 권리"만 담는다. 미확정 후보의 워크플로우
-- 상태는 candidate_status가 담당하므로 draft/review는 여기 없다.
CREATE TYPE rights_grant_status AS ENUM ('approved', 'final', 'terminated');

-- D-24 — 판정 사유 한 건의 처리 상태. D-27에서 rights_evaluation_reason으로 옮겨갔다.
CREATE TYPE conflict_status AS ENUM ('detected', 'resolved', 'waived');

-- D-24 — MVP 지원: waiver·amended·rejected. MUTUAL_AGREEMENT·MANUAL_OVERRIDE는
-- 겹친 두 rights_grant를 그대로 공존시켜야 하는데, EXCLUDE의 WHERE절은 다른
-- 테이블(conflict_resolution)을 참조하는 서브쿼리를 못 쓴다. 이걸 트리거로
-- 새로 구현하면 D-05·D-08의 "EXCLUDE=결정론적 무조건 차단" 원칙이 흔들리므로
-- 이번 범위에서는 뺀다. 값은 남겨 향후 확장 지점만 표시한다.
CREATE TYPE resolution_type AS ENUM (
    'waiver', 'amended', 'rejected', 'mutual_agreement', 'manual_override'
);

CREATE TYPE resolution_status AS ENUM ('pending', 'approved', 'rejected');

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

-- D-15 — 지역·대륙 그룹. 저장 계층이 아니라 전개용 참조다.
-- EXCLUDE는 territory를 동등 비교하므로, 태국 권리가 한쪽은 'TH' 다른 쪽은
-- 'SEA'로 저장되면 겹치는데도 인덱스가 충돌을 못 본다 — 저장 단위로 쓰면 안 된다.
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

-- ── 판정축 1: 법적 권리 (R3) ────────────────────────────────
--
-- D-27 — 관할 중립 taxonomy다. 관할별 실제 조문(공중송신권 / 公衆送信権 /
-- public performance)은 statutory_right가 따로 담는다. 판정축을 관할별 코드로
-- 두면 KR_TRANSMISSION과 JP_TRANSMISSION이 서로 다른 트리에 있어 영영 안 겹치는
-- 버그가 된다 — JA-C05(自動公衆送信 vs 기존 전송권)가 정확히 그 케이스다.
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

-- ── 판정축 2: 사업적 이용형태 (R4) ──────────────────────────
--
-- D-27 — D-13의 5종(SVOD/AVOD/TVOD/TV_LINEAR/THEATRICAL)을 그대로 품되,
-- 계약서가 실제로 쓰는 넓은 표현("all on-demand audiovisual streaming rights")을
-- 받을 상위 노드 VOD를 추가했다. VOD [1,9)는 SVOD/AVOD/TVOD를 전부 포함하므로
-- 넓은 이용형태 부여와 개별 창구 부여가 겹치는 L2 케이스를 EXCLUDE가 잡는다.
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

-- 관할별 법정 지분권(자문축). 판정에 직접 쓰지 않는다 — 화면 표시와
-- 데모 시나리오 1(겨울연가·NHK)의 경고 근거다.
-- D-27 — legal_right_code로 관할 중립 판정축에 연결된다. 이래야 JA-C05의
-- 自動公衆送信이 legal_right=TRANSMISSION으로 정규화되면서도 화면에는
-- 일본 조문명을 그대로 보여줄 수 있다.
CREATE TABLE statutory_right (
    code             text PRIMARY KEY,
    jurisdiction     char(2) NOT NULL REFERENCES country(code),
    legal_right_code text NOT NULL REFERENCES legal_right(code),
    name_local       text NOT NULL,
    name_ko          text NOT NULL,
    parent_code      text REFERENCES statutory_right(code),  -- 관할 내부 상위-하위
    note             text
);

-- D-27 — 역할 재정의. 예전에는 (유통창구 → 법정권리) 변환표였으나, 이제는
-- 두 판정축 조합이 해당 관할에서 통상 성립하는지를 말하는 자문/검증표다.
--
-- **자동 변환에 쓰지 않는다.** "SVOD이니까 legal_right는 TRANSMISSION"으로
-- 채우는 코드를 만들지 않는다 — 계약서에 안 쓰인 법적 권리를 시스템이 창작하는
-- 것이고, 그건 P-1(LLM은 변환만, 판정 안 함)이 금지하는 바로 그 행위다.
-- 용도는 둘뿐이다:
--   1. 조합이 없거나 is_typical=false → AMBIGUOUS_CLAUSE 사유로 review 큐에 올림
--   2. advisory 문구 조회 (rights_advisory(), 02_conflict_rules.sql)
CREATE TABLE right_mapping (
    legal_right       text    NOT NULL REFERENCES legal_right(code),
    exploitation_mode text    NOT NULL REFERENCES exploitation_mode(code),
    jurisdiction      char(2) NOT NULL REFERENCES country(code),
    is_typical        boolean NOT NULL DEFAULT true,
    advisory          text,
    PRIMARY KEY (legal_right, exploitation_mode, jurisdiction)
);

-- ── 판정 사유 마스터 (D-27) ─────────────────────────────────
--
-- D-25의 review_reason_kind ENUM과 D-18의 conflict_code 테이블을 하나로 합친
-- 단일 코드셋이다. "왜 검토가 필요한가"와 "왜 이 판정이 나왔는가"는 의미상
-- 용도만 다를 뿐 같은 축이라, 두 군데서 관리하면 드리프트가 생긴다.
-- 용도 구분은 is_review_trigger / is_decision_reason 두 플래그가 한다.
--
-- 코드 체계에서 MISSING과 UNRESOLVED를 반드시 구분한다:
--   TERRITORY_MISSING     — territory 컬럼 자체가 NULL (DB가 결정론적으로 판단)
--   TERRITORY_UNRESOLVED  — "Worldwide except Korea"처럼 표현은 있으나
--                            국가코드로 정규화 실패 (추출기만 알 수 있다)
CREATE TABLE reason_code (
    code               text PRIMARY KEY,
    category           text NOT NULL,          -- DATA_QUALITY/AI_QUALITY/SCOPE/AUTHORITY/EXTERNAL
    result_type        result_kind NOT NULL,   -- 이 사유가 유발하는 판정 결과
    rule_code          text,                   -- 'R3' · 'R7' — 시나리오 문서의 판정 규칙 번호
    severity           smallint NOT NULL DEFAULT 50,  -- 클수록 중대. primary 사유 선택 정렬용
    is_blocking        boolean NOT NULL,       -- register_candidate()를 막는가
    is_review_trigger  boolean NOT NULL,       -- candidate.review_reason_code로 쓸 수 있는가
    is_decision_reason boolean NOT NULL,       -- 판정 산출물 사유로 쓸 수 있는가
    name_ko            text NOT NULL,
    template_ko        text NOT NULL,          -- 화면 표시·AI 첨언 생성의 기본 문구
    template_en        text NOT NULL,
    implemented        boolean NOT NULL DEFAULT false,  -- 판정 엔진이 실제로 방출하는가
    active             boolean NOT NULL DEFAULT true,

    CONSTRAINT reason_code_has_a_use CHECK (is_review_trigger OR is_decision_reason),
    -- NORMAL은 "사유 없음"이라 코드가 존재할 수 없다.
    CONSTRAINT reason_code_not_normal CHECK (result_type <> 'NORMAL')
);

-- D-08 보존 — EXCLUDE/트리거가 던지는 constraint_name을 사용자에게 보여줄
-- reason_code로 번역한다. 제약명 2개가 같은 코드 하나로 귀결되는 N:1이라
-- reason_code의 컬럼으로는 표현할 수 없어 별도 표로 둔다.
-- 앱의 SFR-011 핸들러가 ExclusionViolation을 잡으면 diag.constraint_name으로
-- 이 표를 조회한다.
CREATE TABLE constraint_reason_map (
    constraint_name text PRIMARY KEY,
    reason_code     text NOT NULL REFERENCES reason_code(code)
);

-- ─────────────────────────────────────────────────────────────
-- 도메인 테이블
-- ─────────────────────────────────────────────────────────────

-- 작품(IP). 언어가 달라도 같은 IP면 같은 행이다 — 다국어 충돌(JA-C02)의 근거.
CREATE TABLE ip (
    id          bigserial PRIMARY KEY,
    title_ko    text,
    title_en    text,
    title_ja    text,
    kind        text,                    -- '드라마' · '영화'
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- D-24 — contract는 이제 "하나의 계약 업무 건(case)"이다. PDF 원문·버전은
-- contract_document로 옮겼다(SER-006 암호화 대상 raw_text도 함께 옮김, D-14).
-- final_document_id의 FK는 contract_document 생성 뒤 ALTER로 붙인다 —
-- 두 테이블이 서로를 참조하는 순환이라 한쪽을 먼저 완성할 수 없다.
CREATE TABLE contract (
    id                bigserial PRIMARY KEY,
    counterparty      text NOT NULL,
    signed_date       date,
    lang              char(2),               -- 'ko' · 'en' · 'ja'
    amount            numeric,               -- SER-006 계층1 암호화 대상 (D-14, 미적용)
    currency          char(4),               -- 'KRW' · 'USD' · 'JPY'
    status            contract_status NOT NULL DEFAULT 'draft',
    final_document_id bigint,                -- 최종 채택 contract_document.id. FK는 아래서 ALTER로

    -- SFR-006 메타데이터 버전 카운터. contract_version_snapshot 트리거가 관리한다.
    version           int NOT NULL DEFAULT 1,

    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    -- D-25 — status='final'인데 final_document_id가 비어 있는 행은 존재할 수 없다.
    -- 이 CHECK는 contract 자기 컬럼만 보므로 plain CHECK로 충분하다. final_document_id가
    -- 가리키는 문서 자체의 상태·소속 검증은 02_conflict_rules.sql의
    -- validate_contract_finalize() 트리거가 한다(다른 테이블 참조가 필요해서).
    CONSTRAINT final_requires_document CHECK (status <> 'final' OR final_document_id IS NOT NULL)
);

-- 같은 계약 건에 수정 PDF를 여러 번 올릴 수 있다. raw_text가 여기로 옮겨왔다 —
-- SER-006 계층1 암호화 대상은 이제 이 컬럼이다(D-14, 미적용).
CREATE TABLE contract_document (
    id           bigserial PRIMARY KEY,
    contract_id  bigint NOT NULL,
    version      int    NOT NULL,          -- 계약 건 내부 문서 버전
    file_name    text   NOT NULL,
    storage_key  text   NOT NULL,          -- S3/Object Storage key. PDF binary는 DB에 안 둠
    file_hash    text   NOT NULL,          -- SHA-256 권장. 동일 파일 재업로드 탐지
    mime_type    text   NOT NULL DEFAULT 'application/pdf',
    status       document_status NOT NULL DEFAULT 'uploaded',
    raw_text     text,                     -- PDF 파싱 원문 — SER-006 암호화 대상 (D-14, 미적용)
    uploaded_by  text,
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    parsed_at    timestamptz,

    FOREIGN KEY (contract_id) REFERENCES contract (id) ON DELETE CASCADE,
    UNIQUE (contract_id, version)
);

CREATE INDEX idx_document_hash ON contract_document (file_hash);

-- contract.final_document_id FK. contract_document가 방금 완성됐으므로
-- 이제 붙일 수 있다. ON DELETE SET NULL — 문서가 지워지면 링크만 풀리고,
-- 그 결과 final_requires_document CHECK가 status='final'인 행에 대해 이 UPDATE 자체를
-- 거부한다(같은 트랜잭션의 SET NULL이 CHECK를 다시 태운다) — 즉 최종 계약의
-- 유일한 근거 문서는 구조적으로 삭제될 수 없다.
ALTER TABLE contract
    ADD FOREIGN KEY (final_document_id)
    REFERENCES contract_document (id)
    ON DELETE SET NULL;

-- 계약 메타데이터 변경 이력(append-only). PDF 버전은 contract_document가 담당하고
-- 이 테이블은 counterparty·status·final_document_id 등 메타데이터 변경만 스냅샷한다.
CREATE TABLE contract_version (
    id            bigserial PRIMARY KEY,
    contract_id   bigint NOT NULL,
    version       int    NOT NULL,
    changed_by    text,
    changed_at    timestamptz NOT NULL DEFAULT now(),
    snapshot      jsonb  NOT NULL,       -- 변경 시점의 계약 메타데이터 필드 전체

    FOREIGN KEY (contract_id) REFERENCES contract (id) ON DELETE CASCADE,
    UNIQUE (contract_id, version)
);

-- D-22에서 확립한 패턴 그대로 유지 — contract_version을 실제로 채우는 경로가
-- 앱에 없어도 DB가 대신 채운다(P-4). BEFORE UPDATE에서 NEW.version을 올리고
-- OLD 스냅샷을 contract_version에 남긴다. changed_by는 앱이 세션 GUC
-- (mindex.changed_by)로 넘기면 반영되고, 안 넘기면 NULL로 남는다.
CREATE OR REPLACE FUNCTION snapshot_contract_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO contract_version (contract_id, version, changed_by, snapshot)
    VALUES (
        OLD.id, OLD.version,
        NULLIF(current_setting('mindex.changed_by', true), ''),
        to_jsonb(OLD)
    );
    NEW.version := OLD.version + 1;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER contract_version_snapshot
    BEFORE UPDATE ON contract
    FOR EACH ROW
    WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION snapshot_contract_version();

-- ─────────────────────────────────────────────────────────────
-- AI 추출 / 검토 staging (D-24)
-- ─────────────────────────────────────────────────────────────
--
-- AI가 문서에서 추출한 아직 미확정인 권리 후보. 사용자가 승인하기 전에는
-- rights_grant에 넣지 않는다 — register_candidate()(02_conflict_rules.sql)가
-- 유일한 승격 경로다.
CREATE TABLE rights_grant_candidate (
    id            bigserial PRIMARY KEY,
    contract_id   bigint NOT NULL,
    document_id   bigint NOT NULL,
    ip_id         bigint NOT NULL,

    -- D-27 — 판정축 2개. 둘 다 nullable이다(추출 실패 시 review로 간다).
    territory          char(2)   REFERENCES country(code),
    legal_right        text      REFERENCES legal_right(code),
    exploitation_mode  text      REFERENCES exploitation_mode(code),
    period             daterange,
    exclusivity        exclusivity_kind,

    confidence    numeric(3,2),      -- AI 추출 신뢰도 0.00~1.00 (SFR-004)

    status        candidate_status NOT NULL DEFAULT 'extracted',
    -- D-25 — 이력 보존을 위해 status가 review를 벗어나도 지우지 않는다.
    -- D-27 — ENUM에서 reason_code 마스터 FK로 바뀌었다. 판정 사유와 같은 코드셋을
    -- 쓰되 is_review_trigger=true인 코드만 허용한다(검증은 classify_candidate()).
    review_reason_code text REFERENCES reason_code(code),
    decided_by    text,
    decided_at    timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (contract_id) REFERENCES contract         (id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES contract_document(id) ON DELETE CASCADE,
    FOREIGN KEY (ip_id)       REFERENCES ip               (id),

    -- D-25 — review 상태인데 사유가 없는 행은 존재할 수 없다.
    CONSTRAINT review_requires_reason CHECK (status <> 'review' OR review_reason_code IS NOT NULL)
);

CREATE INDEX idx_candidate_document ON rights_grant_candidate (document_id);
CREATE INDEX idx_candidate_review_queue ON rights_grant_candidate (created_at)
    WHERE status = 'review';
CREATE INDEX idx_candidate_probe_key
    ON rights_grant_candidate (ip_id, territory, legal_right, exploitation_mode);

-- D-29 — 후보 하나의 판단 근거는 여러 페이지·조항에 걸칠 수 있으므로 N행으로
-- 분리한다. document_id는 candidate에서 결정되므로 중복 저장하지 않는다.
-- 페이지를 알 수 없는 OCR/파서도 수용하되, 인용 원문은 반드시 남긴다.
CREATE TABLE candidate_evidence (
    id            bigserial PRIMARY KEY,
    candidate_id  bigint NOT NULL REFERENCES rights_grant_candidate(id) ON DELETE CASCADE,
    page_start    int,
    page_end      int,
    source_clause text,
    source_quote  text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT evidence_quote_not_blank CHECK (btrim(source_quote) <> ''),
    CONSTRAINT evidence_page_start_positive CHECK (page_start IS NULL OR page_start > 0),
    CONSTRAINT evidence_page_end_valid CHECK (
        page_end IS NULL OR (page_start IS NOT NULL AND page_end >= page_start)
    )
);

CREATE INDEX idx_candidate_evidence_candidate ON candidate_evidence (candidate_id);

-- ─────────────────────────────────────────────────────────────
-- 권리 레코드 — 승인된 데이터의 Single Source of Truth (DAR-001, D-24)
-- ─────────────────────────────────────────────────────────────
--
-- D-03 · D-15 — 지역 1개당 1행. 여러 지역을 커버하는 권리는 지역 수만큼 행이 된다.
-- source_candidate_id가 어떤 AI 후보 승인으로 생성됐는지 추적한다(D-25) — 이 FK가
-- 걸려 있는 한 그 candidate 행은 삭제되지 않으므로 Evidence Anchoring(P-3)이
-- 구조적으로 보존된다. rights_grant_candidate 바로 다음에 만드는 이유는
-- source_candidate_id FK가 그 테이블을 필요로 하기 때문이다 —
-- rights_evaluation_reason이 이 테이블도 참조하므로 그보다 먼저 와야 한다.
CREATE TABLE rights_grant (
    id                   bigserial PRIMARY KEY,
    contract_id          bigint NOT NULL,
    document_id          bigint NOT NULL,   -- 이 권리 데이터가 확정된 근거 PDF
    source_candidate_id  bigint NOT NULL UNIQUE,
    ip_id                bigint NOT NULL,

    status       rights_grant_status NOT NULL DEFAULT 'approved',
    territory    char(2)          NOT NULL REFERENCES country(code),

    -- D-27 — 판정축 2개.
    legal_right       text NOT NULL REFERENCES legal_right(code),
    exploitation_mode text NOT NULL REFERENCES exploitation_mode(code),

    -- D-27 — 비정규화된 nested-set 구간. EXCLUDE의 WHERE절·키 표현식은
    -- 서브쿼리를 못 쓰므로 참조 테이블에서 조인해 올 수 없다 — 행에 실물로
    -- 있어야 한다. sync_rights_grant_spans() 트리거가 채우며, 앱이 넘긴 값은
    -- 무조건 덮어쓴다(앱이 span을 직접 쓰는 경로를 열면 P-4가 깨진다).
    legal_right_span       int4range NOT NULL,
    exploitation_mode_span int4range NOT NULL,

    period       daterange        NOT NULL,   -- 반열림 구간 [start,end)
    exclusivity  exclusivity_kind NOT NULL,

    verified_by  text NOT NULL,      -- 승인 사용자
    verified_at  timestamptz NOT NULL DEFAULT now(),
    created_at   timestamptz NOT NULL DEFAULT now(),

    -- source_candidate_id는 candidate 삭제를 막는 게 목적이라
    -- CASCADE를 안 준다 — 나머지는 contract가 지워지면 함께 정리되는 게 자연스럽다.
    --
    -- 미검증 위험 — source_candidate_id가 CASCADE가 아니고
    -- rights_grant_candidate.contract_id는 CASCADE라서, `DELETE FROM contract`가
    -- rights_grant보다 rights_grant_candidate 캐스케이드를 먼저 처리하면 이
    -- RESTRICT에 걸려 삭제 전체가 실패할 수 있다(diamond cascade 순서는
    -- PostgreSQL이 보장하지 않는다). 실사용에서는 `docker compose down -v`
    -- 볼륨 재생성으로 정리하므로 안 부딪히지만, 테스트 하네스가 `DELETE FROM
    -- contract`로 건별 정리를 시도한다면 스파이크로 실측 확인 후 안전한
    -- 순서(rights_grant → rights_grant_candidate → contract)로 명시적 DELETE를
    -- 쓸 것.
    FOREIGN KEY (contract_id)         REFERENCES contract              (id) ON DELETE CASCADE,
    FOREIGN KEY (document_id)         REFERENCES contract_document     (id) ON DELETE CASCADE,
    FOREIGN KEY (source_candidate_id) REFERENCES rights_grant_candidate(id),
    FOREIGN KEY (ip_id)               REFERENCES ip                    (id),

    -- 기간은 반열림 구간이어야 한다. 종료 12/31 다음 날 시작(2027-01-01)이
    -- 겹치지 않는다는 것이 시나리오 EN-B01의 판정 근거다.
    CONSTRAINT period_not_empty CHECK (NOT isempty(period))
);

-- ─────────────────────────────────────────────────────────────
-- 충돌 판정 1단 — EXCLUDE (D-05, SFR-007)
-- ─────────────────────────────────────────────────────────────
--
-- 담당: 독점/sole ↔ 독점/sole. 비독점이 낀 조합은 트리거가 맡는다(02_conflict_rules.sql).
-- 담당을 XOR로 배타 분할해 "어느 층이 잡았는지"가 결정론적으로 구분되게 한다.
--
-- 제약명을 바꾸지 않는다(D-08) — RFP §6.3.2가 시연 구간 C에서 이 에러 문구를
-- 화면에 크게 노출하라고 규정하고 README도 이 이름을 문서화하고 있다.
--
-- D-24 — status 필터가 provisional·complete에서 approved·final로 바뀌었다.
-- rights_grant_status에는 이제 draft·review가 없다(그 워크플로우는
-- rights_grant_candidate.status로 옮겨갔다) — approved·final 둘 다 "살아있는"
-- 권리이므로 둘 다 판정 대상이다. terminated만 제외된다.
-- D-27 — rights_type WITH = 한 축이 legal_right_span/exploitation_mode_span
-- 두 축의 && 로 바뀌었다. 등호가 아니라 구간 겹침이라 상위-하위 포함관계가
-- 그대로 충돌로 잡힌다(R3·R4):
--   PUBLIC_TRANSMISSION [1,7) && TRANSMISSION [4,6) → 충돌 (JA-C05)
--   VOD [1,9)                 && AVOD [4,6)        → 충돌 (넓은 이용형태 L2)
--   SVOD [2,4)                && TVOD [6,8)        → 통과 (동일 권리, 다른 창구)
-- int4range는 GiST 기본 opclass가 있어 확장이 필요 없다. 스칼라 = 축은
-- 기존대로 btree_gist가 담당한다(00_extensions.sql 무변경).
ALTER TABLE rights_grant
ADD CONSTRAINT no_exclusive_overlap
EXCLUDE USING gist (
    ip_id                  WITH =,
    legal_right_span       WITH &&,
    exploitation_mode_span WITH &&,
    territory              WITH =,
    period                 WITH &&
)
WHERE (exclusivity <> 'non_exclusive' AND status IN ('approved', 'final'));

CREATE INDEX idx_rights_grant_status ON rights_grant (status);
CREATE INDEX idx_rights_grant_document ON rights_grant (document_id);

-- D-27 — 판정키 조회용. 구간 축이 섞여 있어 btree가 아니라 GiST다.
-- check_exclusivity_conflict()와 evaluate_candidate()의 비교 쿼리가 탄다.
CREATE INDEX idx_rights_grant_conflict_key ON rights_grant
    USING gist (ip_id, territory, legal_right_span, exploitation_mode_span, period);

-- 만료 감시(SFR-012)용. 선택 항목이지만 인덱스는 지금 만들어 두는 편이 싸다.
CREATE INDEX rights_grant_expiry ON rights_grant ((upper(period)));

-- ─────────────────────────────────────────────────────────────
-- DB가 계산한 충돌 사실 (D-24)
-- ─────────────────────────────────────────────────────────────
--
-- D-27 — conflict_result를 2층으로 나눈다.
--
-- 판정 결과(Result)와 판정 사유(Reason Code)는 다른 것이다. CONFLICT는 "결론"이고
-- EXCLUSIVE_RIGHT_OVERLAP은 "왜 그 결론인가"다. 게다가 결론 하나에 사유가 여럿일
-- 수 있다 — 기존 독점권 침해 + 상위 계약 기간 초과 + sublicense 금지가 동시에
-- 성립하면 결과는 CONFLICT 하나지만 사유는 셋이다.
--
-- 옛 conflict_result는 이름부터 CONFLICT만 담을 수 있어 REVIEW_REQUIRED·WARNING을
-- 넣을 자리가 없었다(상대 grant가 없는 판정이라 conflicting_grant_id NOT NULL에
-- 걸린다). 이제 결과는 rights_evaluation, 사유는 rights_evaluation_reason이다.
--
-- 판정 1회 = rights_evaluation 1행. 재판정(WAIVER 처리 후 재검사 등)하면 새 행이
-- 쌓인다 — append-only이고 "현재 판정"은 candidate별 MAX(id)다.
CREATE TABLE rights_evaluation (
    id                bigserial PRIMARY KEY,
    candidate_id      bigint NOT NULL,
    result_type       result_kind NOT NULL,

    -- AI 첨언은 판정 전체에 대해 1건이다(화면이 primary 사유 하나를 크게 보여주고
    -- 그 아래 세부 사유를 나열하는 구조와 맞다). DB 판정 사실과 컬럼 레벨로
    -- 분리한다 — P-1(LLM은 변환만, 판정 안 함)을 구조로 강제한다.
    ai_commentary     text,
    ai_recommendation text,
    ai_model          text,
    ai_generated_at   timestamptz,

    evaluated_at      timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (candidate_id)
        REFERENCES rights_grant_candidate (id) ON DELETE CASCADE
);

CREATE INDEX idx_evaluation_candidate ON rights_evaluation (candidate_id);
CREATE INDEX idx_evaluation_result ON rights_evaluation (result_type);

-- 사유 N건. 충돌 상대 grant와 겹침 구간이 여기 붙는다 — 한 후보가 서로 다른
-- 기존 권리 3건과 각각 다른 사유로 부딪히는 경우를 자연스럽게 표현한다.
-- REVIEW_REQUIRED·WARNING 사유는 상대 grant가 없으므로 conflicting_grant_id가 NULL이다.
CREATE TABLE rights_evaluation_reason (
    id                   bigserial PRIMARY KEY,
    evaluation_id        bigint NOT NULL,
    reason_code          text   NOT NULL REFERENCES reason_code(code),
    is_primary           boolean NOT NULL DEFAULT false,
    status               conflict_status NOT NULL DEFAULT 'detected',

    conflicting_grant_id bigint,      -- CONFLICT 사유만. 나머지는 NULL
    overlap_period       daterange,   -- DB가 계산한 실제 겹침 기간
    deterministic_detail jsonb,       -- 비교 필드·값 등 재현 가능한 DB 판정 결과

    FOREIGN KEY (evaluation_id)        REFERENCES rights_evaluation (id) ON DELETE CASCADE,
    FOREIGN KEY (conflicting_grant_id) REFERENCES rights_grant      (id) ON DELETE CASCADE
);

CREATE INDEX idx_evaluation_reason_eval ON rights_evaluation_reason (evaluation_id);
CREATE INDEX idx_evaluation_reason_grant ON rights_evaluation_reason (conflicting_grant_id);
CREATE INDEX idx_evaluation_reason_status ON rights_evaluation_reason (status);

-- 화면에서 크게 보여줄 대표 사유는 판정당 최대 1건이다.
CREATE UNIQUE INDEX uq_evaluation_primary_reason
    ON rights_evaluation_reason (evaluation_id) WHERE is_primary;

-- D-24 — 충돌을 무시하지 않는다. WAIVER 승인 시 트리거(02_conflict_rules.sql의
-- apply_waiver_termination())가 conflicting_grant_id가 가리키는 기존 rights_grant를
-- TERMINATED로 정리해 충돌의 물리적 원인을 제거한다. 그 뒤 candidate를 재검사하고,
-- 통과하면 신규 rights_grant를 INSERT한다 — 이 INSERT는 다른 모든 INSERT와 동일하게
-- EXCLUDE를 통과해야 한다. EXCLUDE에는 예외 조건이 없다.
--
-- AMENDED/REJECTED는 rights_grant를 건드리지 않는다 — candidate 쪽에서 끝난다.
-- D-27 — 참조 대상이 conflict_result에서 rights_evaluation_reason으로 내려왔다.
-- WAIVER 트리거가 "정확히 어느 기존 grant를 종료할지" 결정해야 하는데 그
-- conflicting_grant_id가 이제 사유 행에 있기 때문이다. 판정 단위로만 알면
-- 사유가 여럿일 때 어느 상대를 정리할지 결정할 수 없다.
CREATE TABLE conflict_resolution (
    id                    bigserial PRIMARY KEY,
    evaluation_reason_id  bigint NOT NULL,
    resolution_type       resolution_type NOT NULL,
    status                resolution_status NOT NULL DEFAULT 'pending',
    reason                text NOT NULL,     -- 왜 충돌을 이렇게 처리하는지 감사 가능한 근거
    evidence_document_id  bigint,            -- 합의서/수정본 등이 시스템 문서라면 연결
    approved_by           text,
    approved_at           timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (evaluation_reason_id) REFERENCES rights_evaluation_reason (id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_document_id) REFERENCES contract_document        (id) ON DELETE SET NULL
);

CREATE INDEX idx_resolution_conflict ON conflict_resolution (evaluation_reason_id);
CREATE INDEX idx_resolution_status ON conflict_resolution (status);

-- ─────────────────────────────────────────────────────────────
-- history — 확정 데이터의 감사 로그 (D-18, D-24)
-- ─────────────────────────────────────────────────────────────
--
-- D-24 — staging 용도로 쓰지 않는다. 미확정 AI 추출 이력은 이제
-- rights_grant_candidate 자체가 담당하므로, 이 테이블은 rights_grant의 실제
-- INSERT·UPDATE에만 반응하는 순수 append-only 감사 로그다. 그래서 'parsed'
-- 이벤트와 source_history_id 자기참조가 사라졌다 — "이 승인이 어느 후보에서
-- 왔는지"는 rights_grant.source_candidate_id 하나로 항상 answerable하므로
-- 이벤트마다 따로 연결을 추적할 필요가 없다.
CREATE TABLE rights_grant_history (
    id               bigserial PRIMARY KEY,
    rights_grant_id  bigint NOT NULL,
    contract_id      bigint NOT NULL,
    document_id      bigint NOT NULL,

    event_type       text NOT NULL
                      CHECK (event_type IN ('registered', 'finalized', 'terminated', 'status_changed')),

    -- rights_grant와 동일한 타입의 스냅샷 컬럼 (이벤트 시점 값 그대로)
    -- D-27 — rights_type 한 컬럼이 판정축 2개로 늘었다. span은 스냅샷하지 않는다
    -- — 파생값이라 코드만 있으면 언제든 참조 테이블에서 다시 얻을 수 있다.
    status_at_event   rights_grant_status NOT NULL,
    territory         char(2)          NOT NULL,
    legal_right       text             NOT NULL,
    exploitation_mode text             NOT NULL,
    period            daterange        NOT NULL,
    exclusivity       exclusivity_kind NOT NULL,

    changed_by       text,       -- 세션 GUC(mindex.changed_by)로 앱/트리거가 넘김
    change_reason    text,       -- WAIVER 트리거가 'WAIVER: <reason>'으로 채우기도 함
    snapshot         jsonb,      -- 필요 시 당시 전체 row 스냅샷

    recorded_at      timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (rights_grant_id) REFERENCES rights_grant      (id) ON DELETE CASCADE,
    FOREIGN KEY (contract_id)     REFERENCES contract         (id) ON DELETE CASCADE,
    FOREIGN KEY (document_id)     REFERENCES contract_document(id) ON DELETE CASCADE
);

CREATE INDEX idx_history_grant ON rights_grant_history (rights_grant_id);
CREATE INDEX idx_history_event ON rights_grant_history (event_type);

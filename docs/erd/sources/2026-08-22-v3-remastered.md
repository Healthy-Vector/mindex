# ERD v3 — mindex_remastered

status: `DRAFT` (확정 전, 추가 수정 예정)
date: 2026-08-22
출처: ERD 이미지 판독 — 원본 `.dbml` 미확보

> **판독 문서다.** 원본 DBML을 받기 전까지는 이 문서가 v3의 유일한 기록이지만,
> 이미지에서 옮긴 것이라 오독 가능성이 있다. 아래 "판독 불확실 항목"을 참고하고,
> 원본을 받으면 반드시 대조한다.

---

## 1. 테이블 목록 (21개)

| 그룹 | 테이블 |
|---|---|
| Contracts / Rights | `rights_grant` · `territory_group` · `territory_group_member` · `territory_group_label` · `country_label` |
| IP / Content | `ip` · `ip_alias` · `content_asset` |
| Contracts | `contract` · `contract_history` · `contract_chunk` |
| Rights Taxonomy / Reasons | `legal_right` · `exploitation_mode` · `reason_code` · `constraint_reason_map` |
| Independent / Support | `schema_meta` · `change_log` · `team` |

---

## 2. 테이블 정의

### 2.1 Contracts / Rights

#### `rights_grant` — 권리 레코드 (플랫폼의 심장)

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| FK | `contract_id` | BIGINT |
| FK | `contract_history_id` | BIGINT |
| FK | `content_asset_id` | BIGINT |
| | `lineage_id` | BIGINT |
| | `status` | `rights_grant_status` |
| FK | `territory` | CHAR(2) |
| FK | `legal_right` | TEXT |
| FK | `exploitation_mode` | TEXT |
| | `legal_right_span` | INT4RANGE |
| | `exploitation_mode_span` | INT4RANGE |
| | `period` | DATERANGE |
| | `exclusivity` | `exclusivity_kind` |
| | `evidence` | JSONB |
| | `conditions_raw` | JSONB |
| | `terminated_at` | TIMESTAMPTZ |
| | `terminated_reason` | `terminated_reason_kind` |
| | `termination_note` | TEXT |
| | `created_at` | TIMESTAMPTZ |

**v2 대비 핵심 변화** — `rights_type` 단일 컬럼이 `legal_right` + `exploitation_mode` **두 컬럼으로 분리**됐다.
프로젝트 원칙(두 축을 합치지 않는다)이 스키마 수준에서 지켜진다.

`legal_right_span` / `exploitation_mode_span`은 각 분류 트리의 nested set 구간을 비정규화해 들고 있는 것으로 읽힌다.
이게 있으면 `@>` 연산으로 **상위/하위 권리 포함 관계를 인덱스로 판정**할 수 있다 — R3(권리 위계) 판정의 근거.

#### `territory_group`

| Key | Column | Type |
|---|---|---|
| PK | `code` | TEXT |
| | `note` | TEXT |

#### `territory_group_member`

| Key | Column | Type |
|---|---|---|
| PK/FK | `group_code` | TEXT |
| PK/FK | `country_code` | CHAR(2) |

`ASIA` · `APAC` 같은 계약상 지역 용어를 국가 코드 집합으로 푸는 테이블.

#### `territory_group_label`

| Key | Column | Type |
|---|---|---|
| PK/FK | `group_code` | TEXT |
| PK | `lang` | CHAR(2) |
| | `label` | TEXT |

#### `country_label`

| Key | Column | Type |
|---|---|---|
| PK/FK | `country_code` | CHAR(2) |
| PK | `lang` | CHAR(2) |
| | `label` | TEXT |

### 2.2 IP / Content

#### `ip`

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| | `title` | TEXT |
| | `kind` | TEXT |
| | `created_at` | TIMESTAMPTZ |

#### `ip_alias`

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| FK | `ip_id` | BIGINT |
| | `alias_text` | TEXT |
| | `lang` | CHAR(2) |
| | `alias_type` | TEXT |
| | `created_at` | TIMESTAMPTZ |

**다국어 제목 매칭용.** 같은 작품이 KO `겨울의 신호` / EN `Signal of Winter` / JA `冬の信号`로
나타나는 것을 하나의 `ip`로 묶는다. R1(Content 동일성) 판정의 기반.

#### `content_asset`

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| FK | `ip_id` | BIGINT |
| FK | `parent_id` | BIGINT (자기참조) |
| | `asset_type` | TEXT |
| | `scope_type` | `asset_scope_kind` |
| | `season_no` | INT |
| | `episode_no` | INT |
| | `edition_code` | TEXT |
| | `title` | TEXT |
| | `created_at` | TIMESTAMPTZ |

SERIES → SEASON → EPISODE → EDIT 계층과 OST·Remake 같은 파생 자산을 표현한다.
`parent_id` 자기참조로 계층을, `asset_type`으로 파생 관계를 구분하는 구조로 읽힌다. R2·R9 판정의 기반.

### 2.3 Contracts

#### `contract`

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| | `counterparty` | TEXT |
| | `signed_date` | DATE |
| | `lang` | CHAR(2) |
| | `amount` | NUMERIC |
| | `currency` | CHAR(4) |
| | `status` | `contract_status` |
| FK | `current_history_id` | BIGINT |
| | `created_at` | TIMESTAMPTZ |
| | `updated_at` | TIMESTAMPTZ |

#### `contract_history` — 업로드 문서 버전

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| FK | `contract_id` | BIGINT |
| | `version` | INT |
| | `status` | `contract_history_status` |
| | `file_name` | TEXT |
| | `file_path` | TEXT |
| | `file_hash` | TEXT |
| | `mime_type` | TEXT |
| | `raw_text` | TEXT |
| | `conflict_report` | JSONB |
| | `uploaded_at` | TIMESTAMPTZ |

같은 계약 건에 수정본 PDF를 여러 번 올릴 수 있고, 버전마다 행이 생긴다.
`contract.current_history_id`가 현재 채택본을 가리킨다.

#### `contract_chunk` — 조항 청크 + 벡터

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| FK | `contract_id` | BIGINT |
| FK | `contract_history_id` | BIGINT |
| | `clause_no` | TEXT |
| | `chunk_text` | TEXT |
| | `lang` | CHAR(2) |
| | `page` | INT |
| | `embedding` | VECTOR(1024) |
| | `created_at` | TIMESTAMPTZ |

**v0 대비 `contract_history_id`와 `page`가 추가됐다.** 문서 버전별로 청크가 분리되므로
수정 전/후 계약문서가 검색 결과에 섞이지 않는다. `page`는 Evidence의 `{page, clause, quote}` 형식과 직접 연결된다.

### 2.4 Rights Taxonomy / Reasons

#### `legal_right` — 법적 권리 분류 (계층)

| Key | Column | Type |
|---|---|---|
| PK | `code` | TEXT |
| FK | `parent_code` | TEXT (자기참조) |
| | `name_ko` | TEXT |
| | `lft` | INT |
| | `rgt` | INT |
| | `span` | INT4RANGE |
| | `note` | TEXT |

#### `exploitation_mode` — 이용형태 분류 (계층)

| Key | Column | Type |
|---|---|---|
| PK | `code` | TEXT |
| FK | `parent_code` | TEXT (자기참조) |
| | `name_ko` | TEXT |
| | `lft` | INT |
| | `rgt` | INT |
| | `span` | INT4RANGE |
| | `note` | TEXT |

두 테이블 모두 **nested set(`lft`/`rgt`) + `span` INT4RANGE** 구조다.
"공중송신권이 전송권을 포함하는가", "VOD가 SVOD를 포함하는가" 같은 포함 관계를
문자열 비교가 아니라 **범위 연산**으로 판정한다.

#### `reason_code` — 판정 사유 코드

| Key | Column | Type |
|---|---|---|
| PK | `code` | TEXT |
| | `category` | TEXT |
| | `result_type` | `result_kind` |
| | `rule_code` | TEXT |
| | `severity` | SMALLINT |
| | `is_decision_reason` | BOOLEAN |
| | `name_ko` | TEXT |
| | `template_ko` | TEXT |
| | `template_en` | TEXT |
| | `implemented` | BOOLEAN |
| | `active` | BOOLEAN |

`rule_code`가 R1~R9에, `result_type`이 NORMAL/CONFLICT/REVIEW_REQUIRED/WARNING에 대응하는 것으로 읽힌다.
`implemented`·`active` 플래그로 "설계는 했으나 아직 구현 안 된 규칙"을 구분한다.

#### `constraint_reason_map`

| Key | Column | Type |
|---|---|---|
| PK | `constraint_name` | TEXT |
| FK | `reason_code` | TEXT |

**DB 제약조건 이름 → 사유 코드 매핑.** `EXCLUDE` 위반이 터졌을 때
Postgres 에러의 constraint 이름으로 사용자에게 보여줄 설명을 찾는다.
"DB가 판정한다"는 원칙을 사용자 화면까지 잇는 연결고리.

### 2.5 Independent / Support

#### `schema_meta`

| Key | Column | Type |
|---|---|---|
| PK | `version` | TEXT |
| | `description` | TEXT |
| | `applied_at` | TIMESTAMPTZ |

#### `change_log` — CDC

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| | `table_name` | TEXT |
| | `row_id` | BIGINT |
| | `op` | CHAR(1) |
| | `processed_at` | TIMESTAMPTZ |
| | `attempts` | INT |
| | `last_error` | TEXT |
| | `created_at` | TIMESTAMPTZ |

#### `team`

| Key | Column | Type |
|---|---|---|
| PK | `id` | BIGSERIAL |
| | `name` | TEXT |
| | `pin_hash` | TEXT |
| | `created_at` | TIMESTAMPTZ |

---

## 3. 관계

```
ip ──< ip_alias
ip ──< content_asset ──< content_asset (parent_id 자기참조)

contract ──< contract_history
contract.current_history_id ──> contract_history

contract     ──< contract_chunk
contract_history ──< contract_chunk

contract         ──< rights_grant
contract_history ──< rights_grant
content_asset    ──< rights_grant

rights_grant.territory          ──> country_label.country_code
rights_grant.legal_right        ──> legal_right.code
rights_grant.exploitation_mode  ──> exploitation_mode.code

legal_right.parent_code       ──> legal_right.code        (자기참조)
exploitation_mode.parent_code ──> exploitation_mode.code  (자기참조)

territory_group ──< territory_group_member ──> country_label.country_code
territory_group ──< territory_group_label

reason_code ──< constraint_reason_map
```

## 4. ENUM 타입

이미지에서 컬럼 타입으로만 확인된 것들. 값 목록은 원본 DBML 확보 후 채운다.

| ENUM | 사용처 |
|---|---|
| `rights_grant_status` | `rights_grant.status` |
| `exclusivity_kind` | `rights_grant.exclusivity` |
| `terminated_reason_kind` | `rights_grant.terminated_reason` |
| `contract_status` | `contract.status` |
| `contract_history_status` | `contract_history.status` |
| `asset_scope_kind` | `content_asset.scope_type` |
| `result_kind` | `reason_code.result_type` |

---

## 5. v2 → v3 변화 요약

| 항목 | v2 | v3 | 의미 |
|---|---|---|---|
| 권리 축 | `rights_type` 1개 (SVOD/AVOD/TVOD/TV_LINEAR/THEATRICAL) | `legal_right` + `exploitation_mode` 분리 | **프로젝트 핵심 원칙 준수** |
| 권리 위계 | 없음 (평면 ENUM) | nested set + INT4RANGE | R3·R4 포함관계 판정 가능 |
| 콘텐츠 | `ip` 단일 | `ip` + `content_asset` + `ip_alias` | R1·R2·R9 판정 가능, 다국어 제목 매칭 |
| 문서 버전 | `contract_document` | `contract_history` | 명칭 변경 + `conflict_report` JSONB 추가 |
| 추출 스테이징 | `rights_grant_candidate` → `conflict_result` → `conflict_resolution` | 제거. `rights_grant.status` + `contract_history.conflict_report` | 흐름 단순화 |
| Evidence | `source_page`/`source_clause`/`source_quote` 평면 컬럼 | `evidence` JSONB | 필드별 다중 근거 표현 가능 |
| 사유 코드 | `conflict_code` | `reason_code` + `constraint_reason_map` | DB 제약 위반 → 사용자 설명 연결 |
| 테넌시 | `tenant` UUID + 전 테이블 `tenant_id` | `team` (id/name/pin_hash) | 판독상 `tenant_id` 안 보임 — **확인 필요** |
| 청크 | `document_id` | `contract_history_id` + `page` | 버전별 분리 + 페이지 근거 |

---

## 6. 판독 불확실 항목 — 원본 확보 시 확인할 것

1. **`tenant_id` 부재** — 이미지 어느 테이블에도 `tenant_id`가 보이지 않는다. `team` 테이블이 대체하는지,
   멀티테넌시를 MVP에서 제외한 것인지, 단순히 다이어그램에서 생략된 것인지 확인 필요.
   RLS(`app/security/rls.py`) 설계에 직접 영향을 준다.
2. **`legal_right.code`** — 이미지의 Key 컬럼 렌더링이 뭉개져 PK 여부를 단정하지 못했다.
   `exploitation_mode`와 대칭이므로 `code`가 PK로 추정된다.
3. **`territory_group.code`** — PK 표기가 확인되지 않았다. 추정.
4. **`rights_grant`의 EXCLUDE 제약** — 다이어그램에 제약조건은 표시되지 않는다.
   `constraint_reason_map`이 있다는 것은 제약이 존재한다는 뜻이나, 정의는 확인 필요.
5. **`content_asset.asset_type` vs `scope_type`** — 두 컬럼의 역할 구분이 명시돼 있지 않다.
6. **ENUM 값 목록** — 전부 미확인.
7. **`lineage_id`** — `rights_grant`의 용도 미상. 권리 승계·재허락 체인 추적용으로 추정.

---

## 7. OCR·임베딩 파이프라인이 닿는 지점

이 파이프라인이 쓰기(write)하는 테이블은 **둘뿐**이다.

| 테이블 | 파이프라인이 채우는 컬럼 |
|---|---|
| `contract_history` | `file_name` · `file_path` · `file_hash` · `mime_type` · `raw_text` · `status` |
| `contract_chunk` | `contract_id` · `contract_history_id` · `clause_no` · `chunk_text` · `lang` · `page` · `embedding` |

`rights_grant`를 비롯한 나머지는 후속 LLM 추출·정규화·판정 단계의 영역이다.

`embedding`이 `VECTOR(1024)`이므로 **multilingual-e5-large(1024차원)**가 그대로 맞는다.
`page`가 생겼으므로 청크마다 페이지 번호를 반드시 채워야 하고, 이것이 Evidence의
`{page, clause, quote}`로 이어진다.

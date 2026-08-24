# Mindex API 개발 지시서 v1.0

**대상** — P4 백엔드 API 16개 + 프론트 연동 규약
**스택** — Python 3.12 / FastAPI / SQLAlchemy 2.x / PostgreSQL 17 (`psycopg` 3)
**읽는 순서** — 이 문서 → `mindex-API설계서.md`(필드 사전) → `mindex-API-프로세스배치.html`(호출 위치)

이 문서는 **무엇을 어떻게 만들지**를 정합니다. 각 엔드포인트의 필드 목록과 예시 JSON은 API 설계서에 있으니 여기서 반복하지 않습니다. 두 문서가 어긋나면 **이 문서가 우선**입니다.

---

## 0. 이 시스템이 하는 일 한 문장

> 데이터가 저장되는 단 하나의 경로에 제약조건을 두어, 서로 배타적인 조건이 애초에 같은 테이블에 공존할 수 없게 만든다.

구현할 때 이 문장이 기준입니다. **판정을 애플리케이션 코드로 옮기지 마십시오.** 조회로 겹침을 계산한 뒤 INSERT 하면 그 사이에 다른 트랜잭션이 끼어들 수 있고(TOCTOU), 판정 로직이 두 벌이 되어 서로 어긋납니다.

---

## 1. 전제와 경계

### 1.1 담당 경계

| 범위 | 담당 | 이 문서에서 |
|---|---|---|
| 2번 `POST /extract`, 3번 `GET /extract/{tmpid}` | **P1** (쿠버네티스 추출 서빙) | 계약(contract)만 명시. 구현하지 않음 |
| 1, 4~16번 | **P4** | 전부 구현 대상 |
| 프론트 화면 | P5 | §9 연동 규약만 |

P4는 `staging` 스키마를 **읽기만** 합니다. 쓰는 것은 두 군데뿐입니다 — 6번 확정 저장에서 임시 행을 **삭제**할 때, 그리고 아무것도 아닙니다. 그 외 `staging` INSERT/UPDATE 는 전부 P1 소관입니다.

### 1.2 DB 접속

`master` / `staging` 은 **같은 인스턴스 안의 두 스키마**입니다. 접속을 나누지 마십시오. 한 커넥션에서 두 스키마를 함께 쓰는 트랜잭션이 6번 엔드포인트의 전제입니다.

```
search_path = master, public
```

`staging` 은 항상 스키마명을 명시해 접근합니다(`staging.extract_job`).

### 1.3 필요한 확장

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- EXCLUDE 에서 = 비교를 gist 로 쓰기 위해 필수
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector, contract_chunk.embedding
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid, PIN 해시
```

`btree_gist` 가 없으면 §3.2 의 EXCLUDE 제약이 생성되지 않습니다. 마이그레이션 첫 파일에 넣으십시오.

---

## 2. 프로젝트 구조

```
app/
  main.py                  FastAPI 인스턴스 · 예외 핸들러 등록
  config.py                환경변수 (pydantic-settings)
  db.py                    engine · SessionLocal · get_db 의존성
  deps.py                  require_session (PIN 세션 검사)
  errors.py                AppError 계층 · 공통 에러 응답 변환
  models/                  SQLAlchemy ORM (스키마당 파일 분리)
    master.py
    staging.py
  schemas/                 Pydantic v2 요청·응답 모델
    auth.py contracts.py rights.py ips.py search.py refs.py
  routers/
    auth.py                1
    contracts.py           5 6 7 8 9 11
    rights.py              10
    ips.py                 4 12 13 14
    search.py              15
    refs.py                16
  services/
    conflict.py            검증·확정의 공용 로직 (핵심)
    territory.py           지역 그룹 → 국가 전개
    session_store.py       PIN 세션
migrations/                Alembic
tests/
```

**`services/conflict.py` 가 이 프로젝트의 심장입니다.** 5번과 6번은 이 모듈의 같은 함수를 호출하고, 커밋 여부만 다릅니다. 두 라우터에 판정 코드를 각각 쓰지 마십시오.

---

## 3. 스키마

### 3.1 master — 그대로 만드십시오

```sql
CREATE SCHEMA IF NOT EXISTS master;

CREATE TABLE master.team (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  pin_hash    text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE master.ip (
  id          bigserial PRIMARY KEY,
  team_id     uuid NOT NULL REFERENCES master.team(id),
  title       text NOT NULL,
  kind        text NOT NULL,          -- TV_OTT_SERIES / FILM / ANIMATION / MOBILE_APP / GAME_ENGINE / RELATED_ASSET
  activity    ip_activity_kind NOT NULL DEFAULT 'active',   -- ENUM('active'|'deactive'), 프런트 필터 전용
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE master.ip_alias (
  id          bigserial PRIMARY KEY,
  team_id     uuid NOT NULL REFERENCES master.team(id),
  ip_id       bigint NOT NULL REFERENCES master.ip(id) ON DELETE CASCADE,
  alias_text  text NOT NULL,
  lang        char(2) NOT NULL,
  alias_type  text NOT NULL,          -- OFFICIAL / ABBR / ROMANIZED / MISSPELL
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ip_alias_norm ON master.ip_alias (lower(alias_text));

-- 작품 내부 범위만 담당. OST·리메이크는 여기가 아니라 별도 ip 행
CREATE TABLE master.content_asset (
  id            bigserial PRIMARY KEY,
  team_id       uuid NOT NULL REFERENCES master.team(id),
  ip_id         bigint NOT NULL REFERENCES master.ip(id),
  parent_id     bigint REFERENCES master.content_asset(id),
  scope_type    text NOT NULL,        -- SERIES_ALL / SEASON / EPISODE / EDITION
  season_no     int,
  episode_no    int,
  edition_code  text,
  title         text
);

-- 작품 간 파생 관계. OST·리메이크·스핀오프가 여기로 들어온다
CREATE TABLE master.ip_relation (
  source_ip_id   bigint NOT NULL REFERENCES master.ip(id),
  derived_ip_id  bigint NOT NULL REFERENCES master.ip(id),
  relation_type  text   NOT NULL,     -- OST / REMAKE / SPINOFF
  PRIMARY KEY (source_ip_id, derived_ip_id, relation_type)
);

CREATE TABLE master.contract (
  id                  bigserial PRIMARY KEY,
  team_id             uuid NOT NULL REFERENCES master.team(id),
  title               text NOT NULL,
  contract_type       text,
  counterparty        text NOT NULL,
  signed_date         date,
  lang                char(2),
  amount              numeric,
  currency            char(3),
  current_history_id  bigint,                     -- FK 는 아래에서 뒤늦게 건다 (순환 참조)
  source_tmpid        uuid UNIQUE,                -- 중복 확정 차단
  status              text NOT NULL DEFAULT 'draft',   -- draft / signed / cancelled
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE master.contract_history (
  id            bigserial PRIMARY KEY,
  team_id       uuid NOT NULL REFERENCES master.team(id),
  contract_id   bigint NOT NULL REFERENCES master.contract(id),
  version       text NOT NULL,        -- 'v1','v2',… 또는 'final'
  status        text NOT NULL,        -- applied / conflicted
  conflict_report jsonb,
  file_path     text,
  raw_text      text,
  title         text,
  counterparty  text,
  signed_date   date,
  lang          char(2),
  amount        numeric,
  currency      char(3),
  parsed_at     timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contract_id, version)
);
ALTER TABLE master.contract
  ADD CONSTRAINT fk_contract_current_history
  FOREIGN KEY (current_history_id) REFERENCES master.contract_history(id);

CREATE TABLE master.contract_chunk (
  id                   bigserial PRIMARY KEY,
  team_id              uuid NOT NULL REFERENCES master.team(id),
  contract_history_id  bigint NOT NULL REFERENCES master.contract_history(id) ON DELETE CASCADE,
  clause_no            text,
  chunk_text           text NOT NULL,
  lang                 char(2),
  page                 int,
  embedding            vector(1024),
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_chunk_hnsw ON master.contract_chunk
  USING hnsw (embedding vector_cosine_ops);

-- INSERT 전용. UPDATE 는 status/terminated_* 갱신에만 허용된다 (§4.4)
CREATE TABLE master.rights_grant (
  id                   bigserial PRIMARY KEY,
  team_id              uuid NOT NULL REFERENCES master.team(id),
  contract_id          bigint NOT NULL REFERENCES master.contract(id),
  contract_history_id  bigint NOT NULL REFERENCES master.contract_history(id),
  content_asset_id     bigint NOT NULL REFERENCES master.content_asset(id),
  territory            char(2) NOT NULL REFERENCES master.country(code),
  rights_type          text    NOT NULL REFERENCES master.rights_type_ref(code),
  period               daterange NOT NULL,
  exclusivity          text NOT NULL,   -- exclusive / sole / non_exclusive
  status               text NOT NULL,   -- active / conflicted / terminated
  lineage_id           bigint,          -- 같은 권리의 세대 묶음표. conflicted 행은 NULL
  conditions_raw       jsonb,
  confidence           numeric(3,2),
  evidence             jsonb,
  created_at           timestamptz NOT NULL DEFAULT now(),
  terminated_at        timestamptz,
  terminated_reason    text             -- superseded / cancelled / expired / waiver
);
CREATE INDEX ix_rg_lineage  ON master.rights_grant (lineage_id, created_at);
CREATE INDEX ix_rg_contract ON master.rights_grant (contract_id, status);
```

참조 어휘 테이블(`country`, `country_label`, `territory_group`, `territory_group_label`, `territory_group_country`, `rights_type_ref`, `rights_type_label`, `conflict_code`, `conflict_code_template`)은 ERD v13 그대로 만드십시오. 코드 컬럼이 PK, 라벨은 `(code, lang)` 복합 PK 의 별도 테이블입니다. **라벨을 코드 테이블에 컬럼으로 넣지 마십시오** — 언어 추가가 스키마 변경이 됩니다.

### 3.2 EXCLUDE 제약 — 시스템의 핵심

```sql
ALTER TABLE master.rights_grant
ADD CONSTRAINT no_exclusive_overlap
EXCLUDE USING gist (
  contract_id      WITH <>,
  content_asset_id WITH =,
  territory        WITH =,
  rights_type      WITH =,
  period           WITH &&
)
WHERE (exclusivity <> 'non_exclusive' AND status = 'active');
```

읽는 법 — *다른 계약이면서 · 같은 권리대상 · 같은 국가 · 같은 권리유형 · 기간이 겹치는* 행 두 개는 공존할 수 없다. 단, **비독점이거나 active 가 아닌 행은 이 규칙 밖**입니다.

각 요소가 왜 그 자리인지:

| 요소 | 이유 |
|---|---|
| `contract_id WITH <>` | 같은 계약 안에서 여러 국가·기간을 나눠 담을 때 자기 자신과 충돌하지 않게 함 |
| `territory WITH =` | 국가별로 한 행. 배열이나 그룹 코드로 넣으면 EXCLUDE 가 작동하지 않음 |
| `period WITH &&` | `daterange` 겹침. 끝 경계는 `[)` (상한 배타) 로 통일 |
| `WHERE ... 'non_exclusive'` | 비독점은 몇 건이든 공존 가능 |
| `WHERE status = 'active'` | 종료·충돌 기록이 새 계약을 막지 않게 함 |
| `team_id` **없음** | 회사·팀이 다르다고 이중 계약이 허용되는 것은 아님. 판정 축이 아님 |

**`period` 는 항상 `[)` 로 만드십시오.** `daterange(start, end, '[]')` 를 쓰면 하루 겹침이 오탐으로 잡힙니다. 화면의 종료일이 포함 개념(2029-06-30까지 유효)이므로 저장 시 `daterange(start, end + 1일, '[)')` 로 변환하고, 응답할 때 다시 하루를 빼서 내려줍니다. **이 변환은 한 곳(`services/territory.py` 또는 전용 헬퍼)에만 두십시오.**

### 3.3 staging — P1 이 만들지만 P4 가 읽는다

```sql
CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE staging.pdf_blob (
  tmpid       uuid PRIMARY KEY,
  data        bytea NOT NULL,
  filename    text,
  byte_size   int,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE staging.extract_job (
  tmpid        uuid PRIMARY KEY REFERENCES staging.pdf_blob(tmpid) ON DELETE CASCADE,
  status       text NOT NULL,        -- QUEUED / RUNNING / DONE / FAILED  (대문자)
  stage        text,                 -- OCR / LLM
  lease_until  timestamptz,
  attempts     int NOT NULL DEFAULT 0,
  reason       text,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_job_queue ON staging.extract_job (status, created_at);

CREATE TABLE staging.extract_result (
  tmpid       uuid PRIMARY KEY REFERENCES staging.pdf_blob(tmpid) ON DELETE CASCADE,
  payload     jsonb NOT NULL,
  confidence  numeric(4,3),
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

`pdf_blob` 한 행을 지우면 CASCADE 로 나머지 둘이 함께 사라집니다. **6번 확정 저장의 정리 단계는 `DELETE FROM staging.pdf_blob WHERE tmpid = :tmpid` 한 줄이면 충분합니다.** 세 테이블을 각각 지우지 마십시오.

완료 표시 컬럼(`consumed_at` 같은 것)은 두지 않습니다. 확정과 정리가 같은 트랜잭션이라 표시해 둘 시점 자체가 없습니다.

### 3.4 상태 어휘 — 소문자 고정

| 테이블 | 컬럼 | 값 |
|---|---|---|
| `contract` | `status` | `draft` / `signed` / `cancelled` |
| `contract_history` | `version` | `v1`, `v2`, … / `final` |
| `contract_history` | `status` | `applied` / `conflicted` |
| `rights_grant` | `status` | `active` / `conflicted` / `terminated` |
| `rights_grant` | `exclusivity` | `exclusive` / `sole` / `non_exclusive` |
| `rights_grant` | `terminated_reason` | `superseded` / `cancelled` / `expired` / `waiver` |
| `staging.extract_job` | `status` | `QUEUED` / `RUNNING` / `DONE` / `FAILED` **(대문자)** |

`extract_job.status` 만 대문자입니다. P1 이 정한 값이고 그대로 프론트로 넘어가므로 소문자로 바꾸지 마십시오.

**협의 중인 계약의 권리도 `active` 입니다.** `draft` 단계라도 다른 계약의 충돌 판정 대상이 되어야 하기 때문입니다. 초안 여부는 `contract.status` 로 구분합니다. `rights_grant` 에 `draft` 를 만들지 마십시오.

---

## 4. 공통 규약

### 4.1 네이밍

- DB · SQL — `snake_case`
- API 요청/응답 JSON — `camelCase`
- 변환은 Pydantic 모델에서 `alias_generator=to_camel`, `populate_by_name=True` 로 한 번만 처리합니다. 라우터에서 손으로 딕셔너리를 만들지 마십시오.

### 4.2 에러 응답

성공이 아닌 모든 응답은 이 형태입니다.

```json
{ "error": { "code": "VALIDATION_FAILED", "message": "period 형식이 올바르지 않습니다",
             "details": { "field": "rights[0].period" } } }
```

`errors.py` 에 `AppError(code, message, http_status, details)` 하나를 두고, `main.py` 에서 단일 핸들러로 변환합니다. FastAPI 기본 `HTTPException` 을 그대로 노출하지 마십시오 — 응답 형태가 두 가지가 됩니다. `RequestValidationError` 도 같은 핸들러로 흡수해 `VALIDATION_FAILED` 로 바꿉니다.

| 코드 | HTTP | 상황 |
|---|---|---|
| `VALIDATION_FAILED` | 400 | 요청 형식 오류 |
| `INVALID_PIN` | 401 | PIN 불일치 |
| `SESSION_EXPIRED` | 401 | 세션 없음·만료 |
| `NOT_FOUND` | 404 | 대상 없음 |
| `NO_SOURCE_FILE` | 404 | 원본 PDF 없음 |
| `ALREADY_CONFIRMED` | 409 | `source_tmpid` 재사용 |
| `IP_DUPLICATE` | 409 | 같은 정규화 키의 IP 존재 |
| `ALREADY_CANCELLED` | 422 | 이미 종료된 계약 |
| `EXTRACT_NOT_READY` | 422 | `tmpid` 가 아직 `DONE` 이 아님 |

### 4.3 충돌은 에러가 아니다

권리 충돌은 **정상 응답**입니다. 5번은 `200`, 6번은 `201` 로 주고 본문에 충돌 내역을 담습니다. HTTP 오류로 주면 프론트가 "요청이 실패한 건지, 충돌이 난 건지" 구분하지 못합니다. 이 규칙을 어기는 구현이 가장 흔한 실수입니다.

### 4.4 UPDATE 금지 범위

`rights_grant` 는 append-only 입니다. 허용되는 UPDATE 는 **`status`, `terminated_at`, `terminated_reason` 세 컬럼뿐**이고, 그것도 `active → terminated` 방향만입니다. 조건 컬럼(`period`, `territory`, `exclusivity`, …)을 UPDATE 하면 이력이 사라집니다. 조건이 바뀌면 옛 행을 `terminated` 로 내리고 새 행을 INSERT 하십시오.

`contract_history` 도 append-only 입니다. 업로드 한 건 = 행 한 개.

### 4.5 시간·통화

- 모든 timestamp 는 `timestamptz`, 응답은 ISO8601 + 오프셋(`+09:00`).
- `date` 는 시간대 없이 그대로.
- `currency` 는 저장만 하고 환산하지 않습니다. 통화가 다른 금액을 합산하는 로직을 만들지 마십시오.

### 4.6 페이지네이션

`page`(1부터) / `size`(기본 20, 최대 100). 응답에 `total`, `page`, `size` 를 항상 포함합니다. 커서 방식은 쓰지 않습니다.

### 4.7 PIN 세션 (1번 `POST /auth/pin`)

- `master.team.pin_hash` 는 bcrypt. 평문 비교 금지.
- 세션 토큰은 서명된 JWT(HS256, 만료 15분). **MVP 는 JWT** — 인스턴스가 늘어도 공유 스토리지가 필요 없습니다.
- **Sliding expiration** — 별도 연장 API 는 두지 않습니다. Bearer 인증이 필요한 기존 API(8·9·10·11)가 호출될 때 `require_session`(인증 미들웨어)이 만료 시각을 **요청 시각 + 15분**으로 자동 연장합니다. 과도한 재발급/DB 갱신을 막기 위해 실제 갱신은 **세션당 최대 1분에 한 번**(토큰 `iat` 스로틀)만 수행합니다. 갱신 시 새 토큰을 `X-Session-Token` / `X-Session-Expires` 응답 헤더로 내려줍니다 — 프론트는 이 헤더가 오면 저장 토큰을 교체합니다.
- `deps.require_session` 을 붙이는 엔드포인트는 **8, 9, 10, 11 네 개뿐**입니다. 1, 4, 5, 6, 7, 12~16 은 세션 없이 동작합니다.

> PIN 실패 횟수 제한은 MVP 범위 밖입니다. 넣지 마십시오.

---

## 5. 핵심 로직 — `services/conflict.py`

5번과 6번이 공유하는 부분입니다. **여기만 정확하면 나머지는 CRUD 입니다.**

### 5.1 지역 그룹 전개

요청의 `rights[].territories` 는 국가 코드 배열입니다. 그룹 코드(`APAC`, `WORLDWIDE`)가 섞여 들어오면 `territory_group_country` 로 펼칩니다. 펼친 뒤 중복을 제거합니다.

```
rights 1건 × territories N개  →  rights_grant N행
```

`checkedRows` 는 이 전개 후의 행 수입니다.

### 5.2 후보 행 만들기

```python
def build_rows(payload, contract_id, history_id, team_id) -> list[dict]:
    rows = []
    for r in payload.rights:
        for cc in expand_territories(r.territories):
            rows.append(dict(
                team_id=team_id, contract_id=contract_id,
                contract_history_id=history_id,
                content_asset_id=r.content_asset_id,
                territory=cc, rights_type=r.rights_type,
                period=to_daterange(r.period),      # [) 변환은 여기 한 곳
                exclusivity=r.exclusivity,
                status="active",
                conditions_raw=r.conditions_raw, evidence=r.evidence,
            ))
    return rows
```

### 5.3 넣어보고 되돌리기

```python
from psycopg import errors as pgerr
from sqlalchemy.exc import IntegrityError

def try_insert(session, rows) -> bool:
    """EXCLUDE 통과하면 True(행은 그대로 남음), 걸리면 False(SAVEPOINT 까지 되돌림)."""
    sp = session.begin_nested()          # = SAVEPOINT
    try:
        session.execute(insert(RightsGrant), rows)
        session.flush()                  # 여기서 EXCLUDE 가 터진다
    except IntegrityError as ex:
        if not isinstance(ex.orig, pgerr.ExclusionViolation):
            raise                        # 다른 무결성 오류는 그대로 올린다
        sp.rollback()
        return False
    return True                          # 커밋하지 않음 — 호출자가 결정
```

주의할 점 셋:

1. **`flush()` 를 반드시 부르십시오.** 부르지 않으면 위반이 커밋 시점에 터지고, 그때는 SAVEPOINT 로 되돌릴 수 없습니다.
2. **`ExclusionViolation` 만 잡으십시오.** `IntegrityError` 를 통째로 잡으면 FK 오타가 "충돌"로 둔갑합니다.
3. **`sp.rollback()` 이후에도 바깥 트랜잭션은 살아 있습니다.** 이것이 SAVEPOINT 를 쓰는 이유 전부입니다.

### 5.4 상대 찾기

EXCLUDE 오류 메시지의 `DETAIL` 을 파싱하지 마십시오. 문구가 버전에 따라 다르고 여러 건이 겹쳤을 때 하나만 알려줍니다. 되돌린 뒤 같은 조건으로 조회하십시오.

```sql
SELECT rg.id            AS rights_grant_id,
       rg.contract_id, rg.period, rg.exclusivity, rg.evidence,
       c.title          AS contract_title,
       c.counterparty,
       (rg.period * :period) AS overlap
FROM   master.rights_grant rg
JOIN   master.contract     c ON c.id = rg.contract_id
WHERE  rg.status = 'active'
  AND  rg.exclusivity <> 'non_exclusive'
  AND  rg.content_asset_id = :content_asset_id
  AND  rg.territory        = :territory
  AND  rg.rights_type      = :rights_type
  AND  rg.period          && :period
  AND  rg.contract_id     <> :contract_id;
```

`period * :period` 가 겹친 구간입니다(교집합 연산자). `days` 는 `upper(overlap) - lower(overlap)`.

`severity` 는 두 행의 `exclusivity` 조합으로 만듭니다.

| 이번 × 상대 | severity |
|---|---|
| exclusive × exclusive | `EXCLUSIVE_VS_EXCLUSIVE` |
| exclusive × sole (양방향) | `EXCLUSIVE_VS_SOLE` |
| sole × sole | `SOLE_VS_SOLE` |

### 5.5 5번 `POST /contracts/verify` — 검증

```
BEGIN
  contract_id 결정 (revision·final 이면 기존 id, new 면 0 같은 임시값)
  rows = build_rows(...)
  ok = try_insert(rows)
  conflicts = [] if ok else find_conflicts(rows)
  ROLLBACK        ← 통과했든 걸렸든 무조건. 커밋하지 않는다
RETURN 200 { hasConflict: not ok, checkedRows: len(rows), conflicts }
```

- `mode=new` 는 아직 `contract` 행이 없습니다. **`contract` 를 만들지 마십시오.** `contract_id` 자리에는 실제로 존재하지 않아도 되는 값을 넣되, FK 때문에 INSERT 가 막히면 트랜잭션 전체를 되돌리는 방식으로 처리합니다. 가장 단순한 구현은 **바깥 트랜잭션 안에서 `contract` 를 임시로 INSERT 한 뒤 마지막에 전부 ROLLBACK** 하는 것입니다. 어차피 통째로 되돌리므로 데이터는 남지 않습니다.
- 시퀀스 값은 되돌아가지 않습니다. `contract.id`, `rights_grant.id` 에 구멍이 생기는 것은 **정상**이며 고치려 들지 마십시오.
- 여기서 통과해도 6번에서 다시 걸릴 수 있습니다. 그 사이 다른 사용자가 확정할 수 있기 때문이며, 그래서 6번에도 같은 검사가 남아 있습니다. 화면에 "저장 시 다시 검사됩니다"를 표시할 필요는 없습니다.

### 5.6 6번 `POST /contracts` — 확정 저장

**전체가 한 트랜잭션입니다.** 순서를 바꾸지 마십시오.

```
BEGIN
 1. SELECT id FROM master.contract WHERE source_tmpid = :tmpid
      → 있으면 409 ALREADY_CONFIRMED + 첫 결과(contractId, contractHistoryId) 반환하고 종료
 2. contract  : mode=new 면 INSERT(status='draft', source_tmpid=:tmpid)
                mode=revision/final 이면 기존 행 사용
    contract_history : INSERT (version 계산, status 는 4단계 후에 확정)
    contract_chunk   : INSERT (임베딩은 있으면 저장, 없으면 나중 배치)
      ── 여기까지는 되돌리지 않는 구간 ──
 3. SAVEPOINT sp
      같은 계약의 이전 세대 active 권리를 terminated 로 내림
        (terminated_reason='superseded', terminated_at=now())
      이번 rows 일괄 INSERT
 4. 통과 → 그대로 유지. 다시 INSERT 하지 않는다
    위반 → ROLLBACK TO sp
           find_conflicts()
           같은 rows 를 status='conflicted', lineage_id=NULL 로 재INSERT
           contract_history.status='conflicted', conflict_report=<충돌 JSON>
           contract.current_history_id 는 갱신하지 않는다
 5. DELETE FROM staging.pdf_blob WHERE tmpid = :tmpid    -- CASCADE
 6. COMMIT      ← 성공이든 충돌이든 항상 커밋
```

`lineage_id` 채우기 — INSERT 직후 `id` 를 그대로 씁니다.

```sql
UPDATE master.rights_grant SET lineage_id = id
 WHERE id = ANY(:new_ids) AND lineage_id IS NULL;
```

이전 세대를 이어받는 경우(같은 `content_asset_id` + `territory` + `rights_type` 의 `terminated` 직전 행이 있으면)는 그 행의 `lineage_id` 를 물려받습니다. `lineage_id` 는 포인터가 아니라 **묶음표**입니다. 중간 세대가 사라져도 나머지가 흩어지지 않습니다.

`conflicted` 행은 `lineage_id = NULL` 입니다. 확정되지 않은 조건이므로 이력 계보에 넣지 않습니다.

`version` 계산 — `mode=final` 이면 `'final'`, 아니면 `SELECT count(*) FROM contract_history WHERE contract_id=:id AND version <> 'final'` 에 1을 더해 `'v{n}'`.

결과 조합:

| 상황 | `contract.status` | `history.status` | `rights_grant.status` |
|---|---|---|---|
| `final` · 충돌 없음 | `signed` | `applied` | `active` |
| `final` · 충돌 | `draft` 유지 | `conflicted` | `conflicted` |
| `new`·`revision` · 충돌 없음 | `draft` | `applied` | `active` |
| `new`·`revision` · 충돌 | `draft` | `conflicted` | `conflicted` |

**부분 승인은 발생하지 않습니다.** 이번 PDF 의 권리를 하나의 SAVEPOINT 안에서 한꺼번에 넣으므로, 한 건만 걸려도 전부 되돌아간 뒤 전부 `conflicted` 로 다시 들어갑니다. 권리별로 SAVEPOINT 를 나누지 마십시오 — 계약서 절반만 유효한 상태는 업무적으로 정의되지 않습니다.

### 5.7 11번 `POST /contracts/{id}/cancel` — 계약 종료

```sql
BEGIN;
  UPDATE master.contract SET status='cancelled', updated_at=now() WHERE id=:id AND status<>'cancelled';
  -- 0행이면 422 ALREADY_CANCELLED

  UPDATE master.rights_grant
     SET status='terminated', terminated_at=now(), terminated_reason=:reason
   WHERE contract_id=:id AND status='active';
  -- 영향 행 수가 terminatedRights
COMMIT;
```

**두 번째 UPDATE 가 이 엔드포인트의 존재 이유입니다.** 상태만 바꾸고 권리를 두면 끝난 계약이 EXCLUDE 인덱스에 남아 다른 계약을 계속 막습니다. 종료는 PDF 업로드가 아니므로 `contract_history` 행을 만들지 마십시오.

---

## 6. 조회 엔드포인트에서 놓치기 쉬운 것

### 7번 `GET /contracts`

두 종류의 행이 한 목록에 섞입니다.

- `kind="contract"` — `master.contract` 기반
- `kind="processing"` — `staging.extract_job` 에서 `status IN ('QUEUED','RUNNING','FAILED')` 인 건

`includeProcessing=false` 면 뒤쪽을 뺍니다. 두 소스를 SQL `UNION` 으로 억지로 합치지 말고, 각각 조회한 뒤 애플리케이션에서 `created_at` 역순 병합하십시오. 컬럼이 전혀 달라 UNION 하면 NULL 범벅이 됩니다.

`displayState` / `daysToExpiry` 는 **저장하지 않고 계산**합니다.

| 조건 | `displayState` |
|---|---|
| `today < lower(period)` | `BEFORE_TERM` |
| 기간 내 · 종료까지 30일 초과 | `IN_TERM` |
| 기간 내 · 종료까지 30일 이하 | `EXPIRING` |
| `today >= upper(period)` | `EXPIRED` |

기준 `period` 는 그 계약의 `active` 권리 중 최소 시작 ~ 최대 종료입니다. 만료 상태를 컬럼으로 두면 배치로 계속 갱신해야 하고 실제와 어긋납니다.

### 8번 `GET /contracts/{id}`

- 요청 하나로 사이드바 네 개 카드와 버전 이력을 **모두** 채웁니다. 나누지 마십시오.
- **정상 계약과 충돌 계약의 응답 형태가 같습니다.** 충돌 건도 조건이 `rights_grant` 에 `conflicted` 로 있어 같은 경로로 읽힙니다. `if hasConflict` 로 다른 쿼리를 타지 마십시오.
- `rights[]` 는 기본적으로 `active` + `conflicted` 를 내려주고 `terminated` 는 제외합니다. 과거 세대는 10번에서 봅니다.
- `authority` 객체는 **전 필드 `null` 로 고정**해 내려보내십시오. 스키마 미확정이지만 화면에 카드가 있어 키가 없으면 프론트가 깨집니다.
- `amount` / `currency` / `title` 은 `current_history_id` 가 가리키는 히스토리 행 기준입니다. `contract` 쪽 값은 캐시로 보고 히스토리를 정본으로 쓰십시오.

### 9번 `GET /contracts/{id}/file`

`contract_history.file_path` 의 원본을 스트리밍합니다. `staging.pdf_blob` 은 확정 시점에 이미 지워졌으므로 여기서 읽지 마십시오. `StreamingResponse` + `Content-Disposition` 으로 처리하고, 파일 전체를 메모리에 올리지 마십시오.

### 10번 `GET /rights/{lineageId}/history`

`lineage_id` 로 묶인 행을 `created_at` 오름차순. `changedFields` 는 **서버가 직전 세대와 비교해 계산**합니다. 비교 대상은 `territory`, `rights_type`, `period.start`, `period.end`, `exclusivity` 다섯 개. 프론트에 계산을 넘기지 마십시오.

### 12·13·14번 IP 관리 — `GET /ips` · `POST /ips` · `PATCH /ips/{id}`

- **삭제 엔드포인트를 만들지 마십시오.** 이미 등록된 계약이 참조하고 있습니다. `activity='deactive'` 로 감춥니다(14번 PATCH 의 `activity` 필드로 변경).
- 13번 중복 판정은 정규화 키 — `lower(trim(title))` 에서 공백·구두점 제거. 걸리면 `409 IP_DUPLICATE` + 기존 `ipId`.
- 13번은 진입 경로가 둘(IP 관리 화면, 업로드 중 즉석 등록)이지만 **엔드포인트는 하나**입니다. 분기하지 마십시오.
- 14번의 `aliases` 는 **전체 교체**입니다. 부분 병합이 아닙니다.
- 4번 `GET /ips/match` 는 `ip.title` 과 `ip_alias.alias_text` 를 함께 검색하고, 응답에 `assets`(내부 범위)와 `relations`(OST·리메이크 등 별도 IP)를 함께 실어 보냅니다. 요청을 나누면 드롭다운이 한 박자 늦게 채워집니다.

### 15번 `POST /search`

순서를 지키십시오.

1. `query` 에서 지역·기간·권리유형·독점여부 추출 → `interpreted`
2. `filters`(사용자 지정)가 있으면 **그쪽이 우선**
3. `rights_grant` 를 SQL 로 좁혀 후보 `contract_id` 집합을 얻음
4. 그 집합 안에서만 `contract_chunk.embedding` 코사인 유사도로 랭킹

**벡터 검색을 먼저 하고 필터링하지 마십시오.** 후보가 좁혀지지 않아 느리고, 조건에 안 맞는 계약이 상위에 올라옵니다.

`interpreted` 를 응답에 그대로 실어야 사용자가 "시스템이 내 질문을 이렇게 이해했다"를 보고 필터를 고칠 수 있습니다.

### 16번 `GET /refs`

`types` 로 필요한 것만 골라 받습니다. `territoryGroup` 에는 `countries[]` 를 반드시 포함하십시오 — 사용자가 `APAC` 을 고르면 화면에서 즉시 국가 단위로 펼쳐야 하고, 저장 시에도 국가마다 한 행이 되기 때문입니다.

응답은 캐시 가능(`Cache-Control: max-age=3600`).

---

## 7. 구현 순서

각 단계가 끝날 때마다 동작하는 상태여야 합니다.

| 단계 | 내용 | 끝났다고 볼 수 있는 기준 |
|---|---|---|
| M1 | 마이그레이션 · 확장 · 참조 어휘 시드 | `no_exclusive_overlap` 제약이 실제로 생성됨 |
| M2 | 16번 `/refs`, 12·13·14번 IP CRUD | IP 를 만들고 목록에서 보임 |
| M3 | 4번 `/ips/match` | 별칭으로 검색됨 |
| M4 | **5번 `/contracts/verify`** | 겹치는 두 건을 넣으면 `hasConflict=true`, DB에 행이 남지 않음 |
| M5 | **6번 `/contracts`** | 충돌 없음·충돌 두 경로 모두 커밋되고 `staging` 이 비워짐 |
| M6 | 7·8번 목록·상세 | 충돌 건과 정상 건이 같은 형태로 열림 |
| M7 | 1번 PIN, 9·10·11번 | 세션 없이 8번 호출 시 401 |
| M8 | 15번 검색 | SQL 필터 → 벡터 랭킹 순서 확인 |

M4·M5 가 전체 일정의 절반입니다. 여기를 먼저 끝내고 나머지를 붙이십시오.

---

## 8. 수용 기준 (테스트로 만드십시오)

### 8.1 EXCLUDE 제약 자체

| # | 시나리오 | 기대 |
|---|---|---|
| E1 | 같은 IP·JP·SVOD·기간 겹침, 둘 다 `exclusive`, **다른 계약** | 두 번째 INSERT 실패 |
| E2 | 위와 같되 둘 다 `non_exclusive` | 둘 다 성공 |
| E3 | 위와 같되 상대가 `terminated` | 성공 |
| E4 | 같은 계약 안에서 JP·SG 두 행 | 성공 (`contract_id WITH <>`) |
| E5 | 기간이 하루도 안 겹침 (`~06-30` / `07-01~`) | 성공 (`[)` 변환 확인) |
| E6 | 국가만 다름 (JP / KR) | 성공 |
| E7 | `exclusive` × `sole` 겹침 | 실패 |

### 8.2 API 동작

| # | 시나리오 | 기대 |
|---|---|---|
| A1 | 5번 호출 후 `rights_grant` 행 수 | 호출 전과 동일 |
| A2 | 5번 충돌 응답 | `200`, `hasConflict=true`, `conflicts[0].existing.rightsGrantId` 존재 |
| A3 | 6번 충돌 응답 | `201`, `historyStatus=conflicted`, `rights_grant` 에 `conflicted` 행 존재 |
| A4 | 6번 충돌 후 `contract.current_history_id` | 갱신되지 않음 |
| A5 | 6번 성공 후 `staging.pdf_blob` | 해당 `tmpid` 행 없음. `extract_job`·`extract_result` 도 CASCADE 로 사라짐 |
| A6 | 같은 `tmpid` 로 6번 두 번 | 두 번째는 `409`, 계약은 한 건만 |
| A7 | 6번 개정판 저장 | 이전 세대가 `terminated`, `terminated_reason='superseded'`, 새 행과 `lineage_id` 동일 |
| A8 | 11번 호출 후 | 그 계약의 `active` 권리가 0건, 이후 같은 조건 계약이 충돌 없이 저장됨 |
| A9 | 세션 없이 8번 | `401 SESSION_EXPIRED` |
| A10 | 세션 없이 7번 | `200` |
| A11 | 8번을 충돌 계약에 호출 | 정상 계약과 같은 스키마, `conflictReport` 채워짐 |
| A12 | `territories=["APAC"]` 로 5번 | `checkedRows` 가 APAC 국가 수와 일치 |

A8 이 특히 중요합니다 — 협의 결렬된 계약이 실제 계약을 막는 상황을 막는 것이 11번의 목적입니다.

### 8.3 동시성

두 요청이 동시에 겹치는 계약을 6번으로 확정하면 **하나는 `applied`, 하나는 `conflicted`** 가 되어야 합니다. 둘 다 `applied` 가 되면 EXCLUDE 가 제대로 걸리지 않은 것입니다. `pytest` + 스레드 두 개로 재현하십시오.

---

## 9. 프론트 연동 규약 (P5)

### 9.1 업로드 후 라우팅

2번 응답을 받는 **즉시** 주소를 `/upload/{tmpid}` 로 바꿉니다. 새로고침 복구의 가장 싼 방법입니다. `tmpid` 를 컴포넌트 state 에만 두면 새로고침 시 사라집니다.

### 9.2 폴링

3번을 2s → 4s → 8s → 최대 30s 로 간격을 늘려가며 호출합니다. 몇 번 실패해도 에러 화면으로 넘기지 말고 간격만 늘리십시오. `status` 가 `DONE` 또는 `FAILED` 가 되면 멈춥니다. 브라우저를 닫아도 워커는 계속 돌므로 나중에 같은 `tmpid` 로 들어오면 결과를 그대로 받습니다.

화면 표시 매핑:

| `status` / `stage` | 표시 |
|---|---|
| `QUEUED` | 대기 중 (앞에 N건) |
| `RUNNING` / `OCR` | 문자 인식 중 |
| `RUNNING` / `LLM` | 조건 추출 중 |
| `DONE` | 검증 표 렌더 |
| `FAILED` | 사유 + 다시 시도 버튼 |

### 9.3 검증 → 저장 두 단계

"충돌검사 실행"(5번)과 "저장"(6번)은 **별개 호출**이고, 5번을 건너뛰고 6번을 바로 부를 수 있습니다. 5번에서 통과했더라도 6번에서 충돌 화면이 다시 나올 수 있으니, 저장 버튼을 눌렀을 때도 충돌 화면으로 갈 수 있게 만드십시오.

5번 응답의 `conflicts[]` 를 그대로 렌더하면 ⑤ 충돌 리포트 화면입니다. **별도 API 를 요청하지 마십시오.** `existing.evidence` 가 이미 실려 있어 원문 대조 팝업도 추가 호출 없이 열립니다.

### 9.4 세션

- 401 `SESSION_EXPIRED` 를 받으면 PIN 모달을 띄우고, 성공 후 **원래 요청을 재시도**합니다.
- 만료 시각(`expiresAt`)으로 화면 우측 상단에 카운트다운을 표시합니다. 인증 응답에 `X-Session-Token`/`X-Session-Expires` 헤더가 오면 저장 토큰과 카운트다운을 갱신합니다(sliding expiration — 활동 중이면 자동 연장, 별도 연장 요청 불필요).
- 세션이 필요한 화면은 계약 상세뿐입니다. 목록·검색·IP 관리에 PIN 모달을 붙이지 마십시오.

### 9.5 충돌 계약 표시

목록에서 `hasConflict=true` 인 행에 배지를 답니다. 상세는 정상 계약과 **같은 컴포넌트**로 렌더하고 `conflictReport` 가 있으면 상단 배너만 추가하십시오. 화면 코드를 갈라놓으면 응답 형태가 같게 설계한 의미가 없습니다.

### 9.6 기간 표시

응답의 `period.end` 는 **포함 개념**(그날까지 유효)입니다. 서버가 `[)` ↔ 포함 변환을 이미 마치고 내려줍니다. 프론트에서 하루를 더하거나 빼지 마십시오.

---

## 10. 하지 말아야 할 것

이 목록을 어기면 설계 의도가 무너집니다.

1. **애플리케이션 코드로 겹침을 계산해서 충돌을 판정하지 마십시오.** EXCLUDE 제약이 유일한 판정자입니다.
2. **`rights_grant` 를 UPDATE 로 수정하지 마십시오.** §4.4 의 세 컬럼만 예외입니다.
3. **충돌을 HTTP 4xx/5xx 로 주지 마십시오.**
4. **`territory` 를 배열이나 그룹 코드로 저장하지 마십시오.** EXCLUDE 가 작동하지 않습니다.
5. **`conditions_raw` 를 판정에 쓰지 마십시오.** 원문 보존·화면 표시 전용입니다.
6. **권리별로 SAVEPOINT 를 나누지 마십시오.** 부분 승인 상태가 생깁니다.
7. **`staging` 을 별도 인스턴스·별도 DB 로 분리하지 마십시오.** 6번이 한 트랜잭션이 아니게 됩니다.
8. **IP 삭제 엔드포인트를 만들지 마십시오.**
9. **`master` / `staging` 의 id 구멍을 메우려 하지 마십시오.** 롤백해도 시퀀스는 돌아가지 않으며 정상입니다.
10. **`extract_job.status` 를 소문자로 바꾸지 마십시오.** P1 이 정한 값입니다.
11. **벡터 검색을 SQL 필터보다 먼저 하지 마십시오.**
12. **8번 응답을 여러 엔드포인트로 쪼개지 마십시오.**

---

## 11. 미확정 항목과 그때까지의 처리

| # | 항목 | 확정 전 처리 | 대상 |
|---|---|---|---|
| 0 | **OST·리메이크 모델링** — 별도 IP + `ip_relation` 로 확정. ERD 리뷰 문서는 아직 `content_asset.asset_type=OST` | `content_asset` 에 `asset_type` 을 **만들지 않음** | P2 |
| 1 | **재허락(`authority`)** — 화면에 카드가 있으나 스키마 미확정 | 8번 응답에 전 필드 `null` 인 객체를 고정 반환 | P2·P5 |
| 2 | **`serviceTitle`** — 목록의 "IP명 / 서비스 타이틀" 중 후자의 출처 미정 | `null` 반환 | P2·P5 |
| 3 | **`contractType`** 값 목록 | 자유 텍스트로 저장, 검증하지 않음 | P2 |
| 4 | **`grantor`(갑)** — `contract` 에 컬럼이 없음. 자기 팀으로 볼지 별도 컬럼을 둘지 | `team.name` 반환 | P2 |
| 5 | **PIN 세션 TTL·연장 규칙** | 확정 — 15분 TTL · sliding expiration(요청 시 +15분, 1분 스로틀), 별도 연장 API 없음 | P4·P5 |
| 6 | **업로드 상한** — 100MB 는 화면 표시값. 스캔본에 그레이스케일·200dpi 다운샘플을 걸지 | 상한만 적용, 변환 없음 | P1·P3 |
| 7 | **검색 결과 권한** — 결과에 계약 금액·상대방이 노출되는데 세션을 요구할지 | 세션 없이 허용 | P4·P5 |

4번은 이 문서를 쓰면서 새로 발견한 항목입니다. `contract` 에 `title`·`contract_type`·`currency` 도 ERD v13 에는 없어 §3.1 에서 추가했습니다. **ERD 반영이 필요합니다.**

---

## 부록 A. 참고 문서

| 문서 | 담는 것 |
|---|---|
| `mindex-API설계서.md` | 16개 엔드포인트의 필드 사전과 예시 JSON |
| `mindex-API-프로세스배치.html` | 어느 화면 단계에서 어떤 API 가 호출되는지 (카드 클릭 시 상세) |
| `mindex-erd-제안안-비교및파이프라인.md` | 팀원에게 요청한 스키마 변경 21건과 사유 |
| `mindex-staging스키마-비동기파이프라인.html` | staging 3테이블과 워커 큐 동작 |

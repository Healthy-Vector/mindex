# ERD 버전 관리

서비스 DB 스키마(ERD)의 버전 이력과 현재 기준을 관리한다.
스키마는 아직 확정 전이며 계속 바뀐다. **어떤 버전을 보고 구현했는지 추적하는 것**이 이 폴더의 목적이다.

## 현재 기준

| 항목 | 값 |
|---|---|
| 현재 버전 | **v3** |
| 문서 | [2026-08-22-v3-remastered.md](2026-08-22-v3-remastered.md) |
| 상태 | `DRAFT` — 확정 전, 추가 수정 예정 |
| 출처 | ERD 이미지 판독 (`mindex_remastered.dbml — ERD (Landscape)`) |
| 원본 파일 | ⚠️ **미확보** — 아래 참조 |

> **원본 `.dbml` 확보 필요**
> v3의 원본 DBML 파일이 저장소에도 `../db_erd/`에도 없다.
> `sources/2026-08-18-v2-remastered.dbml`은 v2이며 v3와 구조가 크게 다르다.
> v3 DBML을 받으면 `sources/`에 넣고 이 문서의 판독 내용을 대조해야 한다.

## 버전 이력

| 버전 | 날짜 | 출처 | 핵심 변화 |
|---|---|---|---|
| **v3** | 2026-08-22 | ERD 이미지 | `legal_right`/`exploitation_mode` **분리**, 권리 계층(nested set) 도입, `content_asset`·`ip_alias` 추가, `contract_history`로 문서 버전 관리, `reason_code` 체계, staging 테이블 제거 |
| v2 | 2026-08-18 | [sources/2026-08-18-v2-remastered.dbml](sources/2026-08-18-v2-remastered.dbml) | `rights_grant_candidate` → `conflict_result` → `conflict_resolution` staging 흐름, `contract_document`, `tenant` 기반 멀티테넌시 |
| v1 | 2026-08-14 | [sources/2026-08-14-v1.dbml](sources/2026-08-14-v1.dbml) | 최초안. `content` 단일 테이블 |
| v0 | (적용 중) | [sql/init/01_schema.sql](../../sql/init/01_schema.sql) | 실제 DB에 올라가 있는 초안. **v3와 크게 다름 — outdated** |

## 주의: 코드와 스키마가 어긋나 있다

현재 컨테이너에 실제로 적용되는 것은 [sql/init/01_schema.sql](../../sql/init/01_schema.sql)(v0)이다.
v0은 `rights_type` 하나로 `legal_right`와 `exploitation_mode`를 합쳐놓은 상태라,
프로젝트가 "절대 합치지 않는다"고 못박은 두 축이 병합돼 있다. v3에서 해소된다.

**v3가 실제 마이그레이션으로 반영되기 전까지 `01_schema.sql`을 설계 근거로 삼지 않는다.**

## 이 폴더의 규칙

- 새 ERD를 받으면 `YYYY-MM-DD-vN-<이름>.md`로 스냅샷을 추가하고 위 이력 표에 한 줄 넣는다.
- 원본 `.dbml`을 받으면 `sources/`에 같은 이름으로 저장한다. 원본이 있으면 그것이 기준이다.
- 이전 버전 문서는 지우지 않는다. 어느 시점에 무엇을 보고 구현했는지가 남아야 한다.

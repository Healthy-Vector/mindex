# ERD 버전 관리

서비스 DB 스키마(ERD)의 버전 이력과 현재 기준을 관리한다.
스키마는 아직 확정 전이며 계속 바뀐다. **어떤 버전을 보고 구현했는지 추적하는 것**이 이 폴더의 목적이다.

## 현재 기준

| 항목 | 값 |
|---|---|
| 현재 버전 | **v3** |
| **원본 (기준)** | **[mindex_remastered.dbml](mindex_remastered.dbml)** ✅ 확보됨 |
| 이미지 판독 스냅샷 | [sources/2026-08-22-v3-remastered.md](sources/2026-08-22-v3-remastered.md) |
| 상태 | `DRAFT` — 확정 전, 추가 수정 예정 |

> **원본 `.dbml`이 기준이다.** `sources/2026-08-22-v3-remastered.md`는 원본을
> 받기 전에 ERD 이미지를 판독해 적어 둔 것이라, 어긋나면 원본이 맞다.

## 버전 이력

| 버전 | 날짜 | 출처 | 핵심 변화 |
|---|---|---|---|
| **v3** | 2026-08-22 | [mindex_remastered.dbml](mindex_remastered.dbml) | `legal_right`/`exploitation_mode` **분리**, 권리 계층(nested set) 도입, `content_asset`·`ip_alias` 추가, `contract_history`로 문서 버전 관리, `reason_code` 체계, staging 테이블 제거 |
| v2 | 2026-08-18 | [sources/2026-08-18-v2-remastered.dbml](sources/2026-08-18-v2-remastered.dbml) | `rights_grant_candidate` → `conflict_result` → `conflict_resolution` staging 흐름, `contract_document`, `tenant` 기반 멀티테넌시 |
| v1 | 2026-08-14 | [sources/2026-08-14-v1.dbml](sources/2026-08-14-v1.dbml) | 최초안. `content` 단일 테이블 |
| v0 | (적용 중) | [sql/init/01_schema.sql](../../sql/init/01_schema.sql) | 실제 DB에 올라가 있는 초안. **v3와 크게 다름 — outdated** |

## PostgreSQL 17 기준이다

원본 dbml 첫 줄이 `PostgreSQL 17`이다. 실물 OpenSQL이 **17.8 + pgvector 0.8.1**
기반이며, RFP v3의 "16.8 기반" 기술은 **오기였다**(2026-08-24 확인).
`docker-compose.yml`·CI 모두 `pgvector/pgvector:0.8.1-pg17`로 맞춰 두었다.

## 주의: 코드와 스키마가 어긋나 있다

현재 컨테이너에 실제로 적용되는 것은 [sql/init/01_schema.sql](../../sql/init/01_schema.sql)(v0)이다.
v0은 `rights_type` 하나로 `legal_right`와 `exploitation_mode`를 합쳐놓은 상태라,
프로젝트가 "절대 합치지 않는다"고 못박은 두 축이 병합돼 있다. v3에서 해소된다.

**v3가 실제 마이그레이션으로 반영되기 전까지 `01_schema.sql`을 설계 근거로 삼지 않는다.**

## 이 폴더의 규칙

- **원본 `.dbml`이 있으면 그것이 기준이다.** 현재 기준은 `mindex_remastered.dbml`.
- 원본 없이 이미지만 받았다면 `sources/YYYY-MM-DD-vN-<이름>.md`로 판독 스냅샷을
  남기고, 나중에 원본을 받으면 대조한다.
- 지난 버전 원본은 `sources/`에 보관한다.
- 이전 버전 문서는 지우지 않는다. 어느 시점에 무엇을 보고 구현했는지가 남아야 한다.

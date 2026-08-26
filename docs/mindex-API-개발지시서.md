# Mindex API 개발 지시서 v1.2

> 기준일: 2026-08-25
>
> 담당: P4 API
>
> 실행 기준: PostgreSQL 17 + `main`의 P2-DB D-30/D-33 및 당사자·페이지 범위 스키마

이 문서는 API 구현 규칙을 정하고, [`mindex-API-프로세스배치.html`](./mindex-API-프로세스배치.html)은 엔드포인트별 요청·응답을 정한다. DB 테이블·함수·제약조건은 P2-DB의 `sql/init/*.sql`, `docs/mindex_remastered.dbml`, `docs/DECISIONS.md`가 정본이다. 서로 어긋나면 DB 구조는 P2-DB, HTTP 계약은 두 API 문서를 함께 수정해 일치시킨다.

## 1. 현재 통합 상태

- P2-DB는 2026-08-25 `main`에 병합됐다. API 코드는 최신 `origin/main`의 `sql/init/00_extensions.sql`부터 `99_schema_meta.sql`까지를 실행 계약으로 삼는다.
- 계약 당사자는 `contract.grantor`(권리를 주는 쪽)와 `contract.grantee`(권리를 받는 쪽)로 구분한다. 구형 `counterparty` 필드는 사용하지 않는다.
- 문서 청크의 페이지 위치는 `pageStart`·`pageEnd`로 표현한다. 단일 `page` 필드는 사용하지 않는다.
- P4는 Alembic 마이그레이션이나 ORM 테이블 복제본을 소유하지 않는다. D-10 정책에 따라 P2가 init SQL을 소유한다.
- 개발 DB 이미지는 `pgvector/pgvector:0.8.1-pg17`이다. PostgreSQL 17을 기준으로 검증한다.

## 2. 시스템 경계

### P4가 구현하는 API

| 번호 | 메서드·경로 | 역할 | PIN |
|---:|---|---|---|
| 1 | `POST /api/auth/pin` | 공유 PIN 세션 발급 | 불필요 |
| 4 | `GET /api/ips/match` | IP·content asset 후보 | 불필요 |
| 5 | `POST /api/contracts/verify` | 저장 전 배치 검증 | 불필요 |
| 6 | `POST /api/contracts` | 계약 세대와 권리 배치 저장 | 불필요 |
| 7 | `GET /api/contracts` | 계약·처리 중 업로드 통합 목록 | 불필요 |
| 8 | `GET /api/contracts/{id}` | 계약·권리·세대 상세 | 필요 |
| 9 | `GET /api/contracts/{id}/file` | 원본 PDF | 필요 |
| 10 | `GET /api/rights/{lineageId}/history` | 권리 계보 | 필요 |
| 11 | `POST /api/contracts/{id}/cancel` | 계약 종료와 권리 해제 | 필요 |
| 12 | `GET /api/ips` | IP 목록·검색 | 불필요 |
| 17 | `GET /api/ips/{id}` | IP·별칭·자산 단건 상세 | 불필요 |
| 13 | `POST /api/ips` | IP 등록 | 불필요 |
| 14 | `PATCH /api/ips/{id}` | IP 부분 수정·활성 전환 | 불필요 |
| 15 | `POST /api/search` | SQL 필터 후 벡터 랭킹 | 불필요 |
| 16 | `GET /api/refs` | 2축 taxonomy·지역·사유코드 | 불필요 |

2번 `POST /extract`와 3번 `GET /extract/{tmpid}`는 P1 소유다. P4는 같은 DB의 `staging.extract_job`·`staging.pdf_blob`·`staging.extract_result`를 조회하고, 6번 요청의 `sourceTmpid`를 P2 함수에 전달한다.

## 3. DB 계약

### 3.1 스키마와 팀 경계

- 도메인 테이블은 PostgreSQL 기본 `public` 스키마에 있다. `master.*` 접두사를 쓰지 않는다.
- 임시 추출 데이터만 `staging` 스키마에 있다.
- `team(id, name, pin_hash)`는 PIN 인증 전용이다.
- `ip`, `contract`, `contract_history`, `rights_grant`에 `team_id`를 추가하지 않는다. 단일사 온프레미스 격리는 설치 인스턴스와 DB 경계가 담당한다.

### 3.2 IP와 자산

- `ip.activity`는 `ip_activity_kind` ENUM의 `active | deactive`다.
- 활성·비활성 전환은 별도 API가 아니라 14번 `PATCH /ips/{id}`의 선택 필드 `activity`로 처리한다.
- `ip_relation`은 아직 없다. 4번 응답의 `relations`는 항상 빈 배열이다.
- IP를 만들면 P2 트리거가 기본 `SERIES_ALL` content asset을 하나 만든다. 13번에 `assets`가 있으면 API가 이 기본 행을 요청 목록으로 교체한다.
- `contract.title`은 없다. 계약 표시명은 최신 `contract_history.file_name`을 사용한다.

### 3.3 권리 판정축

권리 한 행은 다음 원자 단위다.

```text
content_asset_id × territory × legal_right span × exploitation_mode span × period
```

- `legal_right`는 법적 권리, `exploitation_mode`는 사업적 이용형태다.
- 두 taxonomy는 nested-set의 `span int4range`로 상·하위 포함관계를 판정한다.
- API 요청은 `legalRight`와 `exploitationMode`를 모두 보내야 한다. 구형 `rightsType`은 받지 않는다.
- 지역 그룹은 입력 편의 기능이다. API가 `territory_group_member`로 국가 코드까지 펼친 뒤 DB 함수에 전달하며, `rights_grant.territory`에는 국가 하나만 저장한다.
- API 기간의 종료일은 포함값이다. DB `daterange`에는 다음 날을 upper bound로 한 `[start, end+1day)`로 저장한다.
- `exclusivity`는 `exclusive | sole | non_exclusive`다.

### 3.4 상태와 충돌 기록

| 대상 | 상태 |
|---|---|
| `contract.status` | `draft | signed | cancelled` |
| `contract_history.document_kind` | `draft | final` |
| `contract_history.status` | `applied | conflicted` |
| `rights_grant.status` | `active | terminated` |

충돌 시 `rights_grant` 행은 한 건도 남기지 않는다. 대신 새 `contract_history`를 `conflicted`로 저장하고 `conflict_report`를 남긴다. 따라서 충돌을 `rights_grant.status='conflicted'`로 구현하면 안 된다.

```json
{
  "constraintName": "no_exclusive_overlap",
  "exceptionDetail": "...",
  "conflicts": [
    {
      "incoming": {
        "legalRight": "TRANSMISSION",
        "exploitationMode": "SVOD",
        "territory": "KR",
        "period": "[2027-01-01,2028-01-01)",
        "exclusivity": "exclusive"
      },
      "existingGrantId": 5100,
      "existingContractId": 101,
      "overlapPeriod": "[2027-06-01,2028-01-01)",
      "legalRightRelation": "same",
      "exploitationModeRelation": "same",
      "blockingLayer": "no_exclusive_overlap"
    }
  ]
}
```

API는 이 JSON의 내용은 유지하되 내부 키를 재귀적으로 camelCase로 변환해 `conflictReport`로 반환한다. DB의 `contract_history.conflict_report` 원문은 변경하지 않는다. 7번은 최신 세대 상태로 `hasConflict`를 계산하고, 8번은 최신 충돌 세대의 `conflictReport`와 전체 `histories[]`를 내려준다.

## 4. 검증과 확정 저장

Python은 DB와 별도의 외부 계약 충돌 알고리즘을 만들지 않는다. `app/services/conflict.py`는 P2 함수 호출, 입력 참조 검증, 같은 요청 내부의 의미 중복 차단만 담당한다.

### 4.1 요청 권리 JSON

`rights[]`는 한 건 이상이어야 하고 각 항목의 `territories[]`도 비어 있을 수 없다.

```json
{
  "contentAssetId": 80,
  "legalRight": "TRANSMISSION",
  "exploitationMode": "SVOD",
  "territories": ["KR", "JP"],
  "period": { "start": "2027-01-01", "end": "2027-12-31" },
  "exclusivity": "exclusive",
  "evidence": {
    "legal_right": { "quote": "제8조 ..." },
    "exploitation_mode": { "quote": "제8조 ..." },
    "territory": { "quote": "대한민국 ..." },
    "period": { "quote": "2027년 1월 1일부터 ..." },
    "exclusivity": { "quote": "독점적으로 ..." }
  }
}
```

`evidence`의 다섯 키와 비어 있지 않은 `quote`는 DB CHECK가 강제한다. `contentAssetId`를 보냈다면 요청한 `ipId` 소속이어야 한다.

### 4.2 5번 검증

```sql
validate_rights_batch(
  p_contract_id, p_grantor, p_grantee, p_ip_id,
  p_file_name, p_file_path, p_file_hash, p_rights,
  p_mime_type, p_raw_text, p_document_kind
)
```

함수는 실제 INSERT 경로와 동일한 제약을 사용한 뒤 내부 서브트랜잭션을 항상 되돌린다. 응답은 `200`이며 `batchResult`, `hasConflict`, `constraintName`, `conflictReport`를 내려준다.

### 4.3 6번 확정

```sql
save_rights_batch(
  p_contract_id, p_grantor, p_grantee, p_ip_id,
  p_file_name, p_file_path, p_file_hash, p_rights,
  p_mime_type, p_raw_text, p_chunks,
  p_document_kind, p_source_tmpid
)
```

- 적용과 충돌 모두 업무적으로 정상 처리이므로 HTTP `201`이다.
- 적용이면 `contract_history.status='applied'`와 active grant가 함께 커밋된다.
- 충돌이면 grant INSERT 전체를 되돌리고 `contract_history.status='conflicted'`와 `conflict_report`만 커밋한다.
- `sourceTmpid`가 있으면 `staging.extract_job.status='DONE'`이고 대응하는 `extract_result`가 있는지 먼저 확인한다.
- 이미 `contract.source_tmpid`에 쓰인 값은 `409 ALREADY_CONFIRMED`다. 신규·개정 계약 모두 같은 사전 검사를 거친다.
- 같은 계약의 동시 버전 등록은 API가 contract 행을 `FOR UPDATE`로 잠가 `MAX(version)+1` 경쟁을 막는다.
- `chunks[]`의 페이지는 `pageStart`·`pageEnd`로 보내며 둘 다 있으면 `pageEnd >= pageStart`여야 한다.
- `POST /contracts`가 `201`로 끝나면 APPLIED·CONFLICTED 모두 같은 트랜잭션에서 `staging.extract_job.consumed_at`을 기록한다. TTL 정리는 별도 단계다.

## 5. 공통 HTTP 규약

### 5.1 네이밍과 오류

- DB·Python 내부는 `snake_case`, JSON은 `camelCase`다.
- 날짜는 `YYYY-MM-DD`, 시각은 timezone을 포함한 ISO 8601이다.
- 페이지 응답은 `items`, `total`, `page`, `size`를 포함한다.
- 오류는 `{ "error": { "code": "...", "message": "...", "details": {} } }` 한 형태로 보낸다.
- 충돌은 오류가 아니다. 5번은 `200`, 6번은 `201`을 유지한다.

### 5.2 PIN 세션

- 1번 요청은 `{ "pin": "1234" }`다. 외부 요청·응답에 `teamId`를 노출하지 않는다.
- `team.pin_hash`와 bcrypt로 비교하고 평문 PIN을 저장하지 않는다.
- 응답은 `sessionToken`, `expiresAt`, `ttlSeconds`다.
- 보호 API 8·9·10·11은 `Authorization: Bearer <sessionToken>`을 요구한다.
- TTL은 15분이다. 보호 API 호출 시 요청 시각 + 15분으로 sliding expiration을 적용한다.
- 토큰 재발급은 `iat` 기준 세션당 최대 1분에 한 번이다. 새 토큰은 `X-Session-Token`, 만료 시각은 `X-Session-Expires` 응답 헤더로 보낸다.
- 별도 세션 연장 엔드포인트는 만들지 않는다.

## 6. 조회·관리 규칙

### 계약

- 7번은 `contract`와 `staging.extract_job`의 `QUEUED | RUNNING | FAILED`를 합쳐 최신순으로 페이지 처리한다.
- `hasConflict`는 최신 `contract_history.status`가 `conflicted`인지로 계산한다.
- 8번의 active 권리는 `rights_grant`에서 읽고, 충돌 입력은 `histories[].conflictReport`에서 읽는다.
- 10번은 같은 `lineage_id`의 active·terminated 세대를 오래된 순서로 내리고, 서버가 직전 세대와 비교해 `changedFields`를 계산한다. 비교축은 `territory`, `legalRight`, `exploitationMode`, `periodStart`, `periodEnd`, `exclusivity`다.
- 11번은 `contract.status='cancelled'`로 변경한다. P2의 `contract_release_rights` 트리거가 active grant를 `terminated/cancelled`로 바꾼다. 새 `contract_history`는 만들지 않는다.

### IP

- 12번은 `q`로 title·alias를 검색한다. `q`가 있으면 `pg_trgm`의 문자열·단어 유사도와 양방향 부분 일치 점수를 조합해 관련도 내림차순으로 반환하고, 없으면 최신 등록순이다. `includeInactive=false`가 기본이다.
- OCR 추출 제목을 사용하는 4번도 같은 검색 경로를 쓴다. 예를 들어 `겨울왕국 시즌2`는 등록 대표명 `겨울왕국`을 높은 점수로 반환한다.
- 4번은 `GET /api/ips/match?q=겨울왕국%20시즌2&limit=10`, 12번은 `GET /api/ips?q=겨울왕국%20시즌2&page=1&size=20`처럼 호출한다. 0.4 미만 후보는 제외하며, `score`는 문자열 관련도이지 계약 판정 신뢰도가 아니다.
- 검색 결과의 `matchedOn`은 `title | alias`, `matchedText`는 최고 점수를 만든 실제 문자열이다. 같은 점수에서는 대표명 일치를 우선한다.
- 17번은 ID로 IP 단건을 조회하고 `aliases`, `assets`, `contractCount`를 함께 반환한다. 기존 계약 확인을 위해 `deactive` IP도 조회한다. 없는 ID는 `404 NOT_FOUND`다.
- 13번은 중복 정규화 키를 찾으면 `409 IP_DUPLICATE`와 기존 `ipId`를 보낸다.
- 14번은 보낸 필드만 수정한다. `aliases`를 보내면 전체 교체한다. `activity`도 이 요청의 선택 필드다.
- 비활성 IP는 신규 매칭에서 제외하지만 기존 계약 조회에는 영향을 주지 않는다.

### 참조와 검색

- 16번은 `legalRights`, `exploitationModes`, `countries`, `territoryGroups`, `reasonCodes`를 제공한다. 구형 `rightsType`은 제공하지 않는다.
- taxonomy 라벨은 현재 P2 테이블의 `name_ko`를 사용한다. `lang`은 국가·지역 그룹 i18n 라벨 선택에 적용한다.
- 15번은 자연어 해석과 명시 `filters`를 합치되 명시 필터를 우선한다. 검색 대상은 `confirmed_rights_grant`의 서명 완료 계약이다. SQL 후보 축소가 먼저이고 `contract_chunk.embedding` 벡터 랭킹은 그 후보 안에서만 수행한다.

## 7. 테스트 수용 기준

### DB 함수·제약

1. 동일 자산·국가·2축 span·기간의 독점 중첩을 잡는다.
2. `exclusive/sole`과 `non_exclusive`의 금지 조합도 잡는다.
3. 서로 다른 계약의 비독점끼리는 공존한다.
4. legal right 또는 exploitation mode의 상·하위 span 중첩을 잡는다.
5. 기간이 하루도 겹치지 않으면 성공한다.
6. 배치 내부 한 행만 충돌해도 grant 전체가 0행이다.
7. 동시 확정 두 건은 하나만 `APPLIED`가 될 수 있다.

### API

1. 5번 호출 전후 `rights_grant` 행 수가 같다.
2. 6번 성공은 `201/APPLIED`, 충돌은 `201/CONFLICTED`다.
3. 충돌 응답은 P2 `conflict_report` 내용을 보존하고 내부 키를 camelCase로 반환한다.
4. 충돌 세대에는 grant가 없고 7·8번에서 충돌을 표시할 수 있다.
5. 8·9·10·11은 토큰 없이 `401 SESSION_EXPIRED`다.
6. 보호 API 호출 1분 후 새 세션 헤더가 내려온다.
7. `PATCH /ips/{id}`의 `activity=deactive`가 저장되고 기본 목록·매칭에서 제외된다.
8. `/refs`가 법적 권리와 이용형태를 별도 배열로 내려준다.
9. 빈 rights·territories, IP와 asset 소속 불일치, 같은 요청 내부 중복을 거부한다.

DB 통합 테스트는 P2 init SQL이 적용된 PostgreSQL 17에서 실행한다. P2 스키마가 없어서 테스트를 건너뛴 결과를 통과로 간주하지 않는다.

## 8. 남은 통합 작업

1. 현재 P4 작업을 최신 `origin/main` 위에 통합하고 파일 충돌을 해소한다.
2. 최신 main init SQL로 새 PG17 볼륨을 만들고 API 통합·동시성 테스트를 실행한다.
3. `contract_history.file_path`의 실제 object storage 어댑터를 연결한다. 현재 로컬 파일 응답은 개발용이다.
4. staging PDF·작업·결과 JSONB의 TTL 정리 책임과 주기를 P1·P2·P4 사이에서 확정한다. `consumed_at` 기록은 확정 API가 맡는다.
5. 검색 응답의 스니펫·교차언어 UI 계약은 임베딩 서비스가 연결될 때 확장하되 SQL 필터 우선 순서는 유지한다.
6. 운영 배포 전에 단일 `team` 행과 bcrypt `pin_hash`를 provisioning한다.
7. `extract_result.payload`의 확정 입력 병합 규칙을 P1과 필드 단위로 확정한다. 현재는 DONE·결과 존재 여부를 검증하고 사용자가 검토한 요청 본문을 저장한다.
8. P2의 `contract.source_tmpid`는 개정 시 마지막 값으로 덮어써 과거 tmpid 재사용을 영구 차단하지 못한다. `contract_history.source_tmpid UNIQUE` 또는 별도 consumed ledger를 P2 스키마에 추가한다.
9. staging 처리 목록의 filename이 필요하면 `pdf_blob` 직접 권한을 넓히지 말고 최소권한 메타데이터 view를 P2/P1과 정의한다. 현재 P4 목록은 권한 계약에 맞춰 filename을 null로 반환한다.
10. 충돌 화면을 버전업할 때 LLM 한 줄 설명의 생성 시점, `conflictReport` 저장 키, API 응답과 UI 표시를 함께 정의한다. 현재 버전에는 설명 필드를 추가하지 않는다.
11. OpenSQL 운영 설치에서 `pg_available_extensions`로 `pg_trgm` 패키지 포함 여부를 확인한다. 없으면 OpenSQL의 PostgreSQL 버전에 맞는 contrib 패키지를 설치한 뒤 init SQL을 적용한다.

## 9. 금지 사항

- Python에서 DB와 별도의 외부 계약 충돌 판정 구현
- `rightsType` 단일축 복구
- `rights_grant`에 `conflicted` 상태 추가
- 도메인 테이블에 `team_id` 전파
- `master.*` 스키마 사용
- P4 Alembic·ORM으로 P2 DDL 복제
- 검증과 확정에 서로 다른 판정 경로 사용
- 충돌을 HTTP 4xx/5xx로 반환
- 벡터 검색 후 SQL 필터 적용
- 별도 PIN 연장 API 추가

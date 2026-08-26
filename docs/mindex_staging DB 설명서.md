# Mindex staging 스키마 구조 및 데이터 파이프라인

`staging`은 **운영 DB(`mindex`)와 같은 PostgreSQL 인스턴스, 같은 DB 안의 별도 스키마**다. OCR·LLM 추출이 계약서 한 건에 50~60초 걸려 요청 안에서 끝낼 수 없어서 생긴 비동기 큐 + 임시 결과 보관용이다. SQL 정본은 `sql/init/06_staging_schema.sql`·`07_staging_roles.sql`, 모델 정본은 [mindex_remastered.dbml](mindex_remastered.dbml)(같은 DB이므로 `staging` 스키마 테이블도 이 파일 안에 있다), 시각 자료는 [mindex_staging_erd.svg](mindex_staging_erd.svg)와 [mindex-임시DB-비동기파이프라인.html](mindex-임시DB-비동기파이프라인.html)이다. 설계 결정은 [DECISIONS.md](DECISIONS.md)의 **D-32**(임시 DB 도입) → **D-33**(별도 인스턴스가 아니라 스키마 분리라고 정정).

> **D-32 → D-33 정정**: D-32에서 "물리적으로 분리된 별도 인스턴스"로 확정했던 건 팀이 "인스턴스"를 스키마 레벨로 오해한 것이었다. 이 문서는 D-33 기준(같은 DB, 스키마 분리)으로 다시 썼다. 아래 표·코드의 스키마 접두사는 전부 `staging.`이다.

이전 `pdf_cache`(동기 처리 전제, 5테이블 정규화: `pdf_cache`/`contract_extraction`/`party`/`rights_grant`/`payment`/`evidence`)를 대체한다.

## 1. 구조 요약

```text
staging.pdf_blob ──(1:1, CASCADE)── staging.extract_job ──(1:1, CASCADE)── staging.extract_result
       PK tmpid                          PK/FK tmpid                            PK/FK tmpid
```

`public.contract.source_tmpid`가 `staging.extract_job.tmpid`를 가리킨다. 같은 DB 안이라 **실제 FK**다 (`ON DELETE SET NULL`, §5).

## 2. 테이블 3개 (`staging` 스키마)

| 테이블 | 역할 |
|---|---|
| `staging.pdf_blob` | 업로드된 PDF 원본을 암호화해 그대로 보관 |
| `staging.extract_job` | 큐 겸 상태 테이블. 워커가 `FOR UPDATE SKIP LOCKED`로 폴링 |
| `staging.extract_result` | AI 추출 결과 전체를 `payload jsonb` 하나로 보관 |

세부 필드를 정규화 테이블로 쪼개지 않는다 — 확정 전 검토용 데이터라 정규화할 이유가 없고, 확정된 값만 `public.rights_grant`로 넘어간다.

### `staging.pdf_blob`

| 컬럼 | 의미 |
|---|---|
| `tmpid` (PK) | `gen_random_uuid()` 기본값 |
| `data` | 암호화된 PDF 바이트 원본 |
| `filename`, `byte_size` | 원본 메타데이터 |
| `created_at` | 업로드 시각 |

### `staging.extract_job`

| 컬럼 | 의미 |
|---|---|
| `tmpid` (PK, FK → `staging.pdf_blob`) | |
| `status` | `QUEUED \| RUNNING \| DONE \| FAILED` |
| `stage` | `OCR \| LLM` — 화면 진행 표시용 |
| `lease_until` | RUNNING 점유 만료 시각. 지나면 다른 워커가 자동 회수 |
| `attempts` | 재시도 횟수 |
| `reason` | FAILED 사유 |
| `consumed_at` | 확정(`contract.source_tmpid` 기록)이 끝난 시각. `POST /contracts`가 201로 완료될 때 같은 트랜잭션에서 기록 |
| `created_at` | |

`(status, created_at)` 인덱스가 `SKIP LOCKED` 폴링을 지원한다.

### `staging.extract_result`

| 컬럼 | 의미 |
|---|---|
| `tmpid` (PK, FK → `staging.extract_job`) | |
| `payload` | AI 추출 결과 원본. `status='DONE'`과 한 트랜잭션으로 커밋 |
| `created_at` | |

화면은 이 `payload`를 읽어 사용자에게 보여준다. **사용자가 고친 값도 여기 남는다(D-34).** 검증(⑦)이 `tmpid`와 부분수정(JSON Merge Patch)을 받아 `payload`에 반영한 뒤 저장된 값으로 판정한다.

`payload`는 두 shape를 함께 담는다.

| 키 | 내용 |
|---|---|
| `raw` | 워커 원본. `raw.contract.*`의 필드마다 `field_status` 래퍼가 붙는다 |
| `validation` | 워커의 confidence 등 |
| `edited` | 사용자 수정본. 화면이 보는 DTO shape(`contractInfo`/`rights`/…) 그대로 |

`raw`를 덮어쓰지 않는 이유는 `to_upload_result()`(워커 원본 → 화면 DTO)가 **단방향이고 손실이 있기** 때문이다 — 워커 코드가 접히고(`EXHIBITION`·`PERFORMANCE` → `PUBLIC_PERFORMANCE`) territory 그룹이 국가로 전개된다. 역변환기를 만들 수 없어 DTO로 덮어쓰면 재조회가 깨진다. `GET /extract/{tmpid}`는 `edited`가 있으면 그걸 돌려준다.

## 3. 데이터 파이프라인 (① ~ ⑩)

같은 DB지만 스키마는 여전히 나뉜다 — 접근 롤(§6)이 스키마 경계로 최소권한을 강제한다.

| 단계 | 스키마 | 내용 |
|---|---|---|
| ① 업로드 접수 | staging | `pdf_blob` INSERT + `extract_job` INSERT(`QUEUED`)를 한 트랜잭션으로. 커밋 후 `202 {tmpid, "QUEUED"}` 반환 |
| ② 워커 수령 | staging | `SELECT ... FOR UPDATE SKIP LOCKED`로 `QUEUED` 한 건을 집어감. `status='RUNNING'`, `lease_until` 갱신, `attempts+1` |
| ③ OCR → LLM 처리 | staging | 50~60초 구간. `stage`를 `OCR`→`LLM`으로 갱신하며 `lease_until` 연장 |
| ④ 결과 커밋 | staging | `extract_result` UPSERT + `extract_job.status='DONE'`을 한 트랜잭션으로. `payload.chunks`에는 워커가 만든 검색 청크·임베딩도 함께 보존한다. 결과와 상태 중 하나만 있는 어중간한 상태는 존재할 수 없다 |
| ⑤ 화면 폴링 | staging | `GET /extract/{tmpid}`. 브라우저를 닫아도 워커는 계속 돈다 |
| ⑥ 사용자 확인·수정 | staging | 화면이 값을 고치면 ⑦ 호출에 부분수정(patch)으로 실려 `extract_result.payload.edited`에 반영된다(D-34). 예전에는 DB 접근이 없었다 |
| ⑦ 검증 | staging + public | `tmpId`가 오면 먼저 수정본을 `extract_result`에 반영·커밋한다. 그 다음 **저장된 값으로** `SAVEPOINT` 잡고 `rights_grant`를 실제로 INSERT해 본 뒤 무조건 롤백. 판정은 롤백되지만 수정본은 남는다(D-34) |
| ⑧ 확정(저장) | public (staging 조회 포함) | `tmpid`로 `payload.edited`(없으면 `raw`)와 워커의 `payload.chunks`를 읽는다. 화면은 청크를 보내지 않으며, 서버가 청크·임베딩을 `p_chunks`로 넣어 `save_rights_batch(..., p_source_tmpid => tmpid)`를 호출한다. 이어서 **`pdf_blob.data`를 서버 저장소로 옮기고**(`{contract_id}/{history_id}.pdf`, D-34b) 그 상대 경로를 `contract_history.file_path`에 UPDATE한다. `contract.source_tmpid` 기록은 SAVEPOINT 밖이라 배치가 충돌해도 남으며, API가 같은 트랜잭션에서 `extract_job.consumed_at = now()`를 기록한다 |
| ⑨ 정리 | staging | TTL 정리 작업이 소비된 작업의 `pdf_blob`을 삭제한다(CASCADE로 나머지 두 테이블 동반 삭제) |
| ⑩ 사후 처리 | public | `change_log` 재색인 대상 기록 등 후속 처리 |

⑧의 "tmpid로 읽어서 저장 쿼리를 만든다"가 확정된 방식이다(B안) — 화면은 검증 필드만 들고 있고, evidence·conditions_raw 같은 나머지는 확정 API 서버가 `staging.extract_result`에서 직접 읽어 채운다. 화면이 저장 API에 전체 페이로드를 다시 보낼 필요가 없다. **이 B안은 D-34에서 실제로 코드에 반영됐다** — 그 전까지 구현은 요청 body만 쓰는 A안이었다.

## 4. `extract_job` 상태 전이

```text
QUEUED → RUNNING → DONE → (확정 시 consumed_at 기록) → TTL 삭제
            │  ↑ lease 만료 시 재수령
            └→ FAILED (attempts 초과, reason 기록) → TTL 7일 배치 → 삭제
```

`DONE`·`FAILED`에서 앞으로 되돌아가는 전이는 없다.

## 5. `public.contract`와의 연결 — `source_tmpid`

```sql
-- sql/init/01_schema.sql
contract.source_tmpid uuid UNIQUE

-- sql/init/06_staging_schema.sql (staging 스키마 생성 후 ALTER로 붙는다)
ALTER TABLE contract
    ADD FOREIGN KEY (source_tmpid)
    REFERENCES staging.extract_job(tmpid) ON DELETE SET NULL;
```

- 같은 DB 안이라 **실제 FK**다. `staging.extract_job`에 없는 tmpid로 확정을 시도하면 `ForeignKeyViolation`으로 걸러진다 — 예전(별도 인스턴스 가정) 설계에는 없던 참조 무결성 보장이다.
- `UNIQUE`가 같은 tmpid로 두 번 확정되는 것을 막는다(중복 확정 방지 목적은 그대로).
- `ON DELETE SET NULL`: TTL 정리 배치가 `staging.pdf_blob`을 지우면(CASCADE로 `extract_job`도 삭제) `contract.source_tmpid`는 `NULL`로 풀린다 — 정리 배치가 이미 확정된 `contract` 행 자체를 건드리거나 지우면 안 되기 때문이다.
- `save_rights_batch()`의 마지막 인자 `p_source_tmpid`가 이 값을 받는다. 신규 계약은 INSERT에 포함, 기존 계약(개정판)은 SAVEPOINT 진입 전에 UPDATE로 기록한다 — 그래서 배치가 충돌(`CONFLICTED`)해도 "이 tmpid로 확정을 시도했다"는 사실 자체는 남는다.
- 비동기 파이프라인을 거치지 않는 호출(예: 테스트, 수동 등록)은 `p_source_tmpid`를 생략하면 된다. 기본값 `NULL` — FK는 `NULL`엔 안 걸린다.

## 6. 최소권한 DB 롤 (SER-002)

`sql/init/07_staging_roles.sql`에 NOLOGIN 롤 3개를 정의한다. 실제 로그인 계정·비밀번호는 이 파일에 없다 — `.env`와 같은 이유로 커밋 대상이 아니며, 배포 시 `GRANT <role> TO <login_role>`로 소속시키는 건 배포(ops/P1) 책임이다. 일반 접근 기준값은 "insert, select만"이고, 워커·정리 배치는 그 예외다(D-33 팀장 확인).

| 롤 | 접근 주체 | 권한 |
|---|---|---|
| `staging_worker` | OCR·LLM 워커(P1) | `staging.pdf_blob` SELECT · `staging.extract_job` SELECT/UPDATE · `staging.extract_result` INSERT/UPDATE |
| `staging_confirm_api` | 검증·확정 API 서버(P4, §3 ⑦⑧) | `staging.extract_result` SELECT/UPDATE · `staging.extract_job` SELECT + `UPDATE(consumed_at)` · `staging.pdf_blob` SELECT |
| `staging_cleanup` | TTL 7일 정리 배치 (미구현) | `staging.pdf_blob` SELECT/DELETE · `staging.extract_job` SELECT |

세 롤 모두 `GRANT USAGE ON SCHEMA staging`이 먼저 필요하다(별도 DB일 땐 필요 없던 권한 — 스키마 접근 자체를 막을 수 있게 됐다는 게 스키마 분리의 이점이다).

**D-34로 `staging_confirm_api`의 경계가 두 군데 넓어졌다.** 둘 다 최소권한 기준값의 예외다.

- `extract_result` **UPDATE** — 검증(⑦)이 사용자 수정본을 반영해야 한다. `payload` 한 컬럼이라 컬럼 단위로 좁힐 수 없고, 애플리케이션이 `edited` 키만 갱신하고 워커 원본 `raw`는 건드리지 않는 것으로 대신한다. **DB 제약이 아니라 애플리케이션 규약에만 의존한다** — P-4 기준에서는 후퇴이며, 좁히려면 `edited`를 별도 컬럼으로 분리해야 한다(후속 과제).
- `pdf_blob` **SELECT** — 확정(⑧)이 원본 PDF를 서버 저장소로 옮기게 되면서 바이트가 필요해졌다(D-34b). 종전에는 "확정 단계에 PDF 원본 바이트는 필요 없다"며 의도적으로 막아뒀던 권한이다. 확정 경로가 뚫리면 이제 원본 바이트도 읽힌다.

`staging_confirm_api`가 실제로 `save_rights_batch()`를 호출하려면 `public` 스키마 쪽 권한(EXECUTE, `contract`/`contract_history`/`rights_grant` INSERT/UPDATE 등)도 필요하다 — 그건 이 롤 정의 범위 밖이고, `public` 스키마 전체 롤 설계(SER-002)는 별도 작업이다.

## 7. 유실 방지 — 어느 단계에서 죽어도 운영 DB는 틀어지지 않는다

| 단계 | 파드가 죽으면 | 방어 |
|---|---|---|
| ① 업로드 접수 중 | 커밋 안 됨 → 아무 것도 안 남음 | 한 트랜잭션. 사용자는 202를 못 받았으니 재업로드가 정상 |
| ② 수령 직후 | `RUNNING`인 채 방치 | `lease_until` 만료 → 다른 워커가 자동 회수 |
| ③ 처리 중 | 작업 통째로 소실 | 같은 lease 회수 경로로 재처리. `attempts` 초과 시 `FAILED` |
| ④ 결과 커밋 중 | 결과/상태 중 하나만 저장될 위험 | 한 트랜잭션이라 부분 저장 불가 |
| ⑤ 폴링 중 이탈 | 화면만 사라짐 | 워커는 계속 진행, 같은 tmpid로 재접속하면 결과 그대로 |
| ⑥ 확인·수정 중 이탈 | 사용자가 고친 값 소실 | 설계상 허용. `extract_result`는 `DONE`으로 남아 재조회 가능 |
| ⑦ 검증 중 | 운영 DB에 흔적 없음 | 무조건 롤백 |
| ⑧ 확정 중 | `public` 트랜잭션 롤백 | staging은 `DONE`째 남아 같은 tmpid로 재시도 가능 |
| ⑧ 커밋 직후 · ⑨ 직전 | `public` 확정과 `consumed_at` 기록은 끝났고 staging 데이터가 남음 | TTL 정리 작업이 삭제하며 `source_tmpid UNIQUE`가 중복 확정을 막음 |
| ⑨ 정리 중 | `consumed_at`이 찍힌 `pdf_blob`이 잔존 가능 | TTL 정리 작업이 재시도 |
| ⑩ 사후 처리 중 | 임베딩·색인 지연 | `change_log` 행이 남아 워커가 재시도. 계약 데이터 자체는 이미 확정 |

**O-15 (신규, D-33)**: `consumed_at` 기록은 ⑧ 확정 트랜잭션에 포함했다. ⑨의 실제 삭제는 TTL 정리 작업의 별도 책임으로 남기며, 삭제 주기와 운영 주체만 팀 논의가 필요하다.

## 8. 아직 없는 것 (O-12 · O-14 · TTL 정리, WORKLOG 2026-08-22 참고)

- **워커(P1)**: `SKIP LOCKED` 폴링, OCR→LLM 처리 코드는 존재하지 않는다.
- **확정 API의 병합 로직(P4)**: `tmpid`로 `staging.extract_result`를 읽어 화면의 검증 필드와 합치는 코드는 존재하지 않는다. 이 문서 §3 ⑧과 §6의 `staging_confirm_api` 롤은 그 로직이 붙을 자리를 미리 정의해 둔 것이다. 이 롤이 `public` 스키마에 필요한 권한(EXECUTE `save_rights_batch()` 등)도 아직 없다.
- **TTL 7일 정리 배치**: 스케줄러·구현 모두 없다.
- **`extract_result.payload` 암호화 여부(O-14)**: `pdf_blob.data`는 암호화 대상으로 명시돼 있지만 `payload`(계약서 원문 인용 포함)는 미정. 팀/보안 담당 확인 필요.
- **TTL 7일 정리 배치의 주기·운영 주체**: `consumed_at` 기록은 ⑧에 포함했으며, 실제 삭제 정책만 남아 있다. §7 참고.
- **로그인 계정 발급**: §6의 NOLOGIN 롤에 실제 로그인 계정을 물리는 작업은 ops/P1 몫이며 아직 안 됐다 — 지금은 여전히 공용 계정으로 접근 중일 것이다.

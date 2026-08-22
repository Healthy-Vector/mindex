# Mindex Staging DB 구조 및 데이터 파이프라인

`mindex_staging`은 운영 DB(`mindex`)와 **물리적으로 분리된 별도 PostgreSQL 인스턴스**다. OCR·LLM 추출이 계약서 한 건에 50~60초 걸려 요청 안에서 끝낼 수 없어서 생긴 비동기 큐 + 임시 결과 보관용 DB다. SQL 정본은 `sql/staging_init/*.sql`, 모델 정본은 [mindex_staging.dbml](mindex_staging.dbml), 시각 자료는 [mindex_staging_erd.svg](mindex_staging_erd.svg)와 [mindex-임시DB-비동기파이프라인.html](mindex-임시DB-비동기파이프라인.html)이다. 설계 결정은 [DECISIONS.md](DECISIONS.md)의 **D-32**.

이전 `pdf_cache`(동기 처리 전제, 5테이블 정규화: `pdf_cache`/`contract_extraction`/`party`/`rights_grant`/`payment`/`evidence`)를 대체한다.

## 1. 구조 요약

```text
pdf_blob ──(1:1, CASCADE)── extract_job ──(1:1, CASCADE)── extract_result
   PK tmpid                    PK/FK tmpid                    PK/FK tmpid
```

운영 DB `contract.source_tmpid`가 이 DB의 `extract_job.tmpid`를 **논리적으로** 가리킨다. 별도 인스턴스라 실제 FK는 없다 — `UNIQUE` 제약이 같은 tmpid의 이중 확정을 막는 유일한 방어선이다.

## 2. 테이블 3개

| 테이블 | 역할 |
|---|---|
| `pdf_blob` | 업로드된 PDF 원본을 암호화해 그대로 보관 |
| `extract_job` | 큐 겸 상태 테이블. 워커가 `FOR UPDATE SKIP LOCKED`로 폴링 |
| `extract_result` | AI 추출 결과 전체를 `payload jsonb` 하나로 보관 |

세부 필드를 정규화 테이블로 쪼개지 않는다 — 확정 전 검토용 데이터라 정규화할 이유가 없고, 확정된 값만 운영 DB `rights_grant`로 넘어간다.

### `pdf_blob`

| 컬럼 | 의미 |
|---|---|
| `tmpid` (PK) | `gen_random_uuid()` 기본값 |
| `data` | 암호화된 PDF 바이트 원본 |
| `filename`, `byte_size` | 원본 메타데이터 |
| `created_at` | 업로드 시각 |

### `extract_job`

| 컬럼 | 의미 |
|---|---|
| `tmpid` (PK, FK → `pdf_blob`) | |
| `status` | `QUEUED \| RUNNING \| DONE \| FAILED` |
| `stage` | `OCR \| LLM` — 화면 진행 표시용 |
| `lease_until` | RUNNING 점유 만료 시각. 지나면 다른 워커가 자동 회수 |
| `attempts` | 재시도 횟수 |
| `reason` | FAILED 사유 |
| `consumed_at` | 운영 DB 확정이 끝난 시각. 확정(운영 DB)과 정리(임시 DB)를 한 트랜잭션으로 못 묶어서 생긴 컬럼 |
| `created_at` | |

`(status, created_at)` 인덱스가 `SKIP LOCKED` 폴링을 지원한다.

### `extract_result`

| 컬럼 | 의미 |
|---|---|
| `tmpid` (PK, FK → `extract_job`) | |
| `payload` | AI 추출 결과 원본. `status='DONE'`과 한 트랜잭션으로 커밋 |
| `confidence` | |
| `created_at` | |

화면은 이 `payload`를 읽어 사용자에게 보여준다. 사용자가 고친 값은 여기 다시 쓰지 않는다 — 확정 전 값은 화면이 들고 있다가 확정 시점에 한 번에 넘어간다.

## 3. 데이터 파이프라인 (① ~ ⑩)

| 단계 | DB | 내용 |
|---|---|---|
| ① 업로드 접수 | 임시 | `pdf_blob` INSERT + `extract_job` INSERT(`QUEUED`)를 한 트랜잭션으로. 커밋 후 `202 {tmpid, "QUEUED"}` 반환 |
| ② 워커 수령 | 임시 | `SELECT ... FOR UPDATE SKIP LOCKED`로 `QUEUED` 한 건을 집어감. `status='RUNNING'`, `lease_until` 갱신, `attempts+1` |
| ③ OCR → LLM 처리 | 임시 | 50~60초 구간. `stage`를 `OCR`→`LLM`으로 갱신하며 `lease_until` 연장 |
| ④ 결과 커밋 | 임시 | `extract_result` UPSERT + `extract_job.status='DONE'`을 한 트랜잭션으로. 결과와 상태 중 하나만 있는 어중간한 상태는 존재할 수 없다 |
| ⑤ 화면 폴링 | 임시 | `GET /extract/{tmpid}`. 브라우저를 닫아도 워커는 계속 돈다 |
| ⑥ 사용자 확인·수정 | — | DB 접근 없음. 수정값은 화면이 들고 있다가 ⑧에서 한 번에 넘어간다 |
| ⑦ 검증 | 운영 | `SAVEPOINT` 잡고 `rights_grant`를 실제로 INSERT해 본 뒤 무조건 롤백. 충돌 여부만 표시하고 행은 남기지 않는다 |
| ⑧ 확정(저장) | 운영 | `tmpid`로 `extract_result.payload`를 읽어 화면이 보낸 검증 필드와 병합 → `save_rights_batch(..., p_source_tmpid => tmpid)` 호출. `contract.source_tmpid` 기록은 SAVEPOINT 밖이라 배치가 충돌해도 남는다 |
| ⑨ 임시 정리 | 임시 | `extract_job.consumed_at = now()` 기록 후 `pdf_blob` 삭제 (CASCADE로 나머지 두 테이블 동반 삭제). ⑧과 별개 트랜잭션 |
| ⑩ 사후 처리 | 운영 | `change_log` 재색인 대상 기록 → 임베딩·검색 인덱스 갱신 (비동기) |

⑧의 "tmpid로 읽어서 저장 쿼리를 만든다"가 확정된 방식이다(B안) — 화면은 검증 필드만 들고 있고, evidence·conditions_raw 같은 나머지는 확정 API 서버가 `extract_result`에서 직접 읽어 채운다. 화면이 저장 API에 전체 페이로드를 다시 보낼 필요가 없다.

## 4. `extract_job` 상태 전이

```text
QUEUED → RUNNING → DONE → (consumed_at 기록) → 삭제
            │  ↑ lease 만료 시 재수령
            └→ FAILED (attempts 초과, reason 기록) → TTL 7일 배치 → 삭제
```

`DONE`·`FAILED`에서 앞으로 되돌아가는 전이는 없다.

## 5. 운영 DB와의 연결 — `source_tmpid`

```sql
-- sql/init/01_schema.sql
contract.source_tmpid uuid UNIQUE
```

- 별도 인스턴스라 실제 FK는 못 건다. `UNIQUE`가 같은 tmpid로 두 번 확정되는 것을 막는 유일한 방어다.
- `save_rights_batch()`의 마지막 인자 `p_source_tmpid`가 이 값을 받는다. 신규 계약은 INSERT에 포함, 기존 계약(개정판)은 SAVEPOINT 진입 전에 UPDATE로 기록한다 — 그래서 배치가 충돌(`CONFLICTED`)해도 "이 tmpid로 확정을 시도했다"는 사실 자체는 남는다.
- 비동기 파이프라인을 거치지 않는 호출(예: 테스트, 수동 등록)은 `p_source_tmpid`를 생략하면 된다. 기본값 `NULL`.

## 6. 최소권한 DB 롤 (SER-002)

`sql/staging_init/02_roles.sql`에 NOLOGIN 롤 3개를 정의한다. 실제 로그인 계정·비밀번호는 이 파일에 없다 — `.env`와 같은 이유로 커밋 대상이 아니며, 배포 시 `GRANT <role> TO <login_role>`로 소속시키는 건 배포(ops/P1) 책임이다.

| 롤 | 접근 주체 | 권한 |
|---|---|---|
| `staging_worker` | OCR·LLM 워커(P1) | `pdf_blob` SELECT · `extract_job` SELECT/UPDATE · `extract_result` INSERT/UPDATE |
| `staging_confirm_api` | 확정 API 서버(P4, §3 ⑧) | `extract_result` SELECT · `extract_job` SELECT + `UPDATE(consumed_at)`만 |
| `staging_cleanup` | TTL 7일 정리 배치 (미구현) | `pdf_blob` SELECT/DELETE · `extract_job` SELECT |

`staging_confirm_api`에는 **`pdf_blob` 권한을 의도적으로 안 줬다** — 확정 단계는 추출 결과(jsonb)만 필요하고 PDF 원본 바이트는 필요 없다. 확정 경로가 뚫려도 원본 바이트까지는 노출되지 않는다.

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
| ⑧ 확정 중 | 운영 DB 트랜잭션 롤백 | 임시 DB는 `DONE`째 남아 같은 tmpid로 재시도 가능 |
| ⑧ 커밋 직후 · ⑨ 직전 | 운영 DB는 확정됐는데 임시 데이터가 남음 — **별도 DB라서 생기는 유일한 실질 유실 구간** | 운영 데이터는 이미 정확. TTL 7일 배치가 정리하고, 재시도해도 `source_tmpid UNIQUE`가 중복 확정을 막음 |
| ⑨ 정리 중 | `consumed_at`만 찍히고 `pdf_blob` 잔존 가능 | TTL 7일 배치가 정리 |
| ⑩ 사후 처리 중 | 임베딩·색인 지연 | `change_log` 행이 남아 워커가 재시도. 계약 데이터 자체는 이미 확정 |

## 8. 아직 없는 것 (O-12 · O-14, WORKLOG 2026-08-22 참고)

- **워커(P1)**: `SKIP LOCKED` 폴링, OCR→LLM 처리 코드는 존재하지 않는다.
- **확정 API의 병합 로직(P4)**: `tmpid`로 `extract_result`를 읽어 화면의 검증 필드와 합치는 코드는 존재하지 않는다. 이 문서 §3 ⑧과 §6의 `staging_confirm_api` 롤은 그 로직이 붙을 자리를 미리 정의해 둔 것이다.
- **TTL 7일 정리 배치**: 스케줄러·구현 모두 없다.
- **`extract_result.payload` 암호화 여부(O-14)**: `pdf_blob.data`는 암호화 대상으로 명시돼 있지만 `payload`(계약서 원문 인용 포함)는 미정. 팀/보안 담당 확인 필요.
- **로그인 계정 발급**: §6의 NOLOGIN 롤에 실제 로그인 계정을 물리는 작업은 ops/P1 몫이며 아직 안 됐다 — 지금은 여전히 공용 계정으로 접근 중일 것이다.

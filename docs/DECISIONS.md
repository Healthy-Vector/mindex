# DECISIONS — 현재 설계 결정

이 문서는 [정본 DBML](mindex_remastered.dbml)에 실제 반영된 결정만 기록한다. 실행 스키마는 PostgreSQL 16용 `sql/init/*.sql`이며 DBML과 함께 변경한다.

## 기준 원칙

- P-1: LLM은 비정형 문서를 정형 데이터로 변환하지만 충돌을 판정하지 않는다.
- P-2: 충돌 판정은 결정론적인 DB 함수와 제약조건이 수행한다.
- P-3: 모든 추출값은 페이지·조항·원문 인용 근거를 동반한다.
- P-4: 애플리케이션을 우회해도 DB 무결성이 유지되어야 한다.

## 현행 결정

### D-05 — 충돌 방어는 EXCLUDE와 statement trigger의 2단 구조

`exclusive`/`sole`끼리의 충돌은 `no_exclusive_overlap` GiST EXCLUDE가 차단한다. 독점과 `non_exclusive` 사이의 금지 조합은 `check_exclusivity_conflict()` statement trigger가 `no_exclusivity_conflict` 오류로 차단한다. 두 장치는 `content_asset × 국가 × legal_right span × exploitation_mode span × 기간`을 같은 판정키로 사용한다.

같은 계약 내부의 권리 행끼리는 충돌 대상으로 보지 않기 위해 EXCLUDE에 `contract_id WITH <>`를 포함한다. 배치 내부의 의미 중복은 입력 검증 책임이다.

### D-08 — 충돌 제약명은 공개 인터페이스다

UI와 `constraint_reason_map`이 사용하는 `no_exclusive_overlap`, `no_exclusivity_conflict` 이름을 고정한다. WAIVER도 제약을 우회하지 않고 기존 grant를 종료한 후 신규 배치를 다시 제출한다.

### D-14 — 민감정보와 판정 키를 분리

원문·계약 메타데이터는 암호화 정책 대상이다. EXCLUDE와 결정론적 판정에 참여하는 정규화 키는 DB가 비교할 수 있어야 하므로 애플리케이션 암호화 대상에서 제외한다. 임베딩은 검색을 위해 평문 벡터로 유지되는 한계가 있다.

### D-15 — 지역 그룹은 입력 전개용, 저장·판정 단위는 국가

`WORLDWIDE`, `APAC` 같은 그룹은 `territory_group_member`를 통해 국가별 행으로 전개한다. `rights_grant.territory`에는 ISO 3166-1 alpha-2 코드 하나만 저장한다. 다중 지역의 원문 표현과 스냅샷 정책은 아직 확정하지 않았다.

### D-19·D-25 — D-30으로 대체

과거 candidate 사전 평가, 후보 상태, candidate evidence, 문서별 부분 승인 모델은 D-30의 계약서 단위 all-or-nothing 모델로 대체됐다. `rights_grant_candidate`, `candidate_evidence`, `rights_evaluation`, `rights_evaluation_reason`, `conflict_resolution`, `rights_grant_history`는 현행 스키마에 없다.

### D-26 — 일부만 유효

`contract_version`과 grant history 트리거 정책은 D-30으로 폐기됐다. 계약 메타데이터 수정 이력의 대체 테이블은 현재 없다. `contract_history.raw_text` 변경을 `change_log`에 남겨 재청킹하는 원칙은 유지한다.

### D-27 — 2축 계층 판정은 유지

판정축은 `legal_right × exploitation_mode`다. 두 taxonomy는 nested-set 좌표에서 생성한 `int4range span`을 사용하고, `rights_grant`에는 trigger가 span을 채운다. EXCLUDE는 두 span을 `&&`로 비교해 상위·하위 포함관계를 잡는다.

D-30에서 `statutory_right`와 `right_mapping`은 삭제했다. 따라서 관할별 typicality/advisory 경고는 현재 생성하지 않는다. `reason_code`는 conflict report와 앱이 참고할 공용 어휘이며 candidate 워크플로우를 구동하지 않는다.

### D-28 — D-30의 배치 검증·저장 규약으로 대체

`probe_rights()`와 후보별 부분 등록은 폐기됐다. 화면의 검증은 `validate_rights_batch()`, 실제 등록은 `save_rights_batch()`를 사용한다. 둘 다 PDF 한 건에 포함된 전체 권리 배열을 입력으로 받는다.

`validate_rights_batch()`는 실제 insert 경로와 제약을 사용하되 서브트랜잭션을 되돌리고 결과만 반환한다. `save_rights_batch()`는 한 SQL 문장의 배치 INSERT로 전체 성공 또는 전체 실패를 보장한다.

### D-29 — 단일 회사 온프레미스 경계는 유지, evidence 구조는 대체

회사 간 격리는 tenant 컬럼이 아니라 설치 인스턴스와 DB 경계가 담당한다. `team`은 PIN 관리용 신규 개념이며 tenant의 리네이밍이 아니다. 다른 테이블에 `team_id`를 전파하거나 충돌키에 넣지 않는다. RLS 연동은 SER-002 범위다.

candidate evidence 1:N 구조는 D-30에서 `rights_grant.evidence JSONB`로 대체됐다. 필수 키는 `legal_right`, `exploitation_mode`, `territory`, `period`, `exclusivity`이고 각 값에는 비어 있지 않은 `source_quote`가 필요하다.

### D-30 — 계약서 단위 all-or-nothing과 권리 계보

- `contract`는 계약 업무 건이고 `contract_history`는 PDF 한 건에 대응하는 세대이자 판정 기록이다.
- `applied` 세대는 추출 권리가 모두 `rights_grant`로 등록된다.
- 하나라도 충돌하면 해당 세대는 `conflicted`로 저장되고 `conflict_report`를 남기며 grant는 0행이다.
- `rights_grant`는 `active | terminated` 2단계 상태다.
- `content_asset`이 실제 판정 대상이다. 시리즈·시즌·에피소드·에디션을 표현하지만 상하위 asset 간 포함 충돌은 현재 판정하지 않고 ID 완전 일치만 비교한다.
- 최초 등록의 `lineage_id`는 자기 ID다. 개정판은 `(content_asset_id, territory, legal_right, exploitation_mode)` 자연키로 이전 active grant를 매칭해 계보를 승계한다. 매칭이 없거나 모호하면 새 lineage를 시작한다.
- 개정판이 성공하면 이전 등록 세대의 active grant를 `terminated/superseded`로 전환한다.
- 계약 업무 상태는 `draft | signed | cancelled` 세 단계다.
- `ip_alias`, `content_asset`, `team`, i18n label 테이블을 신설했다.

### D-31 — 계약 초안도 active grant로 권리를 예약한다

계약서의 업무 상태는 `contract.status`, 권리의 충돌 슬롯 점유 상태는
`rights_grant.status`가 담당한다. 따라서 초안 저장은 `contract.status='draft'`와
`rights_grant.status='active'`의 조합이며, 별도의 grant draft 상태를 만들지 않는다.

`contract_history.version`은 업로드 순번 정수이며 화면에서 v1, v2로 표현한다. 초안과
최종본 구분은 `document_kind(draft | final)`, DB 반영 결과는
`status(applied | conflicted)`로 분리한다.

`save_rights_batch(..., p_document_kind => 'draft')`는 applied history와 active grant를
저장하면서 contract를 draft로 유지한다. 다른 계약은 이 grant와 충돌한다. final 문서가
applied되면 contract를 `signed`로 전환하며 grant 상태는 바꾸지 않는다. 계약이
`cancelled`로 바뀌면 active grant는 `terminated/cancelled`로 종료된다.
확정 권리 조회는 `confirmed_rights_grant` view를 사용하며 contract가 `signed`인 active
grant만 반환한다.

취소·해지·협의 결렬은 모두 `cancelled`로 수렴한다. 이 셋을 구분해야 하면 contract
status를 늘리지 않고 별도 cancellation reason으로 모델링한다. cancelled는 종결
상태이므로 draft나 signed로 되돌릴 수 없다.

### D-32 — 임시 DB를 별도 인스턴스로 분리하고 비동기 추출 파이프라인 도입

**정정(D-33)**: 아래 "별도 DB 인스턴스" 전제는 팀이 "인스턴스"를 스키마
레벨로 오해한 것이었다. 실제로는 같은 `mindex` DB 안 `staging` 스키마
분리다. 비동기 파이프라인 자체(3테이블·큐·상태전이)는 이 D-32 그대로
유효하고, 물리 배치 위치만 D-33이 정정한다.

OCR·LLM 추출이 계약서 한 건에 50~60초 걸려 요청 안에서 끝낼 수 없다. P1은
운영 DB 인스턴스 안 `staging` 스키마를 제안했지만, 팀 논의로 **별도 DB
인스턴스(`mindex_staging`)**로 분리하기로 확정했다. 근거와 대가·유실방지
분석은 `docs/mindex-임시DB-비동기파이프라인.html` 전체를 따른다.

- `mindex_staging`은 `pdf_blob`(암호화 PDF 원본) · `extract_job`(큐 겸 상태:
  `QUEUED|RUNNING|DONE|FAILED`, `FOR UPDATE SKIP LOCKED`로 워커가 폴링) ·
  `extract_result`(AI 추출 결과 전체를 `payload jsonb` 하나로 보관) 3테이블뿐이다.
  기존 `pdf_cache.dbml`의 5테이블(`pdf_cache`/`contract_extraction`/`party`/
  `rights_grant`/`payment`/`evidence`, 필드별 정규화) 설계는 이걸로 대체됐다 —
  확정 전 검토용 데이터라 정규화할 이유가 없고, 확정된 값만 운영 DB
  `rights_grant`로 넘어간다.
- 운영 DB `contract`에 `source_tmpid uuid UNIQUE`를 신설했다. 별도 인스턴스라
  실제 FK는 못 걸고, 같은 `tmpid`로 두 번 확정되는 것을 UNIQUE 제약으로
  차단하는 게 유일한 방어다. `save_rights_batch()`에 `p_source_tmpid` 인자를
  추가해 값을 받으며, 이 기록은 SAVEPOINT 밖(=배치 INSERT 성공/충돌 여부와
  무관)에서 이뤄진다.
- `extract_job.consumed_at`은 운영 DB 확정이 끝났다는 사실을 임시 DB 쪽에
  표시하는 컬럼이다. 확정(운영 DB)과 임시 정리(임시 DB)를 한 트랜잭션으로
  묶을 수 없어서 생겼다 — 정리는 별도 트랜잭션이고, TTL 7일 배치가
  `consumed_at`이 찍힌 행과 오래된 `FAILED` 행을 최종적으로 청소한다.
- 화면의 확인·수정 단계(사용자가 추출 결과를 검토·수정)는 DB에 접근하지
  않는다. 수정값은 화면이 들고 있다가 확정 요청 한 번에 넘긴다 — 이탈하면
  수정값은 사라지지만 `extract_result`의 원본 추출 결과는 `DONE` 상태로
  남아 다시 불러올 수 있다.
- 인프라: `docker-compose.yml`의 `pdf-cache-db` 서비스/컨테이너/볼륨과
  `.env.example`의 `PDF_CACHE_DB_*`는 각각 `staging-db`/`STAGING_DB_*`로
  이름을 바꿨다. 스키마 파일 위치는 `sql/pdf_cache_init/`→`sql/staging_init/`.
  **(D-33에서 다시 정정 — 아래 참고)**
- `mindex_staging`에 최소권한 NOLOGIN 롤 3개(`staging_worker`,
  `staging_confirm_api`, `staging_cleanup`)를 신설했다(SER-002). 확정 API 쪽
  롤에는 `pdf_blob` 권한을 의도적으로 안 줬다 — 확정 단계는 tmpid로
  `extract_result`를 읽어 운영 DB 저장 쿼리를 만드는 데 원본 PDF 바이트가
  필요 없다. 이 역할 분리 원칙은 D-33에서도 그대로 유지, 스키마 레벨
  GRANT로 옮겨졌을 뿐이다.

### D-33 — D-32 정정: 별도 인스턴스가 아니라 같은 DB의 스키마 분리

팀장이 새 다이어그램(`OpenSQL Instance → mindex DB → public/staging 두
스키마`)을 공유하며 D-32의 "별도 DB 인스턴스" 전제가 팀의 오해였음을
확인했다. **실제 확정 구조는 하나의 `mindex` DB 안에 기존 `public`
스키마와 신설 `staging` 스키마(`pdf_blob`/`extract_job`/`extract_result`)뿐이다.**
`public`의 기존 19개 테이블은 옮기지 않는다 — "master 스키마"라는 다이어그램
표현은 `public`을 부르는 이름일 뿐, 실제로 새로 만드는 스키마는 `staging`
하나다.

- **`contract.source_tmpid`는 실제 FK다**: `REFERENCES staging.extract_job(tmpid)
  ON DELETE SET NULL` (`sql/init/06_staging_schema.sql`, `contract`가 이미
  존재하는 `01_schema.sql` 이후 ALTER로 붙인다). 같은 DB라 가능해졌다.
  `staging.extract_job`에 없는 tmpid로 확정을 시도하면 이제
  `ForeignKeyViolation`으로 걸러진다 — 별도 인스턴스 가정 때는 없던
  참조 무결성 보장이다. TTL 정리로 `extract_job`이 삭제되면
  `contract.source_tmpid`는 `NULL`로 풀린다(CASCADE 아님 — 정리 배치가
  이미 확정된 `contract` 행을 건드리면 안 된다).
- **staging 스키마 권한의 "insert, select만 허용"은 일반 접근 기준값이고,
  워커·정리 배치는 예외다.** D-32에서 설계한 3-롤 구조를 스키마 레벨
  `GRANT`로 그대로 옮긴다 — worker(SELECT+UPDATE+INSERT), confirm_api(SELECT
  뿐 + `extract_job.consumed_at` UPDATE), cleanup(SELECT+DELETE). 세 롤 모두
  `GRANT USAGE ON SCHEMA staging`이 먼저 필요하다(별도 DB일 땐 불필요했던
  권한). `sql/init/07_staging_roles.sql`.
- 인프라 단순화: `docker-compose.yml`의 `staging-db` 서비스/컨테이너/볼륨,
  `.env.example`의 `STAGING_DB_*`를 전부 제거했다 — 같은 `DATABASE_URL`로
  `staging.*`까지 접근한다.
- 문서 정본 통합: 같은 물리 DB이므로 DBML도 한 Project여야 FK가 이어진다.
  `docs/mindex_staging.dbml`(별도 Project)을 삭제하고 `staging.*` 테이블을
  `docs/mindex_remastered.dbml`에 스키마 접두사로 합쳤다.
- 새로 열린 질문(O-15): 같은 DB가 되면서 확정(⑧)과 임시 정리(⑨)를 이론적으로
  한 트랜잭션으로 묶을 수 있게 됐다. 이번 정정 범위에서는 파이프라인 단계
  구조(`mindex-임시DB-비동기파이프라인.html` §3) 자체를 재설계하지
  않았다 — 팀 논의 필요.

### D-34 — ⑥·⑦ 재설계: verify가 수정본을 staging에 반영하고 저장된 값으로 판정한다

D-32/D-33의 파이프라인은 ⑥(사용자 확인·수정)을 "DB 접근 없음"으로, 수정값은
"화면이 들고 있다가 ⑧에서 한 번에 넘긴다"로 정의했다. 팀장 확인으로 이 두
단계를 바꾼다.

- **`POST /contracts/verify`가 `tmpId` + `patch`를 받는다.** patch는 화면이
  보는 DTO shape의 JSON Merge Patch(RFC 7386)다. 서버가 저장된 값 위에 얹어
  `staging.extract_result`에 **먼저 커밋**한 뒤, 그 저장된 값으로
  `validate_rights_batch()`를 부른다. 판정은 종전대로 롤백되지만 수정본은 남는다.
  기존의 전체 body 직접 호출 경로도 그대로 받는다(수기 등록·테스트).
- **`payload`를 덮어쓰지 않고 `edited` 키를 더한다.** `staging.extract_result.payload`는
  워커 원본(`raw.contract.*`, 필드마다 `field_status` 래퍼)이고 화면이 보는 건
  `to_upload_result()`가 만든 평탄한 DTO다. **그 변환은 단방향·손실이 있다** —
  워커 코드가 접히고(`EXHIBITION`·`PERFORMANCE` → `PUBLIC_PERFORMANCE`) territory
  그룹이 국가로 전개된다. 역변환기를 만들 수 없어 DTO를 payload에 그대로 덮어쓰면
  `to_upload_result()`가 `raw.contract`를 못 찾아 재조회 자체가 깨진다. 그래서
  `{raw, validation, edited}` 구조로 두고 `GET /extract/{tmpid}`는 `edited`가 있으면
  그걸 돌려준다. 트레이드오프: 컬럼은 안 늘었지만 payload 한 행이 커진다.
- **⑧ 확정이 B안대로 동작한다(미구현 보완).** `mindex_staging DB 설명서` §3 ⑧이
  "tmpid로 `extract_result`를 읽어 저장 쿼리를 만든다"로 확정돼 있었는데 코드는
  요청 body만 쓰고 있었다(A안). 이제 `tmpId`가 오면 서버가 `edited`(없으면
  `raw`)를 읽어 배치를 만든다. 화면은 `rights`를 되보내지 않아도 된다.
- **`rights` 배열은 부분수정하지 않고 통째로 교체한다.** RFC 7386의 배열 규정
  그대로다. staging payload의 권리 행에 안정적인 식별자가 없어 원소 단위 병합
  규칙을 세울 근거가 없다.

### D-34b — 계약 원본 PDF는 서버 내부 디렉터리에 둔다 (O-12 일부 해소)

object storage는 도입하지 않는다. 확정(⑧) 시점에 `staging.pdf_blob.data`를
`CONTRACT_STORAGE_DIR`(기본 `./data/contracts`) 아래
`{contract_id}/{history_id}.pdf`로 쓰고, `contract_history.file_path`에는
**저장소 기준 상대 경로**만 남긴다. 디렉터리를 옮겨도 기존 행이 살아있게 하려는
것이다. `file_hash`는 서버가 원본 바이트에서 SHA-256으로 계산한다.

- **경로는 서버가 정한다. 요청의 `filePath`·`fileHash`는 staging 경로에서
  무시된다.** 종전에는 `contract_history.file_path`가 클라이언트가 보낸 자유
  문자열이었고 `GET /contracts/{id}/file`이 그 값에 `os.path.isfile()`을 걸어
  그대로 내려줬다 — `/etc/passwd` 같은 경로로 확정한 뒤 조회하면 서버 파일이
  그대로 나가는 **임의 파일 읽기**였다. 이제 읽을 때도
  `resolve_contract_pdf()`가 저장소 경계 밖(절대 경로·`..`)을 거부한다. 과거에
  자유 문자열로 들어간 행도 같은 이유로 `NO_SOURCE_FILE`이 된다.
- 부수 효과로 **세대별 원본 조회가 가능해졌다.** 세대마다 파일이 남으므로
  `GET /contracts/{id}/file?historyId=N`이 성립하고, staging TTL 7일 삭제와도
  무관해진다.
- O-12의 남은 부분: TTL 정리 배치는 여전히 미구현이고, object storage 전환은
  이 디렉터리를 어댑터로 바꾸는 후속 작업으로 남는다.

### D-34c — `staging_confirm_api` 롤의 권한 경계를 두 군데 넓혔다

D-33에서 확정 API 롤은 `extract_result` SELECT + `extract_job.consumed_at`
UPDATE만 갖고 있었고, `pdf_blob`은 "확정 단계에 PDF 원본 바이트는 필요 없다"며
의도적으로 막아뒀다. D-34로 둘 다 필요해졌다.

- `GRANT UPDATE ON staging.extract_result` — 검증이 수정본을 반영해야 한다.
  `payload` 전체를 UPDATE하므로 컬럼 단위로 좁힐 수 없다. 애플리케이션이 `edited`
  키만 갱신하고 `raw`는 건드리지 않는 것으로 대신한다(코드·주석으로 강제).
- `GRANT SELECT ON staging.pdf_blob` — 확정이 원본을 서버 저장소로 옮겨야 한다.

P-4(애플리케이션을 우회해도 DB 무결성 유지) 기준에서는 후퇴다. `raw` 보존이
DB 제약이 아니라 애플리케이션 규약에만 의존하게 됐다는 점이 특히 그렇다.
컬럼 단위로 좁히려면 `edited`를 별도 컬럼으로 분리해야 하는데, payload 한
컬럼 유지가 이번 결정이라 후속 과제로 남긴다.

### D-35 — IP 자산(`content_asset`) 수정은 행 단위 별도 엔드포인트로 연다

§14(`PATCH /ips/{id}`)에 "자산 수정은 이 API 범위가 아닙니다"로 닫아뒀던 것을
연다. `content_asset`은 IP 안에서 권리를 걸 수 있는 범위 단위(화면 라벨 "권리
대상")이고 판정 원자 단위의 한 축이라 막아뒀지만, 권리가 걸리지 않은 자산까지
못 고치는 건 과했다.

- **`PATCH /ips/{id}`에 `assets`를 넣지 않는다.** 등록 API의 `assets`는 전체
  교체(DELETE 후 INSERT)라 그대로 수정에 붙이면 빈 배열이 기존 자산을 지운다.
  대신 행 단위로 연다 — `POST /ips/{id}/assets`(201),
  `PATCH /ips/{id}/assets/{assetId}`(200), `DELETE /ips/{id}/assets/{assetId}`(204).
  배열 전체를 보내는 경로가 없으므로 그 사고가 구조적으로 불가능하다(§18).
- **권리가 걸린 자산은 읽기 전용이다.** `rights_grant`가 참조하면 PATCH·DELETE
  모두 `409 ASSET_IN_USE`. 이미 판정된 권리의 대상 범위가 사후에 바뀌면 과거
  판정이 조용히 무효가 되기 때문이다. `terminated` 권리도 센다 — 종료됐어도
  판정 이력은 남는다.
- **IP의 마지막 자산은 지울 수 없다.** `ensure_default_content_asset()` 트리거가
  IP 생성 시 `SERIES_ALL` 한 행을 보장하는 이유가 "모든 권리 등록이 유효한
  `content_asset_id`를 갖도록"인데, 마지막 행이 사라지면 `save_rights_batch()`의
  기본 asset 조회가 깨진다. 같은 `409 ASSET_IN_USE`이되 `details`로 구분한다
  (`rightsGrantCount` / `assetCount`).
- 부분 수정은 **기존 행과 병합한 뒤** scope 정합성을 검증한다(`AssetPatch.merged_with()`).
  `scopeType`만 넓히고 `seasonNo`를 안 지우면 DB CHECK에 걸리는데, 그걸 500이
  아니라 `400 VALIDATION_FAILED`로 돌려주기 위해서다.
- `parent_id`(시리즈 → 시즌 → 에피소드 계층)는 이번 범위 밖이다. 컬럼은 있지만
  API가 쓰지 않는다.

### D-36 — 화면이 고친 계약 메타를 운영 DB에 저장한다

D-34로 `contractInfo`(계약명·체결일·금액·통화·언어)가 staging에는 남게 됐는데,
거기서 `public.contract`로 넘어가는 경로가 없었다. 화면 수정이 조용히 버려지고
있었다 — 이번에 생긴 문제가 아니라 원래 있던 구멍이다.

- **`save_rights_batch()`는 건드리지 않는다.** P2 소유 DB 함수이고, 저장할 네 컬럼
  (`signed_date`·`lang`·`amount`·`currency`)이 `contract`에 이미 있으므로 API가 함수
  호출 직후 같은 트랜잭션에서 평범한 `UPDATE`로 쓰면 된다. 판정과 무관한 값이라
  나중에 써도 의미가 같다.
- NULL은 "지우기"가 아니라 "기존 값 유지"다(`COALESCE`) — 화면이 일부만 고쳤을 때
  나머지를 지우면 안 되기 때문이다.
- **계약명(`title`)은 빠져 있다.** `contract`에 넣을 컬럼이 없다. 목록·상세의 `title`은
  `contract_history.file_name`(업로드 파일명)이며 그건 파일명이지 계약명이 아니다.
  `contract.title` 신설은 P2에 요청한다(→ O-16).
- **`grantor`/`grantee`를 staging 경로에서 선택으로 내렸다.** `payload.raw.contract.parties[]`에
  GRANTOR·GRANTEE가 이미 파싱돼 있고 `_party_name()`이 뽑고 있었다. 화면이 다시 보낼
  이유가 없다. 요청에 있으면 우선하고, 화면이 고쳤다면 patch의
  `contractInfo.grantor`/`grantee`로 들어온다. 둘 다 못 정하면 400이다
  (`contract.grantor`/`grantee`가 NOT NULL이라 끝내 필요하다).
- **검증과 확정이 같은 경로를 쓴다.** 종전 구현은 검증만 staging 저장값으로 판정하고
  확정은 요청 body의 `rights`를 우선해서, 화면이 둘 다 보내면 **검사한 값과 저장하는
  값이 갈라질 수 있었다.** 이제 top-level `rights`는 patch의 배열 전체 교체로 접혀
  staging에 반영되고, 확정은 항상 저장된 값을 읽는다.

`contract.amount`는 D-14 기준 애플리케이션 암호화 대상으로 표시돼 있으나 미적용이다 —
이 경로로 평문 금액이 들어가기 시작한다는 점은 O-14와 같은 성격의 미결이다.

### D-37 — 업로드 맥락을 staging에 저장하고 `mode`를 문서 종류로 좁힌다

`POST /extract`가 `mode`·`contractId`·`ipId`를 Form으로 받아 **검증만 하고 버리고**
있었다. 저장되는 건 `pdf_blob(data, filename, byte_size)`과 `extract_job(tmpid,
status)`뿐이었다. 그래서 화면 상태가 없는 진입 경로에서 맥락이 사라졌다 —
`GET /contracts`의 "처리 중" 항목은 `{tmpid, status, stage, filename, reason,
createdAt}`만 주므로 목록에서 클릭해 들어오면 `tmpid` 하나뿐이고, 브라우저를 닫았다
돌아온 경우도 같다. API설계서 §3이 "같은 tmpid로 다시 들어오면 결과를 그대로
받는다"고 약속하는 바로 그 경로다.

- **`staging.extract_job`에 `mode`·`contract_id`·`ip_id`를 저장한다.** `contract_id`와
  `ip_id`에는 **FK를 걸지 않는다** — staging이 public을 참조하는 방향은 이 스키마에
  없고(있는 건 staging 내부 FK와 `contract.source_tmpid → extract_job`뿐), 버려질
  임시 데이터가 운영 테이블을 참조하게 만들지 않기 위해서다.
  `rights_grant.lineage_id`와 같은 값 전용 컬럼이다.
- **`mode`를 `new`/`revision`/`final` 3값에서 `draft`/`final` 2값으로 좁혔다.**
  "신규냐 개정이냐"는 `contractId`의 유무가 이미 말해주므로 `mode`에 섞을 이유가
  없었다. `mode`는 문서 종류만 나타내며 `documentKind`와 같은 값 집합이 된다.
- **부수 효과로 표현력이 늘었다.** `final` + `contractId` 없음 = **신규 계약의
  서명본**이 표현된다. 예전 3값 체계에서는 `final`이 기존 계약을 전제해(그래서
  `contractId`를 필수로 요구해) 이미 서명된 계약서를 처음 등록할 때도 초안으로 한 번
  올린 뒤 다시 올려야 했다. 같은 이유로 "revision/final은 contractId·ipId 필수"
  검증도 없앴다.
- **5·6번이 `contractId`·`ipId`·`documentKind`를 생략할 수 있다.** 요청에 있으면
  우선하고, 없으면 `extract_job`에 저장된 값을 쓴다. 화면이 아무것도 안 들고 있어도
  `tmpId` 하나로 검증·확정이 된다.

이름은 `mode`로 유지한다. 값 집합이 `documentKind`와 같아졌으니 `document_kind`로
바꾸는 편이 정확하지만, 팀이 이미 쓰고 있는 이름이라 혼동 비용이 더 크다고 봤다.

### D-38 — `staging.pdf_blob`·`extract_job`에 INSERT 권한을 가진 롤이 없다 (미해소)

`07_staging_roles.sql`의 INSERT GRANT는 `extract_result`(`staging_worker`) 하나뿐인데
`POST /extract`는 `pdf_blob`과 `extract_job` 둘 다 INSERT한다. 접근 주체를 셋으로
설계하면서(워커·확정 API·정리 배치) **업로드 주체가 빠졌다.**

지금은 앱이 `DATABASE_URL`의 소유자 계정으로 붙어 모든 권한을 갖고 있어 드러나지
않는다. 롤은 전부 `NOLOGIN`이고 실제 로그인 계정에 묶는 건 배포 책임이라
(D-32/D-33) 아직 적용되지 않았다. **SER-002를 실제로 적용하는 순간 업로드가 막힌다.**
`staging_confirm_api`에 INSERT를 더할지 `staging_upload_api`를 새로 만들지는 P2 판단
사항이며, 요청은 전달했다.

### D-39 — 검색은 현재 세대의 조항만 본다

`contract_chunk`는 세대(`contract_history`)마다 쌓이고 구세대 행이 지워지지 않는데,
15번 검색의 청크 조회가 `WHERE ch.contract_id = ANY(:cands)`뿐이라 **개정판에서 이미
대체된 옛 조항이 그대로 검색 결과로 잡혔다.** 사용자에게는 지금 유효하지 않은 문구가
근거(snippet)로 보인다.

`ch.contract_history_id = contract.current_history_id` 조건을 더한다.
`current_history_id`는 `validate_contract_signing()` 트리거가 applied 세대만
가리키도록 강제하고, 후보는 `confirmed_rights_grant`(= `contract.status='signed'`)에서
나오므로 이 값이 NULL인 계약은 애초에 후보에 들어오지 않는다 — 별도 폴백이 필요 없다.

구세대 청크를 지우지는 않는다. 세대별 원문 조회(D-34)와 같은 이유로 이력은
보존하되, **검색 대상에서만 뺀다.**

### D-40 — 검색 응답에 조항 본문을 싣지 않는다

15번 검색의 `snippets[].text`는 **계약서 조항 원문**이었다. 같은 원문을 돌려주는
9번(`GET /contracts/{id}/file`)은 PIN 세션을 요구하는데 15번은 열려 있어서,
인증 없이 계약서 본문을 조각으로 꺼낼 수 있었다.

처음에는 15번에 `require_session`을 붙였다가 방향을 바꿨다. **화면이 근거문을
표시하지 않기로 했으므로 응답에서 아예 빼는 쪽이 맞다** — 화면에 없는 것을 API가
내보내지 않는다. 표시 계층에서 감추는 것은 방어가 아니며(`curl` 한 줄이면 그대로
나온다), 반대로 응답에서 빼면 인증을 걸 이유 자체가 사라진다.

- `Snippet`에서 `text`를 제거했다. `chunkId`·`clauseNo`·`page`·`similarity`는 남긴다 —
  "어디서 얼마나 걸렸는지"는 메타데이터다.
- `require_session`은 붙이지 않는다. 7번 목록·12번 IP 목록과 같은 기준
  (메타데이터는 열고, 원문·이력 열람만 PIN)이 유지된다.
- 본문은 여전히 **랭킹에는 쓴다.** `word_similarity(lower(ch.chunk_text), :q)`로 어휘
  점수를 내고, 임계값을 넘는 근거가 하나도 없는 계약을 빼는 판단도 본문 기준이다.
  서버 안에서만 보고 밖으로 내보내지 않는다.

**PIN이 보장하지 않는 것도 함께 기록해 둔다.** PIN은 "이 설치에 접근할 자격이 있나"만
확인한다. `team`은 PIN 관리 전용 테이블이고 `team_id`를 도메인 테이블에 전파하지
않으므로(D-29/D-30, 단일사 온프렘) **토큰 안의 팀 정보는 조회 범위를 가르지 않는다** —
라우터들이 `_team: str = Depends(require_session)`으로 받아 그대로 버린다.
멀티테넌트가 필요해지면 스키마에 `team_id` 전파와 RLS가 따로 필요하고,
`app/security/rls.py`가 그 빈자리로 남아 있다.

## 미결

### O-06 — 요구사항별 평가 건수 불일치

요구사항 문서와 합성 시나리오 문서의 정상·충돌·검수 건수 및 성공 기준을 팀에서 확정해야 한다.

### O-07 — 작품·자산·권리사슬의 고급 판정

별칭 저장은 구현됐지만 외부 ID 기반 작품 동일성, asset 상하위 포함 충돌, grantor/grantee·sublicense, 파생 IP 판정은 미구현이다.

### O-12 — 등록 전 산출물 보관 (D-32로 일부 해소, D-34b로 저장 위치 확정)

D-32로 위치·수명 자체는 정해졌다 — `staging.pdf_blob`/`extract_job`/
`extract_result`에 보관하고, 확정되면 `consumed_at` 기록 후 TTL 7일 배치가
정리하며, 확정 안 된 `FAILED`·방치 행도 같은 배치가 청소한다. 남은 미결은
TTL 7일 배치 자체(스케줄러·구현 위치)가 아직 코드로 존재하지 않는다는 점,
그리고 object storage(PDF 원본을 DB `bytea`가 아니라 별도 스토리지에 둘지)는
D-32 문서 범위 밖이라는 점이다.

### O-13 — 다중 territory 표현과 스냅샷

`JP + TW`, `Worldwide except US` 같은 논리 범위의 원문 표현, 국가 전개 시점, 그룹 버전 정책이 미결이다. JSONB를 충돌 판정의 정본으로 쓰지 않고 국가별 원자 행을 사용하는 원칙만 확정돼 있다.

### O-14 — staging.extract_result.payload 암호화 여부 (D-32·D-33)

`staging.pdf_blob.data`는 "암호화된 바이트"라고 명시돼 있는데
`staging.extract_result.payload`는 암호화 언급이 없다. 이 payload에는
evidence의 원문 인용(계약서 exact text)이 그대로 들어있고, B안(확정 API가
tmpid로 이걸 읽어 운영 쪽에 병합)이 채택되면 평문 payload가 그대로
`rights_grant.evidence`까지 이어진다. D-14는 애플리케이션 레이어 암호화
원칙이라 이 판단도 정책 확인이 필요하다 — 스키마 컬럼 타입 자체는 안 바뀔
수 있지만(jsonb 그대로), 암호화 대상 여부는 팀/보안 담당 확인 필요. 같은
DB의 별도 스키마로 정정됐다고 이 이슈의 실질(원문이 평문으로 존재)이
바뀌지는 않는다.

### O-15 — 확정(⑧)·임시 정리(⑨) 트랜잭션 통합 여부 (D-33)

D-32 설계 시점엔 별도 인스턴스 가정이라 ⑧(운영 DB 확정)과 ⑨(임시 DB 정리)를
물리적으로 한 트랜잭션으로 묶을 수 없었다. D-33으로 같은 DB의 스키마
분리임이 확인되면서 이론적으로는 한 트랜잭션으로 묶을 수 있게 됐다 —
그러면 `mindex_staging DB 설명서.md` §7의 "⑧ 커밋 직후·⑨ 직전" 유실 구간
자체가 사라진다. 반대로 확정 트랜잭션이 길어지고 워커/API 프로세스 경계와
어긋난다는 트레이드오프가 있다. 이번 D-33 정정 범위에서는 파이프라인 단계
구조를 그대로 유지했고, 통합 여부는 팀 논의가 필요하다.

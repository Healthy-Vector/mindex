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
- `mindex_staging`에 최소권한 NOLOGIN 롤 3개(`staging_worker`,
  `staging_confirm_api`, `staging_cleanup`)를 신설했다(`sql/staging_init/
  02_roles.sql`, SER-002). 확정 API 쪽 롤에는 `pdf_blob` 권한을 의도적으로
  안 줬다 — 확정 단계는 tmpid로 `extract_result`를 읽어 운영 DB 저장
  쿼리를 만드는 데 원본 PDF 바이트가 필요 없다. 실제 로그인 계정·비밀번호는
  이 파일에 없다 — `.env`와 같은 이유로 커밋 대상이 아니며, 배포 시
  `GRANT <role> TO <login_role>`로 소속시키는 건 배포(ops/P1) 책임이다.

## 미결

### O-06 — 요구사항별 평가 건수 불일치

요구사항 문서와 합성 시나리오 문서의 정상·충돌·검수 건수 및 성공 기준을 팀에서 확정해야 한다.

### O-07 — 작품·자산·권리사슬의 고급 판정

별칭 저장은 구현됐지만 외부 ID 기반 작품 동일성, asset 상하위 포함 충돌, grantor/grantee·sublicense, 파생 IP 판정은 미구현이다.

### O-12 — 등록 전 산출물 보관 (D-32로 일부 해소)

D-32로 위치·수명 자체는 정해졌다 — `mindex_staging.pdf_blob`/`extract_job`/
`extract_result`에 보관하고, 확정되면 `consumed_at` 기록 후 TTL 7일 배치가
정리하며, 확정 안 된 `FAILED`·방치 행도 같은 배치가 청소한다. 남은 미결은
TTL 7일 배치 자체(스케줄러·구현 위치)가 아직 코드로 존재하지 않는다는 점,
그리고 object storage(PDF 원본을 DB `bytea`가 아니라 별도 스토리지에 둘지)는
D-32 문서 범위 밖이라는 점이다.

### O-14 — extract_result.payload 암호화 여부 (D-32)

`pdf_blob.data`는 "암호화된 바이트"라고 명시돼 있는데 `extract_result.payload`는
암호화 언급이 없다. 이 payload에는 evidence의 원문 인용(계약서 exact text)이
그대로 들어있고, B안(확정 API가 tmpid로 이걸 읽어 운영 DB에 병합)이 채택되면
평문 payload가 그대로 운영 DB `rights_grant.evidence`까지 이어진다. D-14는
애플리케이션 레이어 암호화 원칙이라 이 판단도 정책 확인이 필요하다 — 스키마
컬럼 타입 자체는 안 바뀔 수 있지만(jsonb 그대로), 암호화 대상 여부는 팀/보안
담당 확인 필요.

### O-13 — 다중 territory 표현과 스냅샷

`JP + TW`, `Worldwide except US` 같은 논리 범위의 원문 표현, 국가 전개 시점, 그룹 버전 정책이 미결이다. JSONB를 충돌 판정의 정본으로 쓰지 않고 국가별 원자 행을 사용하는 원칙만 확정돼 있다.

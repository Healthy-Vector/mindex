# WORKLOG — 현재 작업 상태

개인 세션 기록이며 최신 항목만 유지한다. 설계의 현행 결정은 [`DECISIONS.md`](DECISIONS.md), 데이터 모델 정본은 [`mindex_remastered.dbml`](mindex_remastered.dbml)을 따른다.

## 2026-08-21 — D-31 계약 상태·업로드 문서 상태·권리 점유 상태 분리

- `contract.status`를 `draft | signed | cancelled`로 단순화했다. cancelled는 종결
  상태이며, 전환 시 해당 계약의 active grant를 `terminated/cancelled`로 종료한다.
- `contract_history.version`은 업로드 순번 정수로 유지하고, 초안/최종본은
  `document_kind(draft | final)`, DB 적용 결과는 `status(applied | conflicted)`로 분리했다.
- `save_rights_batch()`는 `p_document_kind`를 받아 draft/applied면 contract를 draft로
  유지하면서 active grant로 권리를 선점하고, final/applied면 contract를 signed로
  전환한다. conflicted 업로드는 기존 all-or-nothing 규칙대로 신규 grant 0건과
  `conflict_report`를 남긴다.
- `rights_grant.status`는 실제 권리 점유 상태인 `active | terminated`를 유지한다.
  `conflicted`는 `contract_history.status`와 `conflict_report`가 담당한다.
- 확정 계약의 현재 권리는 `confirmed_rights_grant` view로 분리했다.

### 검증

- Python `compileall`, pytest 66개 테스트 수집, `git diff --check`를 통과했다.
- Docker 엔진/PostgreSQL이 실행되지 않아 DB-backed pytest는 연결 단계에서 실행하지
  못했다. DB 기동 후 전체 테스트 재실행이 필요하다.

## 2026-08-21 — 현행 설명서가 SQL 동작과 맞도록 정리

- `mindex DB 설명서.md`와 `contract-registration-flow.md`의 evidence 인용 키를 실제 DB CHECK가 검사하는 `quote`로 통일했다.
- 기존 contract 명시적 잠금이 없고 `MAX(version) + 1`을 사용하는 현재 구현과, 기본 content asset이 신규 IP INSERT trigger로만 생성되는 범위를 문서에 반영했다.
- `change_log` 생성은 구현됐지만 재청킹·재임베딩 worker의 실제 처리 함수는 미구현임을 명시했다.

## 2026-08-20 (3) — D-30 문서 동기화

### 한 일

- `docs/mindex_remastered.dbml`을 SQL의 D-30 구조로 전면 교체했다. candidate/evaluation 계층과 삭제 테이블을 제거하고 `ip_alias`·`content_asset`·`team`·i18n label·`contract_history`·재정의된 `rights_grant`를 반영했다.
- `docs/mindex DB 설명서.md`를 19개 현행 테이블, 2축 EXCLUDE/trigger 판정, evidence JSONB, 배치 검증·저장, lineage·개정판 흐름 중심으로 다시 작성했다.
- `docs/contract-registration-flow.md`를 `validate_rights_batch()`/`save_rights_batch()` 기반 계약서 단위 all-or-nothing 프로세스로 교체했다.
- `docs/DECISIONS.md`에 D-30을 신설하고 D-19·D-25·D-28의 대체, D-26의 부분 폐기, D-27 2축 유지, D-29 단일 회사 경계 유지/evidence 구조 대체를 명시했다.
- 제안서와 다르게 확정한 사항을 문서에 명시했다: `legal_right × exploitation_mode` 2축 유지, `statutory_right`/`right_mapping` 삭제, `contract_version` 무대체, `team`은 tenant가 아닌 PIN 관리용 독립 개념.

### 검증

- DBML과 `sql/init/*.sql`의 테이블 수가 각각 19개로 일치한다.
- 양쪽 테이블 이름 집합을 정렬 비교해 차이가 없음을 확인했다.
- 대상 문서의 구세대 객체명은 "삭제/대체 설명" 외에 활성 구조나 실행 흐름으로 남지 않았다.
- 현재 Codex 실행 환경에는 `docker`와 `pytest` 명령이 없어 실제 `docker compose down -v && docker compose up` 및 테스트 재실행은 하지 못했다. SQL 구현 자체는 직전 세션의 PostgreSQL 16.2 검증과 61 tests 통과 상태이며, Docker 환경 재검증은 여전히 필요하다.

---

## 2026-08-20 (2) — 스키마 전면 재설계 구현: candidate 계층 제거 + 계약서 단위 all-or-nothing

### 배경

`docs/final/mindex-erd-제안안-비교및파이프라인.md`(팀 제안서)를 검토하고 구조 기준으로 채택했다. 현재 스키마(D-19~D-29)는 AI 후보(`rights_grant_candidate`)를 스테이징하고 건별 개별 승인/거부하는 모델인데, 제안서는 "PDF 한 건 = 판정 한 건"인 계약서 단위 all-or-nothing 모델을 제시했다. 조사 결과 이 파이프라인은 `app/`·`service/`·프론트엔드 어디에도 구현돼 있지 않아(전부 stub) `sql/init/*.sql`과 `tests/`로만 범위가 한정됐다.

### 회의에서 확정한 방향 (제안서와 다르게 판단한 지점 포함)

- **구조**: 제안서 기준 채택 — candidate 스테이징 계층 삭제, 계약서 단위 all-or-nothing, 이력 테이블 통합, evidence JSONB화, `content_asset` 신설
- **판정 로직**: 제안서를 따르되 **2축 판정(legal_right × exploitation_mode, D-27)은 유지**. 제안서의 단일 `rights_type` 축(EXCLUDE 등호 비교)은 채택하지 않았다 — JA-C05류 상위-하위 포함관계 버그 재발 방지가 이유. `evidence` JSONB도 제안서의 단일 `rights_type` 키 대신 `legal_right`/`exploitation_mode` 각각의 키로 분리
- **네이밍**: 제안서가 새로 만드는 것(`content_asset`/`lineage_id`/`conditions_raw`/`evidence`/`contract_history`/`ip_alias`/`team`)은 제안서 이름 그대로. 기존 걸 단순 리네이밍하려는 항목(`territory_group_member`→`_country` 등)은 **기존 이름 유지**하고 리네이밍하지 않았다. `team`은 tenant 리네이밍이 아니라 PIN 관리용 신규 개념이라 별도 신설(다른 테이블에 `team_id` 전파 안 함, EXCLUDE 키에도 안 넣음 — SER-002 RLS 연동은 범위 밖)
- **right_mapping/statutory_right**: 제안서 11번대로 **둘 다 삭제**. 현재 `right_mapping`이 내던 관할 typicality/advisory 경고(WARNING/AMBIGUOUS_CLAUSE, 예: JP+TRANSMISSION+SVOD)는 이번 라운드에서 함께 사라졌다 — 필요해지면 별도 재설계
- **범위 제외**: 오늘 아침 브리핑의 다중 territory(JSONB scope, Worldwide except X 등) 문제는 이번 라운드에서 다루지 않았다. `territory`는 현행대로 `country` 단일 CHAR(2) FK 유지 — **아래 원래 08-20 항목의 안건은 여전히 미결**
- **final 계약 개정 정책**: DB가 막지 않는다. `status='final'` 계약에 새 PDF가 올라올 때 판단은 앱 레이어 책임
- **contract_version**: 완전 삭제, 대체 없음. `counterparty`/`amount` 등 메타데이터 수정 감사이력이 필요해지면 별도로 새로 만들어야 한다(현재는 없음)
- **lineage_id 매칭**: `(content_asset_id, territory, legal_right, exploitation_mode)` 자연키 자동 매칭, 실패/모호 시 조용히 새 lineage로 시작 (자동 채택)

전체 설계 근거와 대안 비교는 계획 문서 `/Users/mac/.claude/plans/hidden-jumping-gem.md`에 있다(세션 로컬 경로, 저장소 밖).

### 구현

- `sql/init/01_schema.sql` — 전면 재작성. 삭제: `rights_grant_candidate`·`candidate_evidence`·`rights_evaluation`·`rights_evaluation_reason`·`conflict_resolution`·`rights_grant_history`·`contract_version`·`statutory_right`·`right_mapping`·`contract_document`(→`contract_history`로 흡수). 신설: `ip_alias`·`content_asset`·`team`·`country_label`·`territory_group_label`. `rights_grant` 재정의(`lineage_id`/`evidence` jsonb/`conditions_raw`/2단계 status). EXCLUDE(`no_exclusive_overlap`)에 `contract_id WITH <>` 추가, 락 키를 `ip_id`→`content_asset_id`로 변경, 2축 span `&&` 비교는 그대로.
- `sql/init/02_conflict_rules.sql` — `validate_rights_batch()`(probe_rights 대체)·`save_rights_batch()`(register_candidate 대체)·`attempt_rights_batch_insert()`·`terminate_rights_grant()`(conflict_resolution/waiver 대체, 트리거 아닌 직접호출)·`default_lineage_id()`·`is_valid_evidence()`·`ensure_default_content_asset()` 신설. `check_exclusivity_conflict()`/`validate_contract_finalize()` 수정(대폭 축소). `classify_candidate`/`evaluate_candidate`/`register_candidate`/`probe_rights`/`rights_advisory`/`record_rights_grant_history`/`validate_resolution_target`/`apply_waiver_termination`/`snapshot_contract_version` 삭제. `sync_rights_grant_spans`/`guard_taxonomy_frozen` 무변경.
- `sql/init/03_reference_data.sql` — `statutory_right`/`right_mapping` 시드 삭제, i18n 라벨 테이블로 재구성, `reason_code`에서 `is_blocking`/`is_review_trigger` 제거.
- `sql/init/04_vector.sql`, `05_change_log.sql`, `99_schema_meta.sql` — FK/트리거 재조준, 버전 태그 `2026-08-20.1` 추가.
- `tests/` — `conftest.py`(`make_candidate` 삭제, `make_grant`/`make_batch_row` 재작성), `test_conflict_constraint.py`(픽스처만 교체, 로직 생존), `test_probe_rights.py`/`test_reason_code_pipeline.py`(전면 재작성, 배치 성공/실패/원자성/개정판 세대전환/lineage 승계/WAIVER 재시도 커버), `test_low_confidence_registration.py`(DB 밖 개념이 되어 계약 테스트 3건으로 대체).

### 검증

- 이 세션 샌드박스에 docker가 없어 `pgserver`(pip)로 PostgreSQL 16.2 + 소스 컴파일한 `btree_gist`를 직접 띄워 검증했다 — **실제 프로젝트 `docker-compose.yml` 기준 재검증은 아직 안 됨.** 다음 작업 시작 전 `docker compose down -v` 재기동으로 한 번 더 확인 필요.
- `sql/init/*.sql` 00→99 순서로 `ON_ERROR_STOP=1` 에러 0건, nested-set 자기검증 DO 블록 통과.
- `pytest -q` **61건 전부 통과**.
- 수동 시나리오 4종 확인: 정상 배치 저장(REGISTERED), 충돌 배치(CONFLICTED + `conflict_report`에 `existing_grant_id`/`overlap_period` 포함, `rights_grant` 0행), WAIVER(`terminate_rights_grant()` 후 재제출 성공), 개정판 재등록(이전 세대 `terminated/superseded` 전환 + `lineage_id` 승계).
- 테이블 19개 (신규 4, 유지 15, 삭제 9).

### 남은 일

- **문서 갱신은 이 세션에서 하지 않았다 — `docs/mindex_remastered.dbml`, `docs/mindex DB 설명서.md`, `docs/contract-registration-flow.md` 전면 재작성은 Codex로 별도 진행 예정.** 새로 작업하는 사람은 위 "회의에서 확정한 방향"과 이 항목의 "구현" 절을 근거로 삼을 것 — 특히 제안서와 다르게 간 지점(2축 유지, right_mapping 삭제, contract_version 무대체, team 신설 사유)을 문서에 정확히 반영해야 한다.
- `docs/DECISIONS.md`도 아직 갱신 안 됨 — 새 D-30 신설 필요, D-19/D-25/D-27(2축 부분만 유효)/D-28(all-or-nothing으로 대체)/D-29(evidence 구조만 대체, tenant 관련은 유효) 상호참조 필요.
- 실제 docker-compose 환경 재검증 필요(위 검증 항목 참고).
- 다중 territory(JSONB scope) 문제는 여전히 미결 — 아래 원래 08-20 브리핑 항목 참고.

---

## 2026-08-20 — 회의 브리핑: 다중 Territory 표현과 충돌 판정

### 제기된 문제

- 현재 `rights_grant.territory CHAR(2)`는 국가 한 개만 직접 표현한다.
- 실제 계약과 시나리오에는 `JP + TW`, `Asia`, `Worldwide`, `Worldwide except US`처럼 복수 국가, 그룹, 포함·제외 범위가 존재한다.
- DB는 grant가 포함하는 국가 집합과 제외하는 국가 집합을 알아야 한다.
- 제안안은 `rights_grant.territory`를 `territory_scope JSONB`로 변경하고 `country`는 정규화용 사전으로만 사용하는 것이다.

### 검토 결론

- **문제 진단에는 동의한다.** 단일 `CHAR(2)`만으로 논리적인 계약 범위를 표현하기에는 부족하다.
- **JSONB만을 충돌 판정의 정본으로 사용하는 방안에는 반대한다.** JSONB는 계약서 표현 보존에는 적합하지만 현재 GiST EXCLUDE의 `territory WITH =`를 국가 집합 교집합 판정으로 대체하기 어렵다.
- `{"include":["JP","TW"]}`와 `{"include":["TW","JP"]}`처럼 의미가 같고 표현이 다른 값, 중복 국가, 잘못된 국가 코드, 그룹 전개 시점과 국가 집합 버전 문제가 생긴다.
- JSON 내부 국가에는 일반 FK를 직접 걸 수 없고, GIN 인덱스만으로 여러 grant 사이의 국가 집합 교집합과 나머지 판정축을 하나의 EXCLUDE로 강제하기 어렵다.

### 권장 원칙

계약상 표현과 DB 충돌 판정용 데이터를 분리한다.

```text
territory_scope / raw JSONB
= 사용자가 이해하는 계약상 지역 표현 보존

정규화된 국가 행
= DB가 실제 충돌을 판정하는 원자 단위
```

그룹은 매 조회마다 조인하지 않고 **입력·등록 시 한 번 전개한 결과를 저장**한다.

```text
Asia
→ territory_group_member 조회 1회
→ JP / KR / TW / SG ... 국가 행 저장
→ 이후 충돌 검사에서는 그룹 조인 없음
```

### 단기안 A — 국가별 `rights_grant` 행 유지

- 논리적 territory scope와 원문 JSON을 candidate 또는 별도 scope 테이블에 저장한다.
- 등록 시 scope를 국가별 `rights_grant` 행으로 전개한다.
- 기존 `territory CHAR(2)`와 EXCLUDE를 유지할 수 있어 구현 변경이 가장 작다.
- 후보 하나에서 여러 국가 grant가 생기므로 현재 `source_candidate_id UNIQUE`는 `UNIQUE(source_candidate_id, territory)` 등으로 변경해야 한다.
- 화면에서 논리적인 grant 한 건이 여러 행으로 보이지 않도록 묶음 식별자가 필요하다.

### 장기안 B — 논리 grant와 판정 allocation 분리 (권장)

```text
rights_grant
= 계약에서 사용자가 이해하는 논리적인 권리 한 건

rights_allocation
= 국가별로 전개된 DB 충돌 판정 행
```

예:

```text
rights_grant #100
territory = Worldwide except US

rights_allocation
├─ #100 / KR
├─ #100 / JP
├─ #100 / TW
└─ #100 / SG ...
```

- `rights_grant`는 `territory_scope_id` 또는 원래의 scope 표현을 보존한다.
- `rights_allocation`은 `grant_id`, `country_code`와 IP·법적 권리 span·이용형태 span·기간·독점 조건을 가진다.
- 최종 EXCLUDE는 JSONB가 아니라 `rights_allocation`에 적용한다.
- 앞으로 content scope, carve-out, holdback이 추가될 때도 같은 “논리 grant → 판정용 원자 투영” 패턴으로 확장할 수 있다.

### 반드시 정해야 할 의미

- `Worldwide`의 국가 집합은 ISO 전체인지 서비스 지원 국가인지
- `Worldwide except US`가 계약 체결 당시 국가 집합의 스냅샷인지, 이후 추가된 국가까지 자동 포함하는지
- `Asia`의 공식 구성 국가와 그룹 버전을 누가 관리하는지
- 포함과 제외가 동시에 있거나 중첩될 때 우선순위
- 원문 scope와 정규화된 국가 행이 달라지는 것을 막을 생성·갱신 주체

### 회의에서 결정할 항목

1. 단기안 A와 장기안 B 중 이번 범위에서 채택할 구조
2. JSONB는 원문 표현 보존용으로만 둘지 여부
3. `Worldwide`와 지역 그룹의 기준 국가 집합 및 버전 정책
4. 국가 전개 시점: 검증 시 임시 전개, 실제 등록 시 확정 전개
5. `source_candidate_id` 및 evidence 추적을 국가별 allocation과 어떻게 연결할지

### 현재 상태

- 이 항목은 **회의 검토안이며 아직 DECISIONS, DBML, SQL에는 반영하지 않았다.**
- 현재 구현은 국가별 원자 행과 `territory CHAR(2)`를 사용하는 D-15 구조를 유지한다.

## 2026-08-19 (4) — 계약·권리 등록 흐름 문서화

### 한 일

- `contract-registration-flow.md`를 추가해 기존 IP 선택부터 최초 PDF 임시 업로드, OCR·AI 추출, 사용자 검토, 롤백 probe, 실제 등록, 충돌 후속 처리, 계약 최종화까지 한 문서로 정리했다.
- `mindex DB 설명서.md`의 16~23장을 D-28·D-29 기준으로 교체했다. 기존의 “PDF 업로드 즉시 contract/document INSERT” 설명을 제거하고 등록 전 무커밋과 `RETURNING id` 순서를 명시했다.
- 검증 직후 UI는 저장된 evaluation 조인이 아니라 `probe_rights()` 반환값으로 구성하며, 실제 등록에서 보존된 충돌 건만 evaluation/reason 조인으로 재조회한다고 구분했다.
- 여러 후보가 섞인 계약은 정상 후보를 grant로 승격하고 blocking 후보는 candidate·evaluation·reason으로 보존하는 흐름으로 정리했다.
- `docs/README.md`에 새 프로세스 문서 링크를 추가했다.

### 구현과 검증

- `probe_rights()`의 단일 인용 파라미터를 evidence JSON 배열로 변경해 `candidate_evidence` N행을 실제 검증하도록 맞췄다.
- 빈 evidence 배열 거부와 다건 evidence 허용 테스트를 추가했다.
- `schema_meta`에 `2026-08-19.5`를 기록했다.
- 기존 DB와 볼륨을 건드리지 않고 `mindex_flow_verify` 임시 DB에 초기화 SQL 전체를 로드했다.
- 임시 DB에서 `pytest -q`를 실행해 **71건 전부 통과**했고, 검증 후 임시 DB를 삭제했다.

## 2026-08-19 (3) — 온프레미스 단일 회사 경계와 근거 다건화 (D-29)

### 결정

- 서비스가 여러 고객사를 한 DB에 수용하는 웹 SaaS가 아니라 회사 서버에 직접 설치되는 단일 회사용 제품임을 확인했다.
- 회사 격리는 설치·DB 경계가 담당하므로 `tenant`와 모든 `tenant_id`를 제거했다. 사용자 인증·역할 권한은 이 결정과 별도다.
- IP 행은 설치 회사가 관리하는 작품일 뿐 법적 소유권을 의미하지 않는다고 명시했다.
- 후보의 단일 `source_page/source_clause/source_quote`를 `candidate_evidence` N행으로 분리했다. 페이지 범위, 조항, 원문 인용을 후보별로 여러 건 보관한다.
- D-28의 등록 전 무커밋 원칙은 유지한다. 실제 등록은 `contract → contract_document → candidate → evidence → grant` 순서로 ID를 받아 한 트랜잭션에서 처리한다.

### 구현

- 정본 DBML과 `sql/init/*.sql`에서 tenant 테이블·컬럼·복합 FK·tenant 충돌 축을 제거했다.
- `candidate_evidence` 테이블과 인덱스, 페이지 범위 및 빈 인용문 방지 CHECK를 추가했다.
- `register_candidate()`에 근거 1건 이상 검증을 추가했고 `probe_rights()`가 evidence 행까지 만든 뒤 함께 롤백하도록 변경했다.
- advisory lock 범위를 `(tenant_id, ip_id)`에서 `ip_id`로 변경했다.
- 테스트 픽스처와 tenant/source 의존 테스트를 D-29 구조로 갱신하고, 근거 다건 및 무근거 등록 거부 테스트를 추가했다.
- `schema_meta`에 `2026-08-19.4`를 기록했다.

### 검증

- 기존 개발 DB와 볼륨은 건드리지 않고 `mindex_d29_verify` 임시 DB를 생성해 `sql/init/00~05, 99`를 순서대로 로드했다. 모든 SQL이 오류 없이 적용됐다.
- 임시 DB에서 `pytest -q`를 실행해 **69건 전부 통과**했다.
- DBML과 SQL의 테이블 수가 각각 **23개로 일치**함을 확인했다. tenant 제거 1개와 candidate_evidence 추가 1개가 상쇄돼 총수는 유지된다.
- 활성 스키마·코드·테스트에서 `tenant_id` 참조가 남지 않았음을 전수 검색했다. 과거 schema_meta 설명과 D-29 변경 기록의 문자열만 의도적으로 남겼다.
- 검증 후 임시 DB를 삭제했다. 기존 `mindex` DB와 Docker 볼륨은 변경하지 않았다.

## 2026-08-19 (2) — 화면 프로세스와 DB 호출 규약 확정 (D-28)

### 한 일

- 회의 확정 프로세스를 현행 스키마에 대응시켜 **D-28**로 기록했다. 원칙은 **`권리 등록` 전까지 DB에 커밋되는 것이 없다**이다. PDF 업로드와 OCR/JSON화는 P3 단계이고 DB와 무관하며, 파일은 오브젝트 스토리지에만 둔다.
- `검증`을 **INSERT 후 롤백(probe)** 방식으로 확정했다. 읽기 전용 SELECT 재구현안을 검토했다가 기각했다.
  - **EXCLUDE를 실제로 검증할 수 있다.** 읽기 전용은 EXCLUDE와 같은 조건의 SELECT일 뿐 EXCLUDE가 아니라 언젠가 갈라진다.
  - **RFP §6.3.2가 시연 구간 C에서 제약명 `no_exclusive_overlap` 노출을 요구한다(D-08).** 읽기 전용은 제약 위반을 발생시키지 않아 문구를 지어내야 한다. `constraint_reason_map`의 존재 자체가 실제 위반 경로를 전제한 설계다.
  - **판정 로직이 한 벌로 유지된다.** `evaluate_candidate()`를 그대로 호출하므로 테스트 52건이 걸린 함수를 리팩터링하지 않는다.
- 롤백을 **규약이 아니라 구조로** 강제하기로 했다. `probe_rights()` 안에서 sentinel 예외(`SQLSTATE 'MXP01'`)로 서브트랜잭션을 되돌리고, PL/pgSQL 변수가 트랜잭션 대상이 아니라는 점을 이용해 수집한 결과만 반환한다. 앱이 커밋 여부를 고를 수 없다.
- 부모 행(`ip`·`contract`·`contract_document`)도 같은 서브트랜잭션에서 만들고 함께 되돌린다. 이 값들은 껍데기가 아니라 업로드·추출 단계에서 앱이 이미 들고 있는 실제 데이터다.
- **`저장`의 목적지가 `rights_grant`이지 `rights_grant_history`가 아님**을 못박았다. 히스토리는 `rights_grant_id NOT NULL`이라 직접 INSERT할 수 없고 트리거가 쓴다.
- 예외를 명시했다 — 후보 N개 중 일부만 충돌하면 정상 건은 등록하고 충돌 건만 실제 저장한다. `conflict_resolution`이 사유 행을 FK로 가리키고 WAIVER는 며칠이 걸린다.
- 용어를 정리했다. `검토`는 "사람이 봐야 한다"는 기존 뜻을 유지하고, 화면에서 `저장` 대신 `권리 등록`을 쓴다.
- `mindex_remastered.dbml`의 `rights_evaluation` Note를 D-28에 맞춰 갱신했다.

> 검토 과정에서 읽기 전용안으로 한 번 기울었다가 되돌렸다. 당시 근거로 든 "유령 작품이 남는다"는 부모 행을 같은 트랜잭션에 넣으면 성립하지 않고, "껍데기 조립 비용"도 해당 값들이 실제 데이터라 과장이었다.

### 이번에 발견한 문제

- **`LOW_CONFIDENCE` 데드락 (D-28에서 처리 결정).** `classify_candidate()`가 `confidence < 0.85`에 `status='review'` + `LOW_CONFIDENCE`를 찍고(`02_conflict_rules.sql:270`) 이 코드는 `is_blocking=true`다(`03_reference_data.sql:387`). `register_candidate()`는 review 상태를 거부하고, `evaluate_candidate()`는 단계 (b)에서 이 사유를 그대로 옮겨 단계 (h)가 다시 review로 되돌린다. 해제 수단인 `rights_evaluation_reason.status='resolved'`는 세팅하는 코드가 없고(O-09) `conflict_resolution`은 CONFLICT가 아닌 사유를 거부한다 — **빠져나갈 경로가 없다.** 기존 테스트(`test_reason_code_pipeline.py:78`)는 review로 들어가는 것까지만 확인한다.
  - **실행으로 재현 확인했다.** `is_blocking=true`로 되돌린 상태에서 `confidence=0.42` 후보를 넣으면 INSERT 직후 `review`, `evaluate_candidate()`를 다시 돌려도 `review` 그대로, `register_candidate()`는 `candidate 행 N는 검토 상태다 (사유: LOW_CONFIDENCE)`로 거부한다.
  - `is_blocking`을 `false`로 내렸다(`03_reference_data.sql:393`). 이 프로세스는 사람 확인이 필수 단계라 "사람을 부르자"는 취지가 이미 충족된다.
- **O-08** — `rights_grant_history.snapshot`이 항상 NULL이다.
- **O-09** — `conflict_status.resolved`를 세팅하는 코드가 없다. 화면이 `status='detected'`로만 필터하면 해소된 건의 유령 사유가 잡힌다.
- **O-10** — 미승인 후보와 반려 문서의 보관 정책이 없다.
- **O-11** — `rights_grant_history`의 FK 3개가 모두 `ON DELETE CASCADE`라 문서를 지우면 감사 로그가 함께 사라진다.
- **O-12** — 등록 전 산출물(PDF 고아 객체, `raw_text`·추출 JSON의 앱 보관)의 위치와 수명이 미정이다.

### 구현과 검증

- **`probe_rights()` 신설** (`02_conflict_rules.sql` 12번 함수). 파라미터 7개 + 선택 4개를 받아 판정 결과·사유·제약명을 테이블로 반환한다. 기존 함수는 하나도 수정하지 않았다.
- **`LOW_CONFIDENCE`의 `is_blocking`을 `false`로** (`03_reference_data.sql:393`).
- **`schema_meta` 버전을 `2026-08-19.3`으로** 올렸다.
- 테스트 2개 파일 16건 추가 — `tests/test_probe_rights.py`(10건), `tests/test_low_confidence_registration.py`(4건) 및 기존 파일 보정.
- `docker compose down -v` 후 재기동해 스키마 로드 에러 없음을 확인했다. **`pytest -q` 68건 전부 통과**(기존 52 + 신규 16).
- 실측 동작 — 기존 권리 `KR/PUBLIC_TRANSMISSION/VOD/2027~2029/독점`에 대해 `KR/TRANSMISSION/SVOD/2028~2030/독점`을 검증하면:

  ```
  result_type | reason_code             | conflicting_grant_id | overlap_period          | constraint_name
  CONFLICT    | EXCLUSIVE_RIGHT_OVERLAP | 150                  | [2028-01-01,2029-01-01) | no_exclusive_overlap
  ```

  상위-하위 포함관계(R3/R4)를 양축 모두에서 잡았고, 제약명은 지어낸 문자열이 아니라 `GET STACKED DIAGNOSTICS`로 받은 실제 위반이다. 호출 후 `rights_evaluation` 0행 — 흔적이 남지 않는다.
- 검증 과정에서 알게 된 것: `JP + TRANSMISSION + SVOD`는 `right_mapping`에 advisory가 붙어 있어 **충돌이 없어도 `WARNING`이 나온다.** conftest의 기본 후보값이 이 조합이라, "정상 통과"를 확인하는 테스트는 `KR`을 써야 한다.

### 남은 일

- D-28 규약을 P3·P4·P5와 공유한다. 업로드·OCR 단계가 DB를 안 건드린다는 점이 P3와 직접 관련된다.
- O-08 ~ O-12 판단. O-09와 O-11이 실제 동작에 영향이 있어 우선순위가 높다.
- `probe_rights()`의 `pg_advisory_xact_lock`이 최상위 트랜잭션 종료까지 유지된다. P4가 probe 직후 트랜잭션을 오래 열어두지 않도록 규약에 넣어야 한다.

## 2026-08-19 — 문서 기준선 정리

### 한 일

- `mindex DB 설명서.md`를 정본 DBML과 다시 전수 대조했다. 23개 테이블과 모든 enum 상태가 설명서에 반영돼 있음을 확인했다.
- `rights_evaluation`을 "최종 판정"으로 부르던 표현을 사전 판정 1회분으로 수정하고, append-only 및 candidate별 `MAX(id)` 현재 판정 규칙을 추가했다.
- `conflict_resolution.evaluation_reason_id`의 사유 단위 처리, CONFLICT 대상 검증, MVP 미지원 resolution 2종을 설명에 반영했다.
- candidate·evaluation reason·grant의 전체 상태와 blocking 사유 등록 차단, source candidate 근거 추적, history 자동 기록을 반영했다.
- contract/document 상태 비동기화와 애플리케이션의 grant final 전환 책임, `raw_text` 기반 change log 범위를 명확히 했다.
- `mindex_remastered.dbml`을 유일한 데이터 모델 정본으로 확정했다.
- 정본의 현재 구조가 `legal_right × exploitation_mode`, `reason_code`, `rights_evaluation + rights_evaluation_reason`을 사용하는 D-27 세대임을 확인했다.
- 구세대 ERD와 설명 자료를 삭제했다: `mindex.erd.json`, `mindex.dbml`, `mindex.dbdiagram`, `mindex-schema.md`, `mindex_remastered.dbdiagram`, `RIGHTS-VOCABULARY.md`.
- 과거 스키마 세대만 설명하던 `docs/archive/`의 WORKLOG·DECISIONS를 제거했다.
- `docs/README.md`, 루트 `README.md`, `CLAUDE.md`, `.gitignore`의 문서 경로를 현재 정본 기준으로 수정했다.
- `mindex DB 설명서.md`의 잘못된 컬럼명 `legal_right_id`를 실제 컬럼 `legal_right`로 바로잡았다.
- 정본 DBML의 MVP 지원 목록에서 누락됐던 WAIVER 표기를 바로잡았다.
- `DECISIONS.md`를 현행 스키마에 유효한 결정과 미결 항목만 남도록 재작성했다.

### 현재 기준

- DBML과 `sql/init/*.sql`의 테이블 집합은 23개로 일치한다.
- AI 후보는 `rights_grant_candidate`, 결정론적 판정은 `rights_evaluation`/`rights_evaluation_reason`, 확정 원장은 `rights_grant`가 담당한다.
- 최종 충돌 방어는 span 기반 EXCLUDE와 statement trigger이며 예외 우회는 없다.
- WAIVER는 기존 충돌 권리를 종료한 뒤 재평가·재등록하는 정상 경로다.
- `pytest -q` 결과 52건이 모두 통과했다(2026-08-19).

### 남은 일

- O-06: 데이터셋 구성과 TER-001 성공 기준을 팀과 확정한다.
- O-07: 작품 계층·권리사슬·파생 IP 판정용 스키마를 다음 라운드에서 설계한다.
- SER-002: RLS와 DB role 구현이 남아 있다.

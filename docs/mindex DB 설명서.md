# Mindex Remastered DB 구조 및 서비스 플로우

현행 모델은 D-30의 **계약서 단위 all-or-nothing** 구조다. SQL 정본 구현은 `sql/init/*.sql`, 모델 정본은 [mindex_remastered.dbml](mindex_remastered.dbml)이다.

## 1. 구조 요약

```text
ip ── ip_alias
 └── content_asset
        └── rights_grant ── contract ── contract_history
                                      └── contract_chunk

country ── country_label
territory_group ── territory_group_label
                └── territory_group_member ── country

legal_right ─┐
             ├── rights_grant의 2축 계층 판정
exploitation_mode ─┘
```

candidate, evaluation, 개별 승인 계층은 없다. PDF 한 건의 권리 배열이 모두 등록되거나 모두 거부된다.

## 2. 테이블 19개

### 지역·판정 기준정보

| 테이블 | 역할 |
|---|---|
| `country` | ISO alpha-2 국가코드와 WORLDWIDE 전개 포함 여부 |
| `country_label` | 국가명의 언어별 라벨 |
| `territory_group` | WORLDWIDE/APAC 같은 입력 전개 그룹 |
| `territory_group_label` | 그룹명의 언어별 라벨 |
| `territory_group_member` | 그룹을 국가 집합으로 전개 |
| `legal_right` | 법적 권리 taxonomy와 nested-set span |
| `exploitation_mode` | 이용형태 taxonomy와 nested-set span |
| `reason_code` | conflict report·앱 표시용 판정 사유 어휘 |
| `constraint_reason_map` | DB 제약명을 reason code로 변환 |

`statutory_right`와 `right_mapping`은 삭제됐다. 따라서 관할별 조합 typicality와 advisory 경고는 현재 제공하지 않는다. 다만 법적 권리와 이용형태를 하나로 합치지 않고 독립된 두 판정축으로 유지한다.

### 도메인 테이블

| 테이블 | 역할 |
|---|---|
| `ip` | 관리 작품 |
| `ip_alias` | 작품의 다국어 제목·이명 |
| `content_asset` | 시리즈·시즌·에피소드·에디션 등 실제 판정 대상 |
| `team` | PIN 기반 팀 관리용 독립 테이블 |
| `contract` | 하나의 계약 업무 건 |
| `contract_history` | PDF 한 건, 계약 세대, all-or-nothing 판정 결과 |
| `rights_grant` | 현재 충돌 슬롯을 점유하거나 종료된 권리의 Single Source of Truth |
| `confirmed_rights_grant` | draft 예약을 제외한 확정 계약의 현재 권리 view |

`team`은 tenant가 아니며 다른 테이블에 `team_id`가 없다. 회사 경계는 온프레미스 설치 인스턴스와 DB가 담당한다.

### 검색·운영 테이블

| 테이블 | 역할 |
|---|---|
| `contract_chunk` | 계약서 세대별 조항과 1024차원 임베딩 |
| `change_log` | 원문 변경에 따른 재청킹 작업 큐 |
| `schema_meta` | 적용된 스키마 버전 |

## 3. 계약과 PDF 세대

`contract`는 grantor, grantee, signed date, amount 같은 업무 메타데이터를 가진다. 상태는
`draft | signed | cancelled`다. signed에는 applied 세대를 가리키는
`current_history_id`가 필요하다. 취소·해지·협의 결렬은 모두 cancelled로 처리한다.
cancelled는 종결 상태이며 draft나 signed로 되돌릴 수 없다.

`contract_history`는 과거의 `contract_document`를 흡수한다.

- `version`: 계약 안에서 업로드 순서대로 증가하는 정수. 화면에서는 `v1`, `v2`로 표시
- `document_kind='draft'`: 협의 중 초안본
- `document_kind='final'`: 최종본 업로드 버튼으로 지정된 문서
- `status='applied'`: 모든 추출 권리가 grant로 등록됨
- `status='conflicted'`: 권리는 0행이고 `conflict_report`가 존재
- `file_path`: object-storage key
- `raw_text`: OCR/파싱 원문

`contract_version`은 삭제됐으며 대체 테이블이 없다. 계약 메타데이터 수정 감사가 필요하면 별도 설계가 필요하다.

## 4. 판정 대상과 권리

`content_asset`은 IP 전체뿐 아니라 시즌, 에피소드, 에디션을 표현한다. 현재 충돌 판정은 `content_asset_id` 완전 일치만 사용하므로 시리즈 전체와 시즌2 사이의 포함관계는 자동 판정하지 않는다.

`rights_grant`의 주요 컬럼은 다음과 같다.

| 컬럼 | 의미 |
|---|---|
| `contract_history_id` | 이 권리를 만든 PDF 세대 |
| `content_asset_id` | 실제 판정 대상 |
| `lineage_id` | 개정판 사이의 논리적 권리 계보 값; FK 아님 |
| `territory` | 국가 한 개 |
| `legal_right` | 법적 권리 축 |
| `exploitation_mode` | 이용형태 축 |
| `period` | 반열림 날짜 범위 |
| `exclusivity` | exclusive, sole, non_exclusive |
| `evidence` | 필드별 페이지·조항·원문 인용 |
| `conditions_raw` | 아직 정형화하지 않은 원문 조건 |

상태는 `active | terminated`다. 종료 상태에서는 시각, 사유(`superseded | expired | waiver | cancelled`)가 함께 있어야 한다.

## 5. 2축 계층 충돌 판정

`legal_right`와 `exploitation_mode`는 각각 nested-set `lft/rgt`와 생성 `span`을 가진다. grant INSERT trigger가 참조 span을 grant 행에 복사하므로 앱은 span을 조작할 수 없다.

```text
PUBLIC_TRANSMISSION [1,7) && TRANSMISSION [4,6) → 포함 충돌
SVOD [2,4) && TVOD [6,8)                    → 별도 이용형태
```

독점/sole끼리의 최종 제약은 다음 축을 비교한다.

```text
서로 다른 contract
× 같은 content_asset
× legal_right_span 겹침
× exploitation_mode_span 겹침
× 같은 territory
× period 겹침
```

GiST EXCLUDE 제약명은 `no_exclusive_overlap`이다. 독점과 non-exclusive 조합은 statement trigger가 `no_exclusivity_conflict`로 차단한다. terminated grant는 판정 대상이 아니다.

## 6. Evidence

`evidence`는 JSON object이며 다음 키가 필수다.

```text
legal_right
exploitation_mode
territory
period
exclusivity
```

각 값은 페이지와 조항을 선택적으로 가질 수 있지만 `quote`는 비어 있을 수 없다. 구조와 인용 필수 조건은 `is_valid_evidence()`와 CHECK가 강제한다.

## 7. 검증과 등록 함수

### `validate_rights_batch()`

PDF 전체 권리 배열을 실제 INSERT 경로로 검증한 뒤 서브트랜잭션을 롤백한다. 실제 constraint name, 충돌 grant, 겹친 기간을 반환할 수 있으며 업무 행을 남기지 않는다.

### `save_rights_batch()`

계약과 새 `contract_history` 세대를 만들고 전체 권리를 한 문장으로 INSERT한다.

- 성공: history는 `applied`, 모든 grant는 `active`, contract는 최신 세대를 가리킨다.
  `p_document_kind='draft'`면 contract는 draft로 유지되어 권리를 선점하고,
  기본값 `final`이면 contract를 signed로 전환한다.
- 실패: grant 전체가 롤백되고 history는 `conflicted`, `conflict_report`가 저장된다.

부분 성공은 없다.

### `terminate_rights_grant()`

active grant를 `terminated`로 바꾼다. WAIVER도 이 함수를 통해 충돌 원인을 제거한 뒤 신규 배치를 다시 제출한다.

contract가 `cancelled`로 전환되면 해당 계약의 active grant는 자동으로
`terminated/cancelled`가 되어 예약이 해제된다.

### `confirmed_rights_grant`

확정 계약의 현재 권리만 반환하는 view다. `rights_grant.status='active'`이면서
`contract.status='signed'`인 행만 포함하므로 draft 계약의 예약은 제외된다.

## 8. 개정판과 lineage

새 세대 저장 시 `(content_asset_id, territory, legal_right, exploitation_mode)`가 이전 active grant 하나와 일치하면 `lineage_id`를 승계한다. 없거나 모호하면 조용히 새 lineage를 시작한다. 새 배치가 성공하면 이전 등록 세대의 active grant는 `terminated/superseded`로 전환된다.

`status='signed'` 계약의 개정 허용 여부는 앱 정책이고 DB는 이를 금지하지 않는다.

## 9. 지역 범위의 현재 한계

`territory`는 국가 한 개다. WORLDWIDE/APAC는 등록 전에 국가별 grant 행으로 전개해야 한다. `Worldwide except US` 같은 원문 표현과 그룹 구성의 시점별 스냅샷은 아직 모델링하지 않았다. JSONB만으로 충돌을 판정하지 않고 정규화된 국가 행을 쓰는 원칙은 유지한다.

## 10. 검색과 운영

`contract_chunk`는 contract와 contract_history를 함께 참조해 개정 전후의 조항이 섞이지 않게 한다. `contract_history` 행의 INSERT/UPDATE/DELETE trigger는 `change_log`를 생성한다. 이를 소비해 원문을 다시 청킹·임베딩할 worker 골격은 있으나, 실제 재처리 함수는 아직 구현되지 않았다. `schema_meta`의 현재 D-31 버전 태그는 `2026-08-21.1`이다.

# K-RIGHTS 합성데이터 현황

status: **Phase A~H 전부 완료**
quality tier: `GENERATED_DRAFT` — 전건 사람 검토 전
last updated: 2026-08-22

> 데이터셋의 현재 상태·수치는 이 문서가 기준이다.
> 서비스 개념과 판정 규칙은 `docs/K-RIGHTS_SERVICE_OVERVIEW.md`,
> 전달 규격은 `docs/synthetic_data/interfaces/`를 본다.

---

## 1. Phase 진행

계약서를 먼저 쓰고 나중에 정답을 맞추지 않는다는 원칙에 따라 아래 순서로 진행했고, **8단계 모두 완료**했다.

| Phase | 내용 | 상태 |
|---|---|---|
| A | Scenario Logic Freeze — 72 Scenario 구조, R1~R9, 결과 4종 확정 | 완료 |
| B | Scenario ↔ Contract Graph — target/existing/upstream 관계, Unique Contract 확정 | 완료 · REVIEWED |
| C | Shared Taxonomy — legal right, exploitation mode, territory, 표현사전, clause label | 완료 · REVIEWED |
| D | Generation Metadata — T1~T6 template, 페이지 분포, commercial terms | 완료 · REVIEWED |
| E | Scenario Master — 72건 machine-readable Scenario | 완료 · REVIEWED |
| F | Pilot GT — 대표 6 Scenario로 schema 검증 | 완료 · REVIEWED |
| G | Full GT — 72 Scenario 전체 Ground Truth | 완료 · REVIEWED |
| H | Contract Generation — 본문 · Evidence span · PDF 생성 | 완료 · `GENERATED_DRAFT` |

Phase H는 Pilot 10건 재생성 후 나머지 76건을 `15+15+15+15+16` 5개 batch로 생성했다.

---

## 2. 확정 산출물

### Scenario

| 구분 | 수 |
|---|---|
| Master | 60 |
| Robustness | 12 |
| **합계** | **72** |

언어: KO 24 · EN 24 · JP 24

기대 결과: NORMAL 27 · CONFLICT 35 · REVIEW_REQUIRED 7 · WARNING 3

### Contract

| 구분 | 수 |
|---|---|
| Target | 72 |
| Supporting | 14 |
| **Unique Contract** | **86** |

언어: KO 29 · EN 29 · JP 28

Template family: T1 48 · T2 3 · T3 8 · T4 4 · T5 19 · T6 4

페이지 대역: SHORT 17 · MEDIUM 43 · LONG 19 · EXTENDED 7

> Scenario 수와 Contract 수는 같지 않다. 한 Scenario가 여러 Contract를 참조하고,
> 하나의 Contract가 여러 Scenario에서 재사용된다.

### 정답 · 문서

| 항목 | 수 |
|---|---|
| RightsGrant | 94 |
| Finding | 47 |
| Evidence requirement (planned) | 132 |
| Actual Evidence span | 781 |
| Evidence requirement mapping | 132 / 132 |
| Canonical Markdown | 86 |
| PDF | 86 |

### 검증 결과

전체 자동 validator 통과. 세부 항목:

- 제목 PDF 추출: PASS
- Canonical Markdown offset exact match: PASS
- PDF Evidence text extraction: PASS
- 목표 페이지 허용오차(±1): PASS
- 비표 영역 배경 채움 잔상: 0건
- 파일 hash 검증: PASS

---

## 3. 품질 등급 — 반드시 지킬 것

전체 산출물이 자동검증을 통과했지만 **전건 사람 검토 전까지 `GENERATED_DRAFT` / `DRAFT`다.**

이를 `FINAL` 학습·평가 데이터로 표시하지 않는다.

extraction/decision DB 전달 schema는 계약서 표본·본계약 검토와 함께 후속 확정한다.

---

## 4. Evidence offset 규격

Evidence offset의 기준은 `testdata/k-rights/documents/canonical/`의 Markdown body다.

| 항목 | 값 |
|---|---|
| encoding | UTF-8 |
| line ending | LF |
| front matter | offset에서 제외 |
| unit | Unicode code point |
| `start_char` | inclusive |
| `end_char` | exclusive |

**PDF 페이지 위치와 canonical Markdown 문자 offset을 같은 좌표계로 취급하지 않는다.**

---

## 5. ID와 서비스 DB 경계

`CTR-*` · `GRT-*` · `FND-*` · `EVD-*` / `EVS-*`는 데이터셋 정답과 파일 관계를 잇는 **안정적인 dataset ID**다. 운영 DB의 surrogate ID로 교체하지 않는다.

- 서비스 DB 전달 payload에 `dataset_contract_id`를 **포함하지 않는다.**
- 적재 후 평가가 필요하면 `dataset_contract_id → db_contract_id` 매핑을 데이터셋 외부의 **로컬 sidecar**로 보관한다.
- GT와 계약 파일명은 dataset ID를 계속 사용한다.
- 로컬 sidecar 없이 DB ID만으로 GT를 수정하지 않는다.

---

## 6. 데이터셋 사용 경계

- `annotations/`는 테스트 정답 및 내부 평가용이다.
- `authoring/`은 서비스의 직접 입력이 아니라 합성데이터 관계 복원용 metadata다.
  특히 `contract_generation.yaml`의 당사자·상업·문서구조 값을 **서비스 DB payload로 직접 적재하지 않는다.**
- `template_type` · `clause_order_profile` · `document_evidence_layout` ·
  `source_style_profile` · `target_pages` · `schedule_usage`는 **생성 metadata이며 RightsGrant 추출 필드가 아니다.**
- Payment 추출값은 `amount`와 `currency`만 사용한다.
- `legal_right` · `exploitation_mode` · `exclusivity`를 서로 합치지 않는다.
- 정의되지 않은 `ASIA` / `APAC`를 임의 국가목록으로 확장하지 않는다.
- Consent 문서 부재를 미승인 사실로 변환하지 않는다.
- Contract Term을 License Period로 대체하지 않는다.
- 영상 · Remake · OST를 자동으로 같은 RightsGrant에 병합하지 않는다.

---

## 7. 저장소 경계

이 저장소(`mindex`)는 **서비스 구현 저장소**다. 합성데이터의 생성 파이프라인·Phase 작업 문서·
생성 결정 기록은 별도 합성데이터 워크스페이스에 있으며 여기로 가져오지 않는다.

여기에 두는 것은 서비스 개발과 평가에 실제로 필요한 산출물뿐이다.

- 계약 본문 (canonical Markdown)
- 정답 (annotations)
- 정규화 어휘 (taxonomies)
- 규격 (schemas, interfaces)
- 관계 metadata (authoring YAML)
- 색인 (manifests)

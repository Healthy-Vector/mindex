# K-RIGHTS 팀 공유 테스트데이터

OCR, 문서 구조 인식, 권리정보 추출, 임베딩 검색 및 충돌 판정 평가에 사용할
K-RIGHTS 합성 계약 데이터 묶음이다.

## 디렉터리

- `documents/pdf/`: 합성 계약 PDF 86건 — **이 저장소에는 포함하지 않는다**(`.gitignore`). 원본 워크스페이스에서 받는다
- `documents/canonical/`: PDF와 대응하는 canonical UTF-8/LF Markdown 86건
- `manifests/`: 계약 ID, PDF 경로, SHA-256, 페이지, 언어 및 Scenario 연결정보
- `annotations/`: Full Ground Truth와 실제 Evidence span
- `schemas/`: Full GT schema와 Phase H 전달·offset 규격
- `taxonomies/`: 법적 권리, 이용형태, 지역, 다국어 표현 및 clause label
- `authoring/`: Scenario/Contract/Content 관계와 생성 시 확정한 내부 metadata

Manifest와 Evidence 안의 파일 경로는 모두 이 `testdata/k-rights/` 디렉터리를 기준으로 한
상대경로다. Manifest의 기준 문서는 `canonical_path`(`documents/canonical/...`)이며,
`pdf_path`/`pdf_sha256`은 PDF 세트를 별도로 확보했을 때만 유효하다.

전체 Phase 진행과 확정 수치는 `docs/synthetic_data/DATASET_STATUS.md`가 기준이다.

## 현재 상태

- Scenario: 72건
- Unique Contract: 86건
- PDF/Canonical Markdown: 각각 86건
- RightsGrant: 94건
- Finding: 47건
- Actual Evidence span: 781건
- Evidence requirement mapping: 132/132
- 전체 자동 validator: 통과

PDF와 Actual Evidence는 전건 사람 검토 전 `GENERATED_DRAFT`/`DRAFT`다. 이를
`FINAL` 학습·평가 데이터로 표시하지 않는다.

## Canonical text와 Evidence offset

Evidence offset의 기준은 `documents/canonical/`의 Markdown body다.

- encoding: UTF-8
- line ending: LF
- front matter: offset에서 제외
- unit: Unicode code point
- `start_char`: inclusive
- `end_char`: exclusive

따라서 OCR 결과를 평가할 때 PDF 페이지 위치와 canonical Markdown 문자 offset을
같은 좌표계로 취급하면 안 된다.

## ID와 서비스 DB 경계

`CTR-*`, `GRT-*`, `FND-*`, `EVS-*`는 데이터셋과 평가 파일을 연결하기 위한 ID다.
서비스 DB의 영속 ID로 사용하지 않는다. DB 적재 후 연결이 필요하면 저장소 외부의
로컬 sidecar에서 `dataset_contract_id`와 DB ID를 매핑한다.

## 사용 경계

- `annotations/`와 `authoring/`은 테스트 정답 및 내부 평가용이다.
- `authoring/contract_generation.yaml`에는 생성 전용 당사자·상업·문서 구조 metadata가
  포함되어 있으므로 서비스 DB payload로 직접 적재하지 않는다.
- `template_type`, page/layout/source-style metadata는 RightsGrant 추출 필드가 아니다.
- Payment 추출값은 `amount`와 `currency`만 사용한다.
- `legal_right`, `exploitation_mode`, `exclusivity`를 서로 합치지 않는다.
- 정의되지 않은 `ASIA`/`APAC`를 임의 국가목록으로 확장하지 않는다.
- Consent 문서 부재를 미승인 사실로 변환하지 않는다.
- Contract Term을 License Period로 대체하지 않는다.
- 영상, Remake 및 OST를 자동으로 같은 RightsGrant에 병합하지 않는다.

# K-RIGHTS 합성데이터 — 서비스 전달 문서

합성데이터 워크스페이스에서 이 서비스 저장소로 전달한 문서 묶음이다.
데이터 본체는 `testdata/k-rights/`에 있다.

## 디렉터리

- `DATASET_STATUS.md`: Phase 진행, 확정 산출물 수치, 품질 등급, 사용 경계
- `interfaces/`: Rich Extraction, DB projection, 상세 화면 View Model 제안과 예시

## 읽는 순서

1. 서비스 개념과 판정 규칙 → `docs/K-RIGHTS_SERVICE_OVERVIEW.md`
2. 데이터셋 현재 상태와 수치 → `DATASET_STATUS.md`
3. OCR/추출 내부 표현 → `interfaces/2026-08-19-contract-extraction-interface-scope-v0.1.md`
4. DB 전달값 → `interfaces/2026-08-19-db-contract-projection-v0.1.md`

## 상태 주의

- `interfaces/`의 schema 문서는 현재 `DRAFT` 제안이다.
- 예시 JSON은 인터페이스 설명용이며 전체 86건의 정식 DB projection이 아니다.
- 데이터셋 산출물은 전건 사람 검토 전까지 `GENERATED_DRAFT`다.
- 서비스 API 계약으로 고정하기 전 팀 검토와 정식 JSON Schema 확정이 필요하다.

## 이 저장소에 없는 것

합성데이터 **생성 파이프라인** 문서(Phase 작업지시, 생성 결정 기록, 원자료 provenance)는
별도 합성데이터 워크스페이스에서 관리한다. 여기에는 서비스 개발과 평가에 필요한 산출물만 둔다.

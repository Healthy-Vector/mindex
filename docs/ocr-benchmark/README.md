# OCR 모델 선정 벤치마크 (P1 → P3 인수인계)

**이 폴더는 실제 구현이 아니라 참고자료입니다.**
파싱·OCR 실제 구현 위치는 `app/pipeline/` (P3 담당).

## 무엇을 했나

PaddleOCR vs Tesseract 비교 실험. 합성 계약서 샘플(스캔본·디지털 PDF)로
정확도·핵심 필드 보존율을 측정해 **PaddleOCR을 권장 모델로 선정**했다.
근거는 `OCR_모델선정_근거.md` 참고.

## 파일

| 파일 | 내용 |
|---|---|
| `01_make_samples.py` | 테스트용 합성 계약서 생성 (스캔본·디지털) |
| `02_ocr_compare.py` | PaddleOCR vs Tesseract 정확도 비교 |
| `03_embed_load.py` | 임베딩 적재 (e5-large) |
| `04_search_test.py` | 벡터 검색 동작 확인 |
| `OCR_모델선정_근거.md` | **결론** — 왜 PaddleOCR인가 |
| `RUN.md` | 실행 방법 (원본 README) |
| `out/` | 실행 결과물 (OCR 원문·정답지·비교 리포트) |

## 실행하려면

`RUN.md` 참고. 표준 라이브러리 + `paddleocr`·`pytesseract`·
`sentence-transformers` 설치가 필요하다.

## P3 확인 필요

- `app/pipeline/` 에 실제 구현 시 이 폴더의 전처리·비교 로직을 참고 자료로만 쓸 것
- 마스킹(SER-003)·인젝션 방어(SER-001)는 여기 포함 안 됨 — 별도로
  `llm_extract_demo/` (같은 작업폴더) 확인

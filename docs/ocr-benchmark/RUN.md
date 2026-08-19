# OCR + 임베딩 테스트 파이프라인

> 목적: OCR 모델 비교 근거 확보 + e5-large 다국어 임베딩 검증 (SFR-005)
> 실행 위치: **전부 [맥]**. EC2는 벡터 저장만 담당 (RAM 부족으로 추론 불가)
> 담당 경계: 실제 구현은 P3 모듈(`mindex-core`의 `parsing/`·`embedding/`). 이건 검증·환경 세팅.

---

## 워크플로우

```
01_make_samples.py    합성 계약서 PDF 생성
                      → ① 디지털 PDF (텍스트 레이어 있음)
                      → ② 스캔본 PNG (깨끗한 인쇄물 200dpi 스캔 수준)
                      → ③ 텍스트 레이어 추출 = OCR 우회 경로 확인
        ↓
02_ocr_compare.py     PaddleOCR vs Tesseract → CORE 필드 보존율 비교
        ↓
03_embed_load.py      조항 단위 분할 → e5-large 임베딩(1024차원)
                      → 공유 DB(5432) p1_test_ocr_chunk + HNSW
        ↓
04_search_test.py     의미 검색 + 다국어 검색(일본어 질의→한국어 조항) 검증
                      ⚠️ SFR-009-C(검색) 범위. 충돌 판정에는 벡터 미사용(E-3)
```

> **입력 분기가 핵심이다.** 실무 계약서 PDF 는 Word·HWP 로 만들어 저장한 것이 다수라
> 텍스트 레이어가 살아 있다. 이 경우 OCR 이 아예 불필요하다.
> P3 파싱 모듈은 반드시 텍스트 레이어를 먼저 확인하고, 없을 때만 OCR 을 태워야 한다.

## 설치 [맥]

```bash
# 파이썬 패키지
pip3 install reportlab pypdfium2 pillow sentence-transformers psycopg2-binary

# OCR 엔진 (둘 다 설치해야 비교 가능)
pip3 install paddlepaddle paddleocr          # PaddleOCR
brew install tesseract tesseract-lang        # Tesseract + 한국어팩
pip3 install pytesseract
```

> ⚠️ 첫 실행 시 다운로드가 큼: e5-large 모델 ~2.2GB, PaddleOCR 모델 ~수십MB
> ⚠️ DB 접속은 `~/.pgpass` 를 사용. 시연 준비 때 만든 그대로면 비밀번호 입력 없이 동작

## 실행

```bash
cd "/Users/Lien/Downloads/tibero/Tmax_OpenSQL_3.17.8.7_rockylinux9.7_buildtime20260720/ocr_embedding_test"
python3 01_make_samples.py
python3 02_ocr_compare.py
python3 03_embed_load.py
python3 04_search_test.py
```

## 모델 선택 근거

| 대상 | 결정 | 이유 |
|---|---|---|
| OCR | PaddleOCR 주력 / Tesseract 대조군 | 시나리오가 KO·EN·JA 3개 언어. PaddleOCR이 한중일 특화. 둘 다 Apache 2.0 — D3 제출물 라이선스 호환. **02 결과(CER)가 최종 선택 근거가 된다** |
| 임베딩 | multilingual-e5-large (변경 불가) | RFP SFR-005 확정. 1024차원, 로컬 구동(외부 전송 없음 = masking 불필요). 여기서는 다국어 공간이 실제 동작하는지 **검증**만 |

### e5 사용 시 주의 (구현 시 P3에게 전달)

- 문서 저장: `passage: ` 접두사 / 검색 질의: `query: ` 접두사 — **빼먹으면 검색 품질 하락**
- `normalize_embeddings=True` + 코사인 거리(`vector_cosine_ops`) 조합 사용

## 서버환경 점검 결과 (P1)

| 단계 | 위치 | 메모리 | 판정 |
|---|---|---|---|
| PDF·스캔본 생성 | 맥 | 낮음 | ✅ |
| OCR | 맥 | ~1–2GB | ✅ |
| e5-large 추론 | **맥** | **~3GB** | ✅ (24GB RAM) |
| 벡터 저장·HNSW 검색 | EC2 5432 | 기존 컨테이너 | ✅ |

🔴 **EC2(t3.small, RAM 2GB)에서 임베딩 추론 금지.** DB 두 개가 이미 떠 있어 여유가 없고, e5-large는 모델만 2.2GB다. 올리면 서버가 죽고 팀 전원이 멈춘다.
팀 공용 추론 서버가 필요해지면 t3.large(8GB, ~$0.10/시간) 증설 검토 — 현재는 불필요.

## 공유 DB 규칙 준수

- 실험 테이블은 `p1_test_` 접두사 (`p1_test_ocr_chunk`)
- 테스트 후 정리: `DROP TABLE IF EXISTS p1_test_ocr_chunk;`
- 스키마 동결(8/18)과 무관 — 실험 테이블이라 대상 아님

## 확장 방향 (검증 통과 후)

1. 시나리오 60건 전체 PDF가 P3 손에서 나오면 같은 파이프라인으로 일괄 처리
2. Robustness 12건이 OCR 검증 전용 케이스 — RB-KO01~04, RB-JA01~04 등에 적용
3. EN·JA 샘플 추가 (`01`의 CONTRACT_TEXT 교체, Tesseract는 `lang="kor+eng+jpn"`)
4. CER 목표치 합의 필요 — 권장: 정상 인쇄물 기준 95% 이상, 미달 시 전처리(해상도·이진화) 추가

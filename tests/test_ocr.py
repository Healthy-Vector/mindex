"""OCR 경로 통합 테스트 (Phase 5).

`paddleocr`가 없으면 전부 건너뛴다 — requirements-ml.txt로 분리돼 있어 CI에는
없기 때문이다. 로컬에서 `pip install paddlepaddle paddleocr` 후 확인한다.
반드시 `paddlepaddle`(CPU)다 — `-gpu`가 아니다. 이유는
`app/pipeline/ocr.py` 모듈 docstring 참조(torch와 cuDNN DLL 충돌).

## ⚠️⚠️ 미해결 — pytest 안에서 PaddleOCR 실제 추론이 불안정하다

**이 파일의 실제-추론 테스트는 전부 skip 상태다.** 개발 중 다음을 실제로
관찰했다.

- 독립 스크립트(`python -c "..."`)로 `run_ocr()`을 호출하면 이중 엔진(언어
  자동판정 포함)까지도 여러 번 안정적으로 성공했다.
- 그런데 **똑같은 호출을 pytest 테스트 함수 안에서 하면** 다음 세 가지가
  비결정적으로 나타났다: (1) 정상 통과, (2) 네이티브 access violation으로
  pytest 프로세스 자체가 죽음(Windows fatal exception, exit code 139 —
  파이썬 예외가 아니라서 `pytest.raises`로 못 잡는다), (3) 진행 없이
  응답 없음(수 분 이상).
- 처음엔 "이중 엔진만 위험하다"고 판단해 단일 엔진(`lang_hint` 명시) 경로만
  남겼는데, **재검증하니 단일 엔진 경로도 pytest 안에서 크래시가 났다** —
  그 프로세스의 첫 실제 paddle 추론 호출이었는데도 그랬다. 그래서 "이중 vs
  단일"이 원인이 아니라는 뜻이다.
- pdfplumber 파싱 유무, pypdfium2 반복 호출 여부로도 원인을 좁혀 보려 했으나
  결정적으로 갈리지 않았다(재현 안 됨 / 응답 없음이 섞여 나왔다).

**결론: 이 환경(Windows, paddle CPU, pytest)에서 PaddleOCR 실제 추론 호출은
믿을 수 없다.** 원인 후보로 pytest의 출력 캡처·스레드 설정과 paddle CPU
정적 실행기(`paddle_static/runner.py`)의 상호작용을 의심하지만 확정하지
못했다.

## 다음에 할 일

1. pytest 바깥(순수 스크립트·별도 프로세스)에서만 OCR을 검증하는 방식으로
   전환하거나
2. OCR을 서비스에서도 애초에 별도 프로세스로 격리(subprocess/multiprocessing)
   해서, 이 불안정성이 어디서 오든 메인 프로세스가 죽지 않게 만들 것
3. **완전 스캔 문서를 프로덕션에 올리기 전에 반드시 해결할 것**

## 테스트 데이터를 실제 계약서에서 만드는 이유

이 프로젝트의 합성데이터 86건 446페이지는 전부 digital-born이라 진짜 스캔본이
하나도 없다. 그렇다고 toy 문단으로 테스트하면 실제 계약서 레이아웃(2단 표,
당사자 정보, 법인등록번호 같은 조밀한 숫자열)에서 OCR이 어떻게 도는지 알 수
없다. 그래서 **실제 계약서 페이지를 래스터화해 텍스트 레이어 없는 PDF로
다시 감싼다.** `route()`가 이걸 `OCR`로 정확히 판정하는 것도 이 방식으로
확인된다(`chars_per_kpx` 0.0 — 스캔본 판정 임계값의 기준값과 일치). 이
구조 검증 자체는 paddle 추론이 필요 없어 안정적으로 통과한다.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline import ocr
from app.pipeline.extract import extract_document
from app.pipeline.route import TextSource

pytestmark = pytest.mark.skipif(
    not ocr.is_available(), reason="paddleocr 미설치 — requirements-ml.txt 참조"
)

KO_SAMPLE = Path("testdata/k-rights/documents/pdf/KO/T1/DIRECT_LICENSE/CTR-KO-0001.pdf")
EN_SAMPLE = Path("testdata/k-rights/documents/pdf/EN/T1/DIRECT_LICENSE/CTR-EN-0001.pdf")

#: 실제 추론이 pytest 안에서 비결정적으로 죽으므로 그 테스트들만 별도로 끈다.
_UNSTABLE = pytest.mark.skip(
    reason=(
        "PaddleOCR 실제 추론이 pytest 프로세스 안에서 비결정적으로 access "
        "violation을 낸다(exit 139) — 파이썬 예외가 아니라 못 잡는다. "
        "이 파일 상단 docstring 참조. 독립 스크립트로는 재현 없이 통과했다."
    )
)


def _scan_pdf_bytes(pdf_path: Path, page_index: int = 0, dpi: int = 200) -> bytes:
    """실제 계약서 한 페이지를 래스터화해 텍스트 레이어 없는 PDF로 감싼다."""
    image = ocr.rasterize_page(pdf_path.read_bytes(), page_index, dpi=dpi)
    buf = io.BytesIO()
    Image.fromarray(image).save(buf, format="PDF")
    return buf.getvalue()


@pytest.fixture(scope="module")
def ko_scan_bytes() -> bytes:
    if not KO_SAMPLE.exists():
        pytest.skip("합성데이터가 없는 환경")
    return _scan_pdf_bytes(KO_SAMPLE)


def test_래스터화한_페이지는_OCR_경로로_판정된다(ko_scan_bytes):
    """텍스트 레이어가 없으니 route()가 반드시 OCR을 골라야 한다.

    paddle 추론이 필요 없는 구조 검증이라 안정적으로 통과한다.
    """
    doc = extract_document(ko_scan_bytes, ocr=False)
    assert doc.pages[0].text_source is TextSource.OCR
    assert doc.pages[0].signals.chars_per_kpx == 0.0


@_UNSTABLE
def test_한국어_힌트를_주면_당사자명을_복원한다(ko_scan_bytes):
    """CTR-KO-0001 1페이지 원문에 있는 고유명사로 OCR 품질을 가늠한다.

    독립 스크립트로 실행했을 때는 통과했다 — `lang_hint="ko"`로 한국어 모델을
    태우면 '루미나 픽처스 주식회사'·'해솔미디어 주식회사'·대표자명·주소·
    법인등록번호까지 정확히 복원됐다. pytest 안에서는 불안정해서 skip한다.
    """
    image = ocr.rasterize_page(ko_scan_bytes, 0)
    text, used_lang = ocr.run_ocr(image, lang_hint="ko")
    assert used_lang == "ko"

    found = [name for name in ("루미나", "픽처스", "해솔", "미디어") if name in text]
    assert len(found) >= 2, f"당사자명 조각이 거의 안 잡혔다({found}). OCR 출력:\n{text[:300]}"


@_UNSTABLE
def test_영어_스캔본은_기본모델로_처리된다():
    """en/ja는 기본 PP-OCRv6 모델이 한 모델로 처리한다."""
    if not EN_SAMPLE.exists():
        pytest.skip("합성데이터가 없는 환경")
    scan = _scan_pdf_bytes(EN_SAMPLE)
    image = ocr.rasterize_page(scan, 0)
    text, used_lang = ocr.run_ocr(image, lang_hint="en")
    assert used_lang == "auto"
    assert text.strip(), "영문 스캔본에서 아무것도 인식하지 못했다"


@_UNSTABLE
def test_전체_파이프라인이_스캔본에서도_청크를_만든다(ko_scan_bytes):
    """extract 이후 segment/chunk 까지 예외 없이 도는지 — 조립 전체를 확인한다."""
    from app.pipeline.chunk import build_chunks
    from app.pipeline.segment import segment

    doc = extract_document(ko_scan_bytes, ocr=False)
    page = doc.pages[0]
    image = ocr.rasterize_page(ko_scan_bytes, 0)
    page.text, page.ocr_lang = ocr.run_ocr(image, lang_hint="ko")

    lang, full_text, clauses = segment(doc.pages)
    chunks = build_chunks(clauses, lang, doc.file_hash)

    assert full_text.strip(), "OCR 텍스트가 조항 분해 단계로 전혀 안 넘어갔다"
    assert len(chunks) >= 1


@_UNSTABLE
def test_언어힌트_없이_스캔본을_처리한다(ko_scan_bytes):
    """완전 스캔 문서(디지털 페이지 없음)에서 언어를 자동판정하는 실사용 경로.

    독립 스크립트로는 통과했다(1556자 복원, ko로 정확히 판정) — 다만 pytest
    안에서는 이 파일 상단 docstring의 이유로 검증할 수 없다.
    """
    doc = extract_document(ko_scan_bytes, ocr=True)
    page = doc.pages[0]
    assert page.ocr_lang == "ko"
    found = [name for name in ("루미나", "픽처스", "해솔", "미디어") if name in page.text]
    assert len(found) >= 2

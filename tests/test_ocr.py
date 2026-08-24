"""OCR 경로 통합 테스트 (Phase 5).

`paddleocr`가 없으면 전부 건너뛴다 — requirements-ml.txt로 분리돼 있어 CI에는
없기 때문이다. 로컬에서 `pip install paddlepaddle paddleocr` 후 확인한다.
반드시 `paddlepaddle`(CPU)다 — `-gpu`가 아니다. 이유는
`app/pipeline/ocr.py` 모듈 docstring 참조(torch와 cuDNN DLL 충돌).

## 한때 크래시가 났었다 — 원인은 이 파일의 픽스처였다

개발 중 PaddleOCR 실제 추론이 네이티브 access violation(`0xC0000005`)으로
프로세스를 통째로 죽이는 일이 반복됐다. 파이썬 예외가 아니라 `pytest.raises`
로도 못 잡는 종류였다. 원인을 "pytest 환경 문제"로 오진해서 실제-추론
테스트를 전부 skip 처리했었는데, **실제 원인은 `_scan_pdf_bytes()`가
비정상적으로 거대한 PDF를 만들고 있었던 것**이다.

    원본 PDF 페이지        595 x 842 pt   (A4)
    200dpi 렌더링          1653 x 2339 px
    PIL이 PDF로 저장       1653 x 2339 pt   <- 72dpi 가정, A4의 2.8배 종이
    그걸 다시 200dpi 렌더링  4592 x 6498 px   <- OCR이 이걸 받고 죽었다

`Image.save(format="PDF")`는 dpi를 안 넘기면 72dpi를 가정한다. 그래서 픽셀
크기가 그대로 포인트 크기가 되어 A4의 2.8배짜리 종이가 만들어졌고, 그 PDF를
다시 200dpi로 렌더링하니 4592x6498짜리 이미지가 나왔다. 실제 스캔본은
A4(595x842pt)라 이런 크기가 나올 수 없다 — **순수한 테스트 인공물이었다.**

`resolution=dpi`를 넘겨 A4를 유지하도록 고치자 `extract_document(ocr=True)`
실경로가 언어 자동판정까지 포함해 정상 통과했다(ocr_lang=ko, 1472자).

반증된 가설들을 기록으로 남긴다 — 같은 함정을 다시 파지 않기 위해서다.

| 가설 | 검증 | 결과 |
|---|---|---|
| 이중 엔진(언어 자동판정)이 원인 | 단일 엔진으로 실행 | 반증 — 단일도 크래시 |
| pypdfium2 반복 호출이 원인 | pdfium 2회 후 OCR | 반증 — 성공 |
| pdfplumber가 원인 | 사용/import만/순서 4변형 격리 | 반증 — 없는 변형도 크래시 |
| pytest 환경이 원인 | 독립 스크립트로 동일 입력 실행 | 반증 — 스크립트도 크래시 |

"비결정적"으로 보였던 것도 착각이었다. 성공/실패가 갈린 건 **서로 다른 크기의
이미지를 비교하고 있다는 걸 몰랐기** 때문이고, 입력이 같으면 결과도 일관됐다.

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

def _scan_pdf_bytes(pdf_path: Path, page_index: int = 0, dpi: int = 200) -> bytes:
    """실제 계약서 한 페이지를 래스터화해 텍스트 레이어 없는 PDF로 감싼다.

    `resolution=dpi`를 반드시 넘겨야 한다. PIL은 이미지를 PDF로 저장할 때
    기본적으로 72dpi를 가정해서, 1653x2339 픽셀을 **1653x2339 포인트**
    (A4의 2.8배짜리 종이)로 만들어 버린다. 그 PDF를 다시 200dpi로 렌더링하면
    4592x6498짜리 거대 이미지가 나와서, 실제 스캔본과 전혀 다른 조건이 된다.
    `resolution=200`을 주면 595x842pt(A4)로 정상 저장된다.
    """
    image = ocr.rasterize_page(pdf_path.read_bytes(), page_index, dpi=dpi)
    buf = io.BytesIO()
    Image.fromarray(image).save(buf, format="PDF", resolution=float(dpi))
    return buf.getvalue()


@pytest.fixture(scope="module")
def ko_scan_bytes() -> bytes:
    if not KO_SAMPLE.exists():
        pytest.skip("합성데이터가 없는 환경")
    return _scan_pdf_bytes(KO_SAMPLE)


def test_래스터화한_페이지는_OCR_경로로_판정된다(ko_scan_bytes):
    """텍스트 레이어가 없으니 route()가 반드시 OCR을 골라야 한다."""
    doc = extract_document(ko_scan_bytes, ocr=False)
    assert doc.pages[0].text_source is TextSource.OCR
    assert doc.pages[0].signals.chars_per_kpx == 0.0


def test_한국어_힌트를_주면_당사자명을_복원한다(ko_scan_bytes):
    """CTR-KO-0001 1페이지 원문에 있는 고유명사로 OCR 품질을 가늠한다.

    '루미나 픽처스'·'해솔미디어'는 흔한 단어가 아니라 우연히 맞을 수 없다.
    완벽한 일치는 기대하지 않는다 — 인식이 조금 흔들려도 회사명 전체가
    깨지지만 않으면 됐다고 본다.
    """
    image = ocr.rasterize_page(ko_scan_bytes, 0)
    text, used_lang = ocr.run_ocr(image, lang_hint="ko")
    assert used_lang == "ko"

    found = [name for name in ("루미나", "픽처스", "해솔", "미디어") if name in text]
    assert len(found) >= 2, f"당사자명 조각이 거의 안 잡혔다({found}). OCR 출력:\n{text[:300]}"


def test_영어_스캔본은_기본모델로_처리된다():
    """en/ja는 기본 PP-OCRv6 모델이 한 모델로 처리한다."""
    if not EN_SAMPLE.exists():
        pytest.skip("합성데이터가 없는 환경")
    scan = _scan_pdf_bytes(EN_SAMPLE)
    image = ocr.rasterize_page(scan, 0)
    text, used_lang = ocr.run_ocr(image, lang_hint="en")
    assert used_lang == "auto"
    assert text.strip(), "영문 스캔본에서 아무것도 인식하지 못했다"


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


def test_언어힌트_없이_스캔본을_처리한다(ko_scan_bytes):
    """완전 스캔 문서(디지털 페이지 없음)에서 언어를 자동판정하는 실사용 경로.

    `_guess_lang_hint`가 None을 돌려주고 `run_ocr`이 두 엔진을 다 태운 뒤
    회수한 글자 수가 많은 쪽(=한국어)을 고르는지 확인한다. 이게 실제 스캔
    계약서가 업로드됐을 때 타는 경로다.
    """
    doc = extract_document(ko_scan_bytes, ocr=True)
    page = doc.pages[0]
    assert page.ocr_lang == "ko"
    found = [name for name in ("루미나", "픽처스", "해솔", "미디어") if name in page.text]
    assert len(found) >= 2

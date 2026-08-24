"""PDF → 페이지별 원문 추출.

**바이트를 받는다.** 파이프라인 진입점이 `retrieve_contract_chunks(pdf_bytes)`이고
파일 경로가 없기 때문이다. 경로 대신 바이트를 다루면 부수 효과도 하나 얻는데,
프로젝트 경로에 한글이 섞여 있어도(`d:/오픈소스 대회 자료/...`) 영향을 받지 않는다.

PyMuPDF는 쓰지 않는다 — AGPL이라 프로젝트 전체 라이선스가 오염된다.
텍스트 추출은 pdfplumber, 래스터화(OCR 경로)는 pypdfium2로 처리한다.

## OCR 연계

`route()`가 페이지를 OCR/VERIFY로 판정하면 이 모듈이 `app.pipeline.ocr`을
호출해 텍스트를 채운다. `ocr`도 `embed`와 같은 지연 import 패턴이라
`paddleocr`이 없는 환경(CI)에서도 이 모듈 import 자체는 실패하지 않는다.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field

import pdfplumber

from app.pipeline import ocr as ocr_mod
from app.pipeline.normalize import normalize_text
from app.pipeline.route import PageSignals, TextSource, route
from app.pipeline.segment import detect_language

logger = logging.getLogger(__name__)


@dataclass
class Page:
    page: int
    text: str
    text_source: TextSource
    signals: PageSignals
    tables: list[list[list[str]]] = field(default_factory=list)
    #: OCR을 거쳤다면 실제 사용한 언어("ko" 또는 "auto"). 안 거쳤으면 None.
    #: 진단용 필드라 RetrievalBundle 규격에는 노출하지 않는다.
    ocr_lang: str | None = None


@dataclass
class Document:
    file_hash: str
    page_count: int
    pages: list[Page]

    @property
    def source_summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.pages:
            out[p.text_source.value] = out.get(p.text_source.value, 0) + 1
        return out


def _page_signals(page) -> PageSignals:
    text = normalize_text(page.extract_text() or "")
    area = (page.width or 1) * (page.height or 1)
    image_area = sum(
        max(0.0, i.get("x1", 0) - i.get("x0", 0))
        * max(0.0, i.get("bottom", 0) - i.get("top", 0))
        for i in (page.images or [])
    )
    return PageSignals(
        char_count=len(text),
        # 페이지 크기가 제각각이라 문자 수를 그대로 쓰면 A3와 A4를 같은 기준으로
        # 볼 수 없다. 1000px^2 당 문자 수로 정규화한다.
        chars_per_kpx=len(text) / (area / 1000) if area else 0.0,
        image_coverage=image_area / area if area else 0.0,
        image_count=len(page.images or []),
        # 인코딩이 깨진 텍스트 레이어의 흔적. 있으면 OCR과 대조해야 한다.
        bad_char_count=text.count("\ufffd") + text.count("\x00"),
    )


def _guess_lang_hint(pages: list[Page]) -> str | None:
    """디지털 페이지에서 언어를 추정한다. ko면 `"ko"`, 그 외/모르면 None.

    None을 돌려주는 것으로 충분한 이유는 기본 OCR 모델이 en/ja/zh를 이미
    한 모델로 처리해서다 — 구분이 필요한 건 ko 대 그 밖의 언어뿐이다.
    """
    text_pages = [p for p in pages if p.text_source is TextSource.TEXT_LAYER]
    if not text_pages:
        return None
    lines = [ln for p in text_pages for ln in p.text.split("\n")]
    return "ko" if detect_language(lines) == "ko" else None


def _fill_via_ocr(pdf_bytes: bytes, pages: list[Page]) -> None:
    """OCR/VERIFY로 판정된 페이지의 텍스트를 채운다. 제자리에서 수정한다.

    VERIFY는 텍스트 레이어가 있긴 하지만 미심쩍은 경우다(깨진 문자 또는
    이미지가 페이지를 덮음). OCR 결과와 대조해 **글자 수가 더 많은 쪽**을
    취한다 — 완전성의 대용 지표다. 이 경로는 이 프로젝트의 합성데이터
    (전부 digital-born)로는 한 번도 실행된 적이 없어 실측 검증이 안 됐다는
    점을 밝혀둔다.
    """
    targets = [p for p in pages if p.text_source in (TextSource.OCR, TextSource.VERIFY)]
    if not targets:
        return
    if not ocr_mod.is_available():
        logger.warning(
            "paddleocr 미설치 — %d개 페이지를 OCR 없이 둔다. "
            "requirements-ml.txt 를 설치하면 켜진다.",
            len(targets),
        )
        return

    lang_hint = _guess_lang_hint(pages)
    for p in targets:
        image = ocr_mod.rasterize_page(pdf_bytes, p.page - 1)
        ocr_text, used_lang = ocr_mod.run_ocr(image, lang_hint=lang_hint)
        ocr_text = normalize_text(ocr_text)
        if p.text_source is TextSource.VERIFY and len(p.text) >= len(ocr_text):
            continue  # 기존 텍스트 레이어가 더 완전하다고 판단, 그대로 둔다
        p.text = ocr_text
        p.ocr_lang = used_lang


def extract_document(pdf_bytes: bytes, *, with_tables: bool = True, ocr: bool = True) -> Document:
    """PDF 바이트 → 페이지별 정규화 텍스트 + 경로 판정.

    표 추출은 비용이 있어서 끌 수 있게 두었다. 별지의 권리 명세가 표로 들어가는
    템플릿이 있으므로 기본값은 켜 둔다.

    `ocr=True`(기본)면 OCR/VERIFY 페이지를 실제로 OCR한다. `paddleocr`이 없는
    환경에서는 자동으로 건너뛰고 경고만 남긴다 — CI에서도 이 함수가 예외 없이
    동작해야 하기 때문이다.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = []
        for idx, page in enumerate(pdf.pages, start=1):
            sig = _page_signals(page)
            tables = []
            if with_tables:
                tables = [
                    [[normalize_text(c or "").strip() for c in row] for row in tbl]
                    for tbl in (page.extract_tables() or [])
                ]
            pages.append(
                Page(
                    page=idx,
                    text=normalize_text(page.extract_text() or ""),
                    text_source=route(sig),
                    signals=sig,
                    tables=tables,
                )
            )

    if ocr:
        _fill_via_ocr(pdf_bytes, pages)

    return Document(
        file_hash=hashlib.sha256(pdf_bytes).hexdigest(),
        page_count=len(pages),
        pages=pages,
    )

"""PDF → 페이지별 원문 추출.

**바이트를 받는다.** 파이프라인 진입점이 `retrieve_contract_chunks(pdf_bytes)`이고
파일 경로가 없기 때문이다. 경로 대신 바이트를 다루면 부수 효과도 하나 얻는데,
프로젝트 경로에 한글이 섞여 있어도(`d:/오픈소스 대회 자료/...`) 영향을 받지 않는다.

PyMuPDF는 쓰지 않는다 — AGPL이라 프로젝트 전체 라이선스가 오염된다.
텍스트 추출은 pdfplumber, 래스터화(OCR 경로)는 pypdfium2로 처리한다.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

import pdfplumber

from app.pipeline.normalize import normalize_text
from app.pipeline.route import PageSignals, TextSource, route


@dataclass
class Page:
    page: int
    text: str
    text_source: TextSource
    signals: PageSignals
    tables: list[list[list[str]]] = field(default_factory=list)


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


def extract_document(pdf_bytes: bytes, *, with_tables: bool = True) -> Document:
    """PDF 바이트 → 페이지별 정규화 텍스트 + 경로 판정.

    표 추출은 비용이 있어서 끌 수 있게 두었다. 별지의 권리 명세가 표로 들어가는
    템플릿이 있으므로 기본값은 켜 둔다.
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

    return Document(
        file_hash=hashlib.sha256(pdf_bytes).hexdigest(),
        page_count=len(pages),
        pages=pages,
    )

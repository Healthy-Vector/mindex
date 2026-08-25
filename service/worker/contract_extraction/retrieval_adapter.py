"""PDF 바이트를 OCR·Retrieval 구현에 연결하는 Adapter."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .interface import RetrievalBundle


def retrieve_contract_chunks(pdf_bytes: bytes) -> RetrievalBundle:
    """PDF bytes → OCR parse → field retrieval → RetrievalBundle."""

    if not pdf_bytes:
        raise ValueError("PDF bytes must not be empty")

    # OCR 담당 브랜치가 최종 병합되면 제공되는 함수다.
    from scripts.build_retrieval_bundle import build_bundle
    from scripts.ocr_parse_sample import build_payload

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as temp_file:
            temp_file.write(pdf_bytes)
            temp_path = Path(temp_file.name)

        parsed = build_payload(
            temp_path,
            max_chars=1200,
            overlap=150,
            embed=False,
        )
        bundle = build_bundle(
            parsed,
            top_k=5,
            min_score=0.15,
        )

        return RetrievalBundle.from_dict(bundle)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

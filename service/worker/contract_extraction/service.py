#!/usr/bin/env python3
"""Document retrieval과 계약 추출 파이프라인을 연결하는 서비스.

Retrieval 함수는 외부에서 명시적으로 주입한다. 운영 환경에서 Mock을
자동 선택하지 않으며, 추출·검증·정규화·축약 결과를 ExtractionResult로 반환한다.
"""
from __future__ import annotations

import uuid
from typing import Callable

from .extractor import extract as extract_contract
from .interface import ExtractionResult, RetrievalBundle
from .normalizer import normalize_contract
from .projector import project
from .validator import validate

RetrieveFn = Callable[[bytes], RetrievalBundle]
OnStageFn = Callable[[str], None]


def run_extraction(
    pdf_bytes: bytes,
    retrieve_fn: RetrieveFn,
    extractor=None,
    request_id: str | None = None,
    on_stage: OnStageFn | None = None,
) -> ExtractionResult:
    """PDF 바이트 → Document retrieval → 추출·검증·정규화·축약 → ExtractionResult.

    extractor 를 안 주면 extractor.py 의 기본값(OllamaExtractor)을 쓴다
    (테스트에서는 fixture 기반 fake extractor 를 넘겨서 Ollama 없이 검증한다).
    on_stage("OCR"/"LLM") 콜백 — worker.py 가 staging.extract_job.stage 를 갱신하는 데 쓴다
    (api 명세서 §3 — 화면이 "파싱 중"/"추출 중"을 이 값으로 구분해서 보여줌).
    """
    if on_stage:
        on_stage("OCR")
    bundle = retrieve_fn(pdf_bytes)

    if on_stage:
        on_stage("LLM")
    bundle_dict = bundle.model_dump(mode="json")  # extractor/validator 는 RetrievalBundle 의 dict 형태를 받는다
    raw = extract_contract(bundle_dict, extractor=extractor)
    validation = validate(raw, bundle_dict)
    normalized = normalize_contract(raw)
    compact = project(
        normalized,
        request_id=request_id or f"req-{uuid.uuid4().hex[:12]}",
        source_document_ref=bundle.document.file_hash,
    )

    return ExtractionResult(raw=raw, validation=validation, normalized=normalized, compact=compact)


if __name__ == "__main__":
    print("service.py 는 실제 Ollama 호출이 필요합니다 (run_extraction() 기본 extractor=OllamaExtractor).")
    print("Ollama 없이 전체 흐름 확인은 tests/test_service_smoke.py 를 실행하세요.")

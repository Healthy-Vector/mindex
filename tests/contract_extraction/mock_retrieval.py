#!/usr/bin/env python3
"""
Document retrieval 실제 구현 나오기 전까지 쓰는 Mock 어댑터.

팀원(고유경) 확정 계약(2026-08-22):
    retrieve_contract_chunks(pdf_bytes: bytes) -> RetrievalBundle

실제 Document retrieval이 준비되면 이 파일의 retrieve_contract_chunks() 를 실제 구현으로
교체하거나, service.py 의 run_extraction() 호출부에서 import 만 바꾸면 된다.
pdf_bytes 는 지금은 무시하고 항상 같은 mock_retrieved_chunks.json 을 돌려준다.
"""
from __future__ import annotations

import json
import os

from service.worker.contract_extraction.interface import RetrievalBundle

HERE = os.path.dirname(os.path.abspath(__file__))


def retrieve_contract_chunks(pdf_bytes: bytes) -> RetrievalBundle:
    """Mock: pdf_bytes 내용과 무관하게 mock_retrieved_chunks.json 을 반환한다."""
    with open(os.path.join(HERE, "fixtures", "mock_retrieved_chunks.json"), encoding="utf-8") as f:
        payload = json.load(f)
    return RetrievalBundle.from_dict(payload)

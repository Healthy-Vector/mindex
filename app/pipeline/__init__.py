"""OCR/파싱 → 임베딩 → 필드별 회수 파이프라인 (Task1).

공개 진입점은 하나다.

    from app.pipeline import retrieve_contract_chunks
    bundle = retrieve_contract_chunks(pdf_bytes)

내부 단계는 각각 따로 쓸 수 있게 나눠 두었다.
extract -> segment -> chunk -> embed -> retrieval 순서로 의존한다.
"""

from app.pipeline.service import SCHEMA_VERSION, retrieve_contract_chunks

__all__ = ["SCHEMA_VERSION", "retrieve_contract_chunks"]

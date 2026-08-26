"""OCR/파싱 → 임베딩 → 필드별 회수 파이프라인 (Task1).

공개 진입점은 하나다.

    from app.pipeline import retrieve_contract_chunks
    bundle = retrieve_contract_chunks(pdf_bytes)
    payload = bundle.model_dump(mode="json")   # Task2에 넘길 JSON

내부 단계는 각각 따로 쓸 수 있게 나눠 두었다.
extract -> segment -> chunk -> embed -> retrieval 순서로 의존한다.
출력 규격은 app/schemas/pipeline.py 에 있다.
"""

from app.pipeline.service import retrieve_contract_chunks
from app.schemas.pipeline import SCHEMA_VERSION, RetrievalBundle

__all__ = ["SCHEMA_VERSION", "RetrievalBundle", "retrieve_contract_chunks"]

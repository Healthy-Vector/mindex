"""파이프라인 진입점 — `retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle`.

Task1의 담당 경계 전체가 이 함수 하나다.

    [화면] --PDF--> retrieve_contract_chunks --RetrievalBundle--> [Task2 LLM] --> [Worker] --> DB

`contract_id`도 `tenant_id`도 받지 않으므로 **Task1은 DB에 쓸 수 없다.** 적재는
사용자가 저장을 확정한 시점에 Worker가 한다. 그래서 임베딩 벡터를 번들에 실어
보낸다. 안 그러면 사용자 검색용 벡터가 어디에도 남지 않아 검색할 때마다 PDF를
다시 파싱해야 한다.
"""

from __future__ import annotations

import logging

from app.pipeline import embed as embed_mod
from app.pipeline.chunk import Chunk, build_chunks, chunk_stats
from app.pipeline.extract import extract_document
from app.pipeline.retrieval import FIELD_QUERIES, Hit, retrieve
from app.pipeline.segment import segment

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "mindex.retrieval-bundle.v0.2"


def _chunk_payload(c: Chunk) -> dict:
    return {
        "chunk_id": c.chunk_id,
        "chunk_index": c.chunk_index,
        "clause_no": c.clause_no,
        "clause_title": c.clause_title,
        "clause_kind": str(c.clause_kind),
        "lang": c.lang,
        "text": c.text,
        # 페이지는 범위로 준다. 조항이 페이지를 넘는 경우가 실측 9.4%다.
        "page_start": c.page_start,
        "page_end": c.page_end,
        # DB의 page 단일 컬럼 호환용. 컬럼 분리 협의가 끝나면 뺀다.
        "page": c.page,
        "location": {
            "page_start": c.page_start,
            "page_end": c.page_end,
            "clause_no": c.clause_no,
            "clause_kind": str(c.clause_kind),
            "char_start": c.char_start,
            "char_end": c.char_end,
        },
        "char_start": c.char_start,
        "char_end": c.char_end,
        "embedding": c.embedding,
    }


def _hit_payload(h: Hit, field_name: str) -> dict:
    return {
        "chunk_id": h.chunk_id,
        "score": h.score,
        "lexical": h.lexical,
        "semantic": h.semantic,
        "matched_field": field_name,
        "match_reasons": h.reasons,
    }


def retrieve_contract_chunks(
    pdf_bytes: bytes,
    *,
    file_name: str | None = None,
    embed: bool = True,
    top_k: int = 5,
    min_score: float = 0.15,
    semantic_weight: float = 0.0,
) -> dict:
    """PDF 바이트 → 필드별 회수 결과 묶음.

    `embed=True`인데 실행 환경에 `sentence_transformers`가 없으면 임베딩 없이
    진행하고 경고만 남긴다. CI에는 ML 의존성이 없으므로 이 경로가 정상 동작이다.
    """
    doc = extract_document(pdf_bytes)
    lang, full_text, clauses = segment(doc.pages)
    chunks = build_chunks(clauses, lang, doc.file_hash)
    stats = chunk_stats(chunks, clauses)

    embedded = False
    query_vectors = None
    if embed:
        if embed_mod.is_available():
            embed_mod.attach_embeddings(chunks)
            embedded = True
            if semantic_weight > 0:
                names = list(FIELD_QUERIES)
                vecs = embed_mod.embed_queries([FIELD_QUERIES[n] for n in names])
                query_vectors = dict(zip(names, vecs, strict=True))
        else:
            logger.warning(
                "sentence_transformers 미설치 — 임베딩 없이 어휘 회수만 수행한다. "
                "requirements-ml.txt 를 설치하면 켜진다."
            )

    fields = retrieve(
        chunks,
        top_k=top_k,
        min_score=min_score,
        semantic_weight=semantic_weight if query_vectors else 0.0,
        query_vectors=query_vectors,
    )

    # 같은 청크가 여러 필드에 걸린다. 본문은 아래에 한 번만 두고
    # fields[]는 chunk_id로 참조하게 해서 중복을 없앤다.
    used = {h.chunk_id for hits in fields.values() for h in hits}
    referenced = [c for c in chunks if c.chunk_id in used]

    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "file_name": file_name,
            "file_hash": doc.file_hash,
            "mime_type": "application/pdf",
            "page_count": doc.page_count,
            "language": lang,
            "text_source_summary": doc.source_summary,
            "text_normalization": "NFC",
            "embedding_model": embed_mod.MODEL_NAME,
            "embedding_dim": embed_mod.EMBEDDING_DIM,
            "embedded": embedded,
            "full_text_length": len(full_text),
        },
        "retrieval": {
            "scorer": "hybrid" if query_vectors else "lexical-v0",
            "semantic_weight": semantic_weight if query_vectors else 0.0,
            "top_k": top_k,
            "min_score": min_score,
            "field_count": len(fields),
            "clause_total": len(clauses),
            "chunk_total": stats.total,
            "chunk_indexable": stats.indexable,
            "chunk_referenced": len(referenced),
        },
        "fields": {
            name: [_hit_payload(h, name) for h in hits] for name, hits in fields.items()
        },
        "chunks": [_chunk_payload(c) for c in referenced],
    }

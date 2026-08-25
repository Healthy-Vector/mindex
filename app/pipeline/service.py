"""파이프라인 진입점 — `retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle`.

Task1의 담당 경계 전체가 이 함수 하나다.

    [화면] --PDF--> retrieve_contract_chunks --RetrievalBundle--> [Task2 LLM] --> [Worker] --> DB

`contract_id`도 `tenant_id`도 받지 않으므로 **Task1은 DB에 쓸 수 없다.** 적재는
사용자가 저장을 확정한 시점에 Worker가 한다. 그래서 임베딩 벡터를 번들에 실어
보낸다. 안 그러면 사용자 검색용 벡터가 어디에도 남지 않아 검색할 때마다 PDF를
다시 파싱해야 한다.

반환값은 pydantic 모델이다. JSON이 필요하면 `.model_dump(mode="json")`를 쓴다.
모델을 거치는 이유는 직렬화가 아니라 검증이다 — offset 정합성, 페이지 범위,
`fields[]`의 참조 무결성이 여기서 걸린다. 자세한 내용은 app/schemas/pipeline.py.
"""

from __future__ import annotations

import logging

from app.pipeline import embed as embed_mod
from app.pipeline.chunk import Chunk, build_chunks, chunk_stats
from app.pipeline.extract import extract_document
from app.pipeline.retrieval import (
    DEFAULT_SEMANTIC_WEIGHT,
    FIELD_QUERIES,
    HYBRID_SCORER,
    LEXICAL_SCORER,
    Hit,
    retrieve,
)
from app.pipeline.segment import segment
from app.schemas.pipeline import (
    SCHEMA_VERSION,
    BundleChunk,
    ChunkLocation,
    DocumentInfo,
    FieldHit,
    RetrievalBundle,
    RetrievalInfo,
)

logger = logging.getLogger(__name__)

__all__ = ["SCHEMA_VERSION", "retrieve_contract_chunks"]


def _to_bundle_chunk(c: Chunk) -> BundleChunk:
    return BundleChunk(
        chunk_id=c.chunk_id,
        chunk_index=c.chunk_index,
        clause_no=c.clause_no,
        clause_title=c.clause_title,
        clause_kind=c.clause_kind,
        lang=c.lang,
        text=c.text,
        # 페이지는 범위로 준다. 조항이 페이지를 넘는 경우가 실측 9.4%다.
        page_start=c.page_start,
        page_end=c.page_end,
        # DB의 page 단일 컬럼 호환용. 컬럼 분리 협의가 끝나면 뺀다.
        page=c.page,
        location=ChunkLocation(
            page_start=c.page_start,
            page_end=c.page_end,
            clause_no=c.clause_no,
            clause_kind=c.clause_kind,
            char_start=c.char_start,
            char_end=c.char_end,
        ),
        char_start=c.char_start,
        char_end=c.char_end,
        indexable=c.indexable,
        embedding=c.embedding,
    )


def _to_field_hit(h: Hit, field_name: str) -> FieldHit:
    return FieldHit(
        chunk_id=h.chunk_id,
        score=h.score,
        lexical=h.lexical,
        semantic=h.semantic,
        semantic_norm=h.semantic_norm,
        matched_field=field_name,
        match_reasons=h.reasons,
    )


def retrieve_contract_chunks(
    pdf_bytes: bytes,
    *,
    file_name: str | None = None,
    embed: bool = True,
    top_k: int = 5,
    min_score: float = 0.15,
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
) -> RetrievalBundle:
    """PDF 바이트 → 필드별 회수 결과 묶음.

    `embed=True`인데 실행 환경에 `sentence_transformers`가 없으면 임베딩 없이
    진행하고 경고만 남긴다. CI에는 ML 의존성이 없으므로 이 경로가 정상 동작이다.
    그때는 `semantic_weight`가 무시되고 어휘 회수만 수행한다.
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

    # chunks[]는 회수된 것만이 아니라 **계약서 전문**을 담는다(v0.4). Worker가
    # 이걸 그대로 contract_chunk에 적재하고, 그 뒤로는 시스템 전체의 검색
    # 인덱스가 된다. 회수된 것만 넘기면 비밀유지·준거법처럼 우리 6개 필드에
    # 안 걸리는 조항이 검색에서 영영 사라진다. 같은 청크가 여러 필드에 걸리는
    # 중복은 fields[]가 본문 없이 chunk_id만 참조하는 것으로 이미 막고 있다.
    used = {h.chunk_id for hits in fields.values() for h in hits}

    # 색인 제외 청크(별지 제목 등)는 애초에 임베딩을 받지 않는다. 그것 때문에
    # embedded가 False로 떨어지면 안 되므로 색인 대상만 헤아린다.
    embedded = embedded and all(c.embedding is not None for c in chunks if c.indexable)

    return RetrievalBundle(
        schema_version=SCHEMA_VERSION,
        document=DocumentInfo(
            file_name=file_name,
            file_hash=doc.file_hash,
            page_count=doc.page_count,
            language=lang,
            text_source_summary=doc.source_summary,
            embedding_model=embed_mod.MODEL_NAME,
            embedding_dim=embed_mod.EMBEDDING_DIM,
            embedded=embedded,
            full_text_length=len(full_text),
        ),
        retrieval=RetrievalInfo(
            scorer=HYBRID_SCORER if query_vectors else LEXICAL_SCORER,
            semantic_weight=semantic_weight if query_vectors else 0.0,
            top_k=top_k,
            min_score=min_score,
            field_count=len(fields),
            clause_total=len(clauses),
            chunk_total=stats.total,
            chunk_indexable=stats.indexable,
            chunk_referenced=len(used),
        ),
        fields={
            name: [_to_field_hit(h, name) for h in hits]
            for name, hits in fields.items()
        },
        chunks=[_to_bundle_chunk(c) for c in chunks],
    )

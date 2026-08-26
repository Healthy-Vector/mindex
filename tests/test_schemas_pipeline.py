"""출력 규격 검증 — 불변조건이 실제로 걸리는지 확인한다.

검증기를 써놓고 안 걸리면 없는 것만 못하다. 오히려 "검증했다"는 착각을 남긴다.
그래서 정상 번들을 만든 뒤 **한 군데씩 망가뜨려** 각 규칙이 반응하는지 본다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.pipeline import (
    EMBEDDING_DIM,
    RETRIEVAL_FIELDS,
    BundleChunk,
    ChunkLocation,
    ClauseKind,
    DocumentInfo,
    FieldHit,
    RetrievalBundle,
    RetrievalInfo,
)

HASH = "a" * 64
TEXT = "이용지역은 대한민국으로 한다."


def make_chunk(**over) -> BundleChunk:
    base = dict(
        chunk_id="abc123def456-0001",
        chunk_index=1,
        clause_no="제3조",
        clause_title="이용허락",
        clause_kind=ClauseKind.ARTICLE,
        lang="ko",
        text=TEXT,
        page_start=1,
        page_end=2,
        page=1,
        char_start=100,
        char_end=100 + len(TEXT),
        embedding=None,
    )
    base.update(over)
    base.setdefault(
        "location",
        ChunkLocation(
            page_start=base["page_start"],
            page_end=base["page_end"],
            clause_no=base["clause_no"],
            clause_kind=base["clause_kind"],
            char_start=base["char_start"],
            char_end=base["char_end"],
        ),
    )
    return BundleChunk(**base)


def make_bundle(chunks=None, fields=None, **over) -> RetrievalBundle:
    chunks = [make_chunk()] if chunks is None else chunks
    if fields is None:
        fields = dict.fromkeys(RETRIEVAL_FIELDS, [])
        fields["territory"] = [
            FieldHit(
                chunk_id=chunks[0].chunk_id,
                score=0.9,
                lexical=0.9,
                matched_field="territory",
            )
        ]
    base = dict(
        document=DocumentInfo(
            file_hash=HASH,
            page_count=3,
            language="ko",
            text_source_summary={"TEXT_LAYER": 3},
            embedding_model="intfloat/multilingual-e5-large",
            full_text_length=5000,
        ),
        retrieval=RetrievalInfo(
            scorer="lexical-v0",
            top_k=5,
            min_score=0.15,
            field_count=len(RETRIEVAL_FIELDS),
            clause_total=24,
            # v0.4 — chunks[]가 계약서 전문이므로 통계가 실제와 맞아야 한다.
            chunk_total=len(chunks),
            chunk_indexable=sum(1 for c in chunks if c.indexable),
            chunk_referenced=len(
                {h.chunk_id for hits in fields.values() for h in hits}
            ),
        ),
        fields=fields,
        chunks=chunks,
    )
    base.update(over)
    return RetrievalBundle(**base)


def test_정상_번들은_통과한다():
    assert make_bundle().document.language == "ko"


# ── 청크 단위 불변조건 ────────────────────────────────────────────────────
def test_offset_길이가_본문과_다르면_거부():
    """Evidence Anchoring이 이 offset으로 원문을 되짚는다. 밀리면 오인용이 된다."""
    with pytest.raises(ValidationError, match="offset 길이"):
        make_chunk(char_end=100 + len(TEXT) + 5)


def test_페이지_범위가_뒤집히면_거부():
    with pytest.raises(ValidationError, match="page_start > page_end"):
        make_chunk(page_start=3, page_end=2, page=3)


def test_page_호환값이_시작페이지와_다르면_거부():
    with pytest.raises(ValidationError, match="page 호환값"):
        make_chunk(page=2)


def test_location이_본체와_어긋나면_거부():
    loc = ChunkLocation(
        page_start=1,
        page_end=2,
        clause_no="제3조",
        clause_kind=ClauseKind.ARTICLE,
        char_start=999,
        char_end=999 + len(TEXT),
    )
    with pytest.raises(ValidationError, match="location offset"):
        make_chunk(location=loc)


def test_임베딩_차원이_다르면_거부():
    """contract_chunk.embedding 이 vector(1024)다. 다르면 적재가 깨진다."""
    with pytest.raises(ValidationError, match="임베딩 차원"):
        make_chunk(embedding=[0.1] * 512)


def test_올바른_차원의_임베딩은_통과():
    assert len(make_chunk(embedding=[0.0] * EMBEDDING_DIM).embedding) == EMBEDDING_DIM


# ── 번들 단위 불변조건 ────────────────────────────────────────────────────
def test_회수_필드가_빠지면_거부():
    fields = dict.fromkeys(RETRIEVAL_FIELDS, [])
    del fields["parties"]
    with pytest.raises(ValidationError, match="회수 필드 누락"):
        make_bundle(fields=fields)


def test_모르는_필드가_있으면_거부():
    fields = dict.fromkeys(RETRIEVAL_FIELDS, [])
    fields["governing_law"] = []
    with pytest.raises(ValidationError, match="모르는 회수 필드"):
        make_bundle(fields=fields)


def test_끊긴_chunk_id_참조를_잡는다():
    """fields[]는 본문 대신 id만 담는다. 참조가 끊기면 Task2가 근거를 못 읽는다."""
    fields = dict.fromkeys(RETRIEVAL_FIELDS, [])
    fields["period"] = [
        FieldHit(chunk_id="없는-0099", score=0.5, lexical=0.5, matched_field="period")
    ]
    with pytest.raises(ValidationError, match="참조가 끊긴"):
        make_bundle(fields=fields)


def test_matched_field가_어긋나면_거부():
    chunk = make_chunk()
    fields = dict.fromkeys(RETRIEVAL_FIELDS, [])
    fields["period"] = [
        FieldHit(
            chunk_id=chunk.chunk_id, score=0.5, lexical=0.5, matched_field="territory"
        )
    ]
    with pytest.raises(ValidationError, match="matched_field"):
        make_bundle(chunks=[chunk], fields=fields)


def test_top_k를_넘는_결과는_거부():
    chunk = make_chunk()
    hits = [
        FieldHit(
            chunk_id=chunk.chunk_id, score=0.5, lexical=0.5, matched_field="territory"
        )
        for _ in range(6)
    ]
    fields = dict.fromkeys(RETRIEVAL_FIELDS, [])
    fields["territory"] = hits
    with pytest.raises(ValidationError, match="top_k"):
        make_bundle(chunks=[chunk], fields=fields)


def test_chunk_id_중복을_잡는다():
    c = make_chunk()
    with pytest.raises(ValidationError, match="chunk_id가 중복"):
        make_bundle(chunks=[c, make_chunk()])


def test_embedded인데_벡터가_없으면_거부():
    doc = DocumentInfo(
        file_hash=HASH,
        page_count=3,
        language="ko",
        text_source_summary={"TEXT_LAYER": 3},
        embedding_model="intfloat/multilingual-e5-large",
        embedded=True,
        full_text_length=5000,
    )
    with pytest.raises(ValidationError, match="벡터가 없는 청크"):
        make_bundle(document=doc)


# ── v0.4 — chunks[]는 계약서 전문 corpus다 ────────────────────────────────
def test_chunks가_전문이_아니면_거부():
    """일부만 담기면 Worker가 contract_chunk를 반쪽만 채우고, 빠진 조항은
    검색에서 영영 사라진다. 실측상 회수분만 담으면 61.4%밖에 안 남는다."""
    b = make_bundle()
    with pytest.raises(ValidationError, match="계약서 전문이어야 한다"):
        make_bundle(retrieval=b.retrieval.model_copy(update={"chunk_total": 26}))


def test_색인_제외_청크에_벡터가_붙으면_거부():
    """내용 없는 조각에 벡터를 주면 어떤 질의와도 어중간하게 가까워서
    정답을 밀어낸다. 실수로 붙는 걸 막는다."""
    with pytest.raises(ValidationError, match="색인 제외 청크에 벡터"):
        make_chunk(indexable=False, embedding=[0.1] * EMBEDDING_DIM)


def test_색인_제외_청크는_벡터가_없어도_embedded를_유지한다():
    """별지 제목처럼 60자 미만인 조각은 원래 벡터를 안 받는다.
    그것 때문에 embedded가 거짓이 되면 안 된다."""
    body = make_chunk(embedding=[0.1] * EMBEDDING_DIM)
    head = make_chunk(
        chunk_id="abc123def456-0002", chunk_index=2, indexable=False, embedding=None
    )
    doc = DocumentInfo(
        file_hash=HASH,
        page_count=3,
        language="ko",
        text_source_summary={"TEXT_LAYER": 3},
        embedding_model="intfloat/multilingual-e5-large",
        embedded=True,
        full_text_length=5000,
    )
    bundle = make_bundle(chunks=[body, head], document=doc)
    assert bundle.retrieval.chunk_indexable == 1
    assert bundle.retrieval.chunk_total == 2


def test_chunk_index_정렬이_깨지면_거부():
    """Worker가 contract_chunk를 문서 순서대로 적재한다."""
    a = make_chunk(chunk_id="abc123def456-0005", chunk_index=5)
    b = make_chunk(chunk_id="abc123def456-0002", chunk_index=2)
    with pytest.raises(ValidationError, match="문서 순서"):
        make_bundle(chunks=[a, b])


def test_chunk_indexable_이_실제와_다르면_거부():
    b = make_bundle()
    with pytest.raises(ValidationError, match="chunk_indexable"):
        make_bundle(retrieval=b.retrieval.model_copy(update={"chunk_indexable": 99}))


def test_점수는_0과_1_사이():
    with pytest.raises(ValidationError):
        FieldHit(chunk_id="x", score=1.4, lexical=0.5, matched_field="territory")


def test_해시는_sha256_길이여야_한다():
    with pytest.raises(ValidationError):
        DocumentInfo(
            file_hash="짧다",
            page_count=1,
            language="ko",
            text_source_summary={"TEXT_LAYER": 1},
            embedding_model="m",
            full_text_length=1,
        )

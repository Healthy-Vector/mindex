"""Task1 출력 규격 — `RetrievalBundle`.

Task2(LLM 추출·정규화)가 받는 계약이다. 지금까지는 dict를 손으로 쌓아 올려서
필드가 빠지거나 값이 어긋나도 조용히 통과했다. 여기서 타입으로 고정한다.

## 여기서 검사하는 불변조건

단순한 타입 검사가 아니라 **틀리면 다음 단계가 조용히 망가지는 것들**을 막는다.

- `char_end - char_start == len(text)` — Evidence Anchoring이 이 offset으로 원문을
  되짚는다. 어긋나면 사용자 화면에 엉뚱한 구절이 근거로 뜬다.
- `page_start <= page_end` — 조항이 페이지를 걸치는 경우가 실측 9.4%다.
- **`fields[]`의 모든 `chunk_id`가 `chunks[]`에 있어야 한다** — 회수 결과는
  본문을 직접 담지 않고 id로 참조한다. 참조가 끊기면 Task2가 근거를 못 읽는다.
- **`chunks[]`가 계약서 전문이어야 한다** — `chunk_total == len(chunks)`.
  아래 v0.4 설명 참조.
- `embedding` 길이 1024 — `contract_chunk.embedding`이 `vector(1024)`다.

## v0.4 — `chunks[]`는 회수 결과가 아니라 계약서 corpus다

v0.3까지 `chunks[]`에는 **어떤 field에든 회수된 청크만** 담았다. 중복을 줄이려던
것이었는데, 받는 쪽에서 이게 `contract_chunk` 적재분이 되면서 문제가 됐다.

실측(샘플 10건): 전체 215개 중 회수 132개, **회수율 61.4%**. 그리고 빠지는
83개가 무작위가 아니다. 비밀유지·해지·통지·불가항력·준거법 — **회수 스코어러가
일부러 감점하는 DISTRACTOR 조항들**이다. 추출 6개 필드에 대해서는 그게 맞지만,
`contract_chunk`는 시스템 전체의 검색 인덱스(SFR-008/009)라서 그대로 넣으면
"비밀유지 조항이 있는 계약"을 영원히 못 찾는다.

그래서 두 축을 분리했다.

    chunks[]  = 계약서 전문 corpus. pgvector 적재·RAG 검색의 원본
    fields{}  = 그 위에 얹힌 회수 결과. chunk_id로 참조만 한다

색인 제외 청크(`indexable=False`, 별지 제목처럼 60자 미만)도 **본문은 담고
벡터만 None**으로 둔다. `contract_chunk.embedding`이 nullable이라 원문은
보존되고 검색 품질은 안 망친다.

이 파일은 leaf다. `app.pipeline`을 import하지 않는다. 그래야 스키마만 필요한
쪽(Task2, Worker)이 pdfplumber까지 끌어오지 않는다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "mindex.retrieval-bundle.v0.4"

#: 임베딩 차원 — DB의 `contract_chunk.embedding vector(1024)`와 맞물린다.
EMBEDDING_DIM = 1024

#: 회수 대상 필드. Task2와 합의된 목록이다.
#:
#: 주의: `rights_type`은 **회수 질의 이름일 뿐**이다. 추출 결과 필드로 굳으면
#: 안 된다. ERD v3에서 이 축은 `legal_right`와 `exploitation_mode`로 분리돼
#: 있고 프로젝트가 둘을 절대 합치지 않는다고 못박았다. Ground Truth도
#: `LEGAL_RIGHT`/`EXPLOITATION_MODE`로 이미 나뉘어 있다.
RETRIEVAL_FIELDS = (
    "territory",
    "rights_type",
    "period",
    "exclusivity",
    "payment",
    "parties",
)


class TextSource(StrEnum):
    """페이지 텍스트를 어디서 얻었는가."""

    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"
    #: 텍스트 레이어가 미심쩍어 OCR과 대조가 필요한 페이지.
    VERIFY = "VERIFY"


class ClauseKind(StrEnum):
    FRONT_MATTER = "FRONT_MATTER"
    ARTICLE = "ARTICLE"
    #: 별지. T5·T6 템플릿은 권리 명세를 전부 여기 넣는다.
    SCHEDULE = "SCHEDULE"
    #: 별지 안의 개별 권리부여 한 건.
    GRANT_ITEM = "GRANT_ITEM"
    #: 조항 머리를 하나도 못 찾은 문서.
    UNSEGMENTED = "UNSEGMENTED"


class ChunkLocation(BaseModel):
    """청크가 원문 어디에서 왔는지. Evidence 인용의 좌표다."""

    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    clause_no: str
    clause_kind: ClauseKind
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class BundleChunk(BaseModel):
    chunk_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    clause_no: str
    clause_title: str = ""
    clause_kind: ClauseKind
    lang: str
    text: str = Field(min_length=1)

    #: 조항이 페이지를 걸치므로 범위로 준다.
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    #: DB의 `page` 단일 컬럼 호환값. 컬럼 분리 협의가 끝나면 뺀다.
    page: int = Field(ge=1)

    location: ChunkLocation
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    #: 검색 색인 대상인가. False면 `embedding`이 None인 것이 **정상**이다.
    #:
    #: 이 구분이 없으면 받는 쪽이 `embedding: null`을 보고 "임베딩이 실패했나"와
    #: "원래 안 주나"를 구분할 수 없다. 실측상 제외 대상은 별지 제목 줄처럼
    #: 60자 미만인 조각이다(샘플 215개 중 3개). 내용 없는 조각에 벡터를 주면
    #: e5 공간에서 어떤 질의와도 어중간하게 가까워서 정답을 밀어낸다.
    indexable: bool = True

    #: Worker가 `contract_chunk.embedding`에 적재할 벡터. 임베딩 전에는 None.
    #: `indexable=False`면 임베딩 후에도 None이다.
    embedding: list[float] | None = None

    @model_validator(mode="after")
    def _check(self) -> BundleChunk:
        if self.page_start > self.page_end:
            raise ValueError(f"{self.chunk_id}: page_start > page_end")
        if self.page != self.page_start:
            raise ValueError(f"{self.chunk_id}: page 호환값은 page_start와 같아야 한다")
        # offset이 텍스트 길이와 어긋나면 Evidence 인용이 밀린다
        if self.char_end - self.char_start != len(self.text):
            raise ValueError(
                f"{self.chunk_id}: offset 길이 {self.char_end - self.char_start} != "
                f"본문 길이 {len(self.text)}"
            )
        loc = self.location
        if (loc.char_start, loc.char_end) != (self.char_start, self.char_end):
            raise ValueError(f"{self.chunk_id}: location offset이 본체와 다르다")
        if (loc.page_start, loc.page_end) != (self.page_start, self.page_end):
            raise ValueError(f"{self.chunk_id}: location 페이지가 본체와 다르다")
        if not self.indexable and self.embedding is not None:
            raise ValueError(f"{self.chunk_id}: 색인 제외 청크에 벡터가 붙었다")
        if self.embedding is not None and len(self.embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"{self.chunk_id}: 임베딩 차원 {len(self.embedding)} != {EMBEDDING_DIM}"
            )
        return self


class FieldHit(BaseModel):
    """한 필드에 대한 회수 결과 한 건. 본문은 담지 않고 `chunk_id`로 참조한다."""

    chunk_id: str
    score: float = Field(ge=0.0, le=1.0)
    lexical: float = Field(ge=0.0, le=1.0)
    #: 질의 벡터와의 코사인 유사도(원값). 임베딩을 안 쓰면 None.
    #:
    #: e5 코사인은 좁은 구간에 눌려 있어(실측 0.68~0.86) 절대값에 의미가 없다.
    #: 참고용으로만 싣고, 점수 합산에는 아래 `semantic_norm`을 쓴다.
    semantic: float | None = Field(default=None, ge=-1.0, le=1.0)
    #: 위 값을 **문서 안에서** 0~1로 편 것. `score`는 이 값으로 계산된다.
    #: 문서마다 다시 펴므로 문서 간 비교에는 쓸 수 없다.
    semantic_norm: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_field: str
    #: 어떤 신호가 걸렸는지. `+이용지역` / `-준거법` 형태.
    match_reasons: list[str] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    file_name: str | None = None
    file_hash: str = Field(min_length=64, max_length=64)
    mime_type: str = "application/pdf"
    page_count: int = Field(ge=1)
    language: str
    #: 경로별 페이지 수. 예) {"TEXT_LAYER": 8}
    text_source_summary: dict[TextSource, int]
    text_normalization: str = "NFC"
    embedding_model: str
    embedding_dim: int = EMBEDDING_DIM
    embedded: bool = False
    full_text_length: int = Field(ge=0)


class RetrievalInfo(BaseModel):
    scorer: str
    semantic_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    top_k: int = Field(ge=1)
    min_score: float = Field(ge=0.0, le=1.0)
    field_count: int = Field(ge=1)
    clause_total: int = Field(ge=0)
    #: 전체 청크 수. v0.4부터 `len(chunks)`와 같아야 한다.
    chunk_total: int = Field(ge=0)
    #: 그중 색인 대상. 별지 제목처럼 60자 미만인 조각은 빠지고 벡터를 받지 않는다.
    chunk_indexable: int = Field(ge=0)
    #: 그중 `fields{}`가 실제로 가리킨 청크 수. **통계값일 뿐 `chunks[]`의 크기가
    #: 아니다** — v0.3까지는 같았으나 v0.4에서 갈라졌다.
    chunk_referenced: int = Field(ge=0)


class RetrievalBundle(BaseModel):
    """`retrieve_contract_chunks(pdf_bytes)`의 반환값."""

    schema_version: str = SCHEMA_VERSION
    document: DocumentInfo
    retrieval: RetrievalInfo
    #: 필드 이름 → 점수순 회수 결과. `chunks`를 id로 참조만 하고 본문은 안 담는다.
    fields: dict[str, list[FieldHit]]
    #: **계약서 전문 corpus.** 회수 여부와 무관하게 조항 전량이 문서 순서로 담긴다
    #: (`chunk_index` 오름차순). Worker가 `contract_chunk`에 그대로 적재하는 대상이고,
    #: 적재 이후 RAG·하이브리드 검색이 보는 것도 이 집합이다. v0.4 변경 — 위 모듈
    #: docstring 참조.
    chunks: list[BundleChunk]

    @model_validator(mode="after")
    def _check(self) -> RetrievalBundle:
        missing = set(RETRIEVAL_FIELDS) - set(self.fields)
        if missing:
            raise ValueError(f"회수 필드 누락: {sorted(missing)}")
        unknown = set(self.fields) - set(RETRIEVAL_FIELDS)
        if unknown:
            raise ValueError(f"모르는 회수 필드: {sorted(unknown)}")

        known = {c.chunk_id for c in self.chunks}
        if len(known) != len(self.chunks):
            raise ValueError("chunk_id가 중복됐다")

        # 회수 결과가 본문을 못 찾으면 Task2가 근거를 읽을 수 없다
        referenced: set[str] = set()
        for name, hits in self.fields.items():
            for h in hits:
                referenced.add(h.chunk_id)
                if h.chunk_id not in known:
                    raise ValueError(f"{name}: 참조가 끊긴 chunk_id {h.chunk_id}")
                if h.matched_field != name:
                    raise ValueError(
                        f"{name}: matched_field가 {h.matched_field}로 어긋났다"
                    )
            if len(hits) > self.retrieval.top_k:
                raise ValueError(f"{name}: top_k({self.retrieval.top_k})를 넘는 결과")

        # v0.4 — chunks[]는 회수 결과가 아니라 계약서 전문이다. 일부만 담기면
        # Worker가 contract_chunk를 반쪽만 채우고, 빠진 조항은 검색에서 영영
        # 사라진다. 통계값이 아니라 이 불변조건이 그걸 막는다.
        if self.retrieval.chunk_total != len(self.chunks):
            raise ValueError(
                f"chunk_total {self.retrieval.chunk_total} != 실제 {len(self.chunks)} "
                "— chunks[]는 계약서 전문이어야 한다"
            )
        if self.retrieval.chunk_indexable != sum(1 for c in self.chunks if c.indexable):
            raise ValueError(
                f"chunk_indexable {self.retrieval.chunk_indexable} != "
                f"실제 {sum(1 for c in self.chunks if c.indexable)}"
            )
        if self.retrieval.chunk_referenced != len(referenced):
            raise ValueError(
                f"chunk_referenced {self.retrieval.chunk_referenced} != "
                f"실제 {len(referenced)}"
            )
        if [c.chunk_index for c in self.chunks] != sorted(
            c.chunk_index for c in self.chunks
        ):
            raise ValueError("chunks[]가 문서 순서(chunk_index)로 정렬돼 있지 않다")
        # 색인 제외 청크는 벡터가 없는 것이 정상이므로 대상에서 뺀다.
        if self.document.embedded and any(
            c.embedding is None for c in self.chunks if c.indexable
        ):
            raise ValueError("embedded=True인데 색인 대상 중 벡터가 없는 청크가 있다")
        return self

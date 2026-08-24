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
- `embedding` 길이 1024 — `contract_chunk.embedding`이 `vector(1024)`다.

이 파일은 leaf다. `app.pipeline`을 import하지 않는다. 그래야 스키마만 필요한
쪽(Task2, Worker)이 pdfplumber까지 끌어오지 않는다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "mindex.retrieval-bundle.v0.3"

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

    #: Worker가 `contract_chunk.embedding`에 적재할 벡터. 임베딩 전에는 None.
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
    chunk_total: int = Field(ge=0)
    #: 색인 대상 청크 수. 별지 제목처럼 내용 없는 조각은 빠진다.
    chunk_indexable: int = Field(ge=0)
    chunk_referenced: int = Field(ge=0)


class RetrievalBundle(BaseModel):
    """`retrieve_contract_chunks(pdf_bytes)`의 반환값."""

    schema_version: str = SCHEMA_VERSION
    document: DocumentInfo
    retrieval: RetrievalInfo
    #: 필드 이름 → 점수순 회수 결과.
    fields: dict[str, list[FieldHit]]
    #: `fields`가 참조하는 청크의 본문. 같은 청크가 여러 필드에 걸리므로
    #: 여기에 한 번만 두고 id로 참조해 중복을 없앤다.
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
        for name, hits in self.fields.items():
            for h in hits:
                if h.chunk_id not in known:
                    raise ValueError(f"{name}: 참조가 끊긴 chunk_id {h.chunk_id}")
                if h.matched_field != name:
                    raise ValueError(
                        f"{name}: matched_field가 {h.matched_field}로 어긋났다"
                    )
            if len(hits) > self.retrieval.top_k:
                raise ValueError(f"{name}: top_k({self.retrieval.top_k})를 넘는 결과")

        if self.retrieval.chunk_referenced != len(self.chunks):
            raise ValueError(
                f"chunk_referenced {self.retrieval.chunk_referenced} != "
                f"실제 {len(self.chunks)}"
            )
        if self.retrieval.chunk_indexable > self.retrieval.chunk_total:
            raise ValueError("색인 대상이 전체 청크보다 많다")
        if self.document.embedded and any(c.embedding is None for c in self.chunks):
            raise ValueError("embedded=True인데 벡터가 없는 청크가 있다")
        return self

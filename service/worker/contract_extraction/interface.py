#!/usr/bin/env python3
"""
Contract extraction — interface.py

Document retrieval <-> Contract extraction 인터페이스. **2026-08-22 팀원(고유경) 실제 구현 README 기준으로 갱신**
(이전 버전은 "청크가 여러 필드에 걸리면 chunk_id를 복제" 하는 방식이었는데, 실제
retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle 출력은 그렇게 안 한다 — 아래 참고.

실제 구조 (팀원 README `*.retrieval.json` 그대로):
    schema_version   "mindex.retrieval-bundle.v0.1"
    document         파일명/해시/페이지수/언어 등 메타
    retrieval        scorer/top_k/min_score 등 검색 메타
    fields           필드 6개(territory/rights_type/period/exclusivity/payment/parties)
                     각각 점수 내림차순 배열 — FieldMatch 리스트
    chunks[]         검색에 걸린 청크의 정본(중복 없음) — ChunkRecord 리스트

⚠️ KNOWN GAP (팀원 README 로 확인된 실제 동작, 재논의 필요):
    chunks[] 는 "6개 질의 중 하나라도 걸린" 청크만 담는다 (예시: 문서 전체 26청크 중 10개만).
    질의 6개 밖의 필드(legal_right/content/scope_modifiers/agreement_type)의 근거가
    어느 질의에도 안 걸리는 청크에만 있으면, 그 청크 자체가 아예 안 넘어온다 —
    LLM이 못 보거나(ABSENT 오판), validator 의 환각 검증에서 오탐(false hallucination)
    날 수 있다. interface_retrieved_chunks.md §3 에서 이미 요청했던 부분 — 여전히 미해결.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ChunkLocation:
    page: int | None = None
    clause_no: str | None = None
    clause_kind: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    clause_page_span: list[int] | None = None  # 조항이 걸친 페이지 범위 [start, end]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict | None) -> "ChunkLocation | None":
        if not d:
            return None
        return ChunkLocation(
            page=d.get("page"), clause_no=d.get("clause_no"), clause_kind=d.get("clause_kind"),
            char_start=d.get("char_start"), char_end=d.get("char_end"),
            clause_page_span=d.get("clause_page_span"),
        )


@dataclass
class FieldMatch:
    """`fields[필드명][]` 배열 원소. 같은 chunk_id 가 여러 필드에 나올 수 있다."""
    chunk_id: str
    text: str
    page: int | None
    clause: str | None
    location: ChunkLocation | None
    score: float
    matched_field: str
    match_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "FieldMatch":
        return FieldMatch(
            chunk_id=d["chunk_id"], text=d.get("text", ""), page=d.get("page"),
            clause=d.get("clause"), location=ChunkLocation.from_dict(d.get("location")),
            score=d.get("score", 0.0), matched_field=d.get("matched_field", ""),
            match_reasons=d.get("match_reasons", []),
        )


@dataclass
class ChunkRecord:
    """`chunks[]` 정본. chunk_id 기준 중복 없음 — 본문은 여기 한 번만 있다."""
    chunk_id: str
    text: str
    page: int | None
    clause: str | None
    clause_kind: str | None = None
    lang: str | None = None
    location: ChunkLocation | None = None
    embedding: list[float] | None = None  # 임베딩 도입 전에는 항상 None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ChunkRecord":
        return ChunkRecord(
            chunk_id=d["chunk_id"], text=d.get("text", ""), page=d.get("page"),
            clause=d.get("clause"), clause_kind=d.get("clause_kind"), lang=d.get("lang"),
            location=ChunkLocation.from_dict(d.get("location")), embedding=d.get("embedding"),
        )


FIELD_NAMES = ("territory", "rights_type", "period", "exclusivity", "payment", "parties")


@dataclass
class RetrievalBundle:
    schema_version: str = "mindex.retrieval-bundle.v0.1"
    document: dict = field(default_factory=dict)     # file_name/file_hash/page_count/language 등
    retrieval: dict = field(default_factory=dict)     # scorer/top_k/min_score 등
    fields: dict[str, list[FieldMatch]] = field(default_factory=dict)
    chunks: list[ChunkRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "document": self.document,
            "retrieval": self.retrieval,
            "fields": {k: [m.to_dict() for m in v] for k, v in self.fields.items()},
            "chunks": [c.to_dict() for c in self.chunks],
        }

    @staticmethod
    def from_dict(d: dict) -> "RetrievalBundle":
        return RetrievalBundle(
            schema_version=d.get("schema_version", "mindex.retrieval-bundle.v0.1"),
            document=d.get("document", {}),
            retrieval=d.get("retrieval", {}),
            fields={k: [FieldMatch.from_dict(m) for m in v] for k, v in d.get("fields", {}).items()},
            chunks=[ChunkRecord.from_dict(c) for c in d.get("chunks", [])],
        )

    def matched_chunk_ids(self) -> set[str]:
        """fields 어디에든 등장하는 chunk_id 집합 — chunks[] 는 이미 이 집합과 같아야
        정상이지만(팀원 README: chunk_referenced 만 chunks[] 에 담김), 방어적으로 계산."""
        ids: set[str] = set()
        for matches in self.fields.values():
            for m in matches:
                ids.add(m.chunk_id)
        return ids

    def document_id(self) -> str:
        return self.document.get("file_hash") or self.document.get("file_name") or "unknown-document"

    def language(self) -> str:
        return (self.document.get("language") or "ko").upper()


@dataclass
class ExtractionResult:
    """Contract extraction 파이프라인 전체(extractor->validator->normalizer->projector) 출력을 묶는다."""
    raw: dict            # Rich Extraction (evidence 위치 후처리까지 끝난 상태)
    validation: dict      # validator.validate() 리포트
    normalized: dict       # normalizer.normalize_contract() 출력
    compact: dict          # projector.project() 출력 (Compact DB Projection)
    chunks: list[dict]     # search index chunks and embeddings

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "validation": self.validation,
            "normalized": self.normalized,
            "compact": self.compact,
            "chunks": self.chunks,
        }

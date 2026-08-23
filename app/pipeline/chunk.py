"""조항 → 청크.

## 왜 조항 단위인가

이전 구현은 페이지 경계에서 청크를 잘랐다. `contract_chunk.page`가 정수
하나여서 한 청크가 여러 페이지에 걸칠 수 없었기 때문이다. 논리는 맞지만
**자르는 위치를 의미가 아니라 종이 크기가 정한다**는 문제가 있었다.

86건 실측:

    페이지를 걸치는 조항        172 / 1825 (9.4%)  — 문서 기준 80/86 (93%)
    그 경계가 문장 중간          130 / 172 (76%)
    그 중 권리허락 조항          34건

결과로 Evidence 정답 781건 중 55건(7%)이 두 청크에 걸쳐서 어떤 검색으로도
회수되지 않았다. 781건 Ground Truth 기준 Recall@5 비교:

    페이지 분할   85.3%
    조항 단위     97.6%     <- 이 구현
    문장경계 스냅  89.2%

그래서 조항을 통째로 한 청크로 두고, 페이지는 **범위**(`page_start`~`page_end`)로
기록한다. DB의 `page` 컬럼 분리는 협의 중이므로 단일값도 함께 실어 보낸다.

## 길이 처리

조항 단위로 두면 대부분 짧다(1825건 중 토큰 중앙 107, p95 230). 다만 극소수가
임베딩 모델 입력 한계(512토큰)를 넘으므로 그때만 나눈다.

토크나이저는 쓰지 않는다. `transformers`가 CI에 없기 때문이다(ML 의존성은
requirements-ml.txt로 분리했다). 대신 문자 종류별 계수로 추정한다 — 실제
토크나이저와 대조해 1809건 중 과소추정 8건, 최대 부족 1토큰이었다.
임계를 480으로 두면 실제 512 초과 조항을 하나도 놓치지 않는다(실측 확인).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.pipeline.segment import Clause, ClauseKind

#: 임베딩 모델 입력 한계(512)에서 여유를 둔 분할 임계.
MAX_TOKENS = 480

#: 이보다 짧은 청크는 검색 색인에서 제외한다.
#: V1 적용 후 이 기준에 걸리는 것은 86건 전체에서 23건이고 전부 별지 제목
#: (`별지 1 — 개별 이용허락 명세`)이다. 내용은 GRANT_ITEM 청크로 따로 있다.
#: 이런 조각을 색인에 넣으면 의미검색 상위를 차지해 정답을 밀어낸다.
MIN_INDEXABLE_CHARS = 60

#: 한중일 문자 — 토큰 밀도가 라틴 문자와 크게 다르다.
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")

#: 문장 끝. 분할이 불가피할 때 여기서 끊는다.
_SENTENCE_END = re.compile(r"[.。．!?！？]['\"”’)）]?\s*$")

# 실측 최소제곱 계수는 (0.74, 0.23)이었으나 그대로 쓰면 절반이 과소추정된다.
# 분할 판정은 과대추정이 안전하므로 상한 쪽 계수를 쓴다.
_TOK_PER_CJK = 1.0
_TOK_PER_OTHER = 0.35


def estimate_tokens(text: str) -> float:
    """토크나이저 없이 e5 토큰 수를 추정한다. 과대추정 쪽으로 치우쳐 있다."""
    cjk = len(_CJK.findall(text))
    return cjk * _TOK_PER_CJK + (len(text) - cjk) * _TOK_PER_OTHER


@dataclass
class Chunk:
    chunk_id: str
    chunk_index: int
    clause_no: str
    clause_title: str
    clause_kind: ClauseKind
    lang: str
    text: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    #: 색인 대상 여부. 별지 제목처럼 내용 없는 조각을 걸러낸다.
    indexable: bool = True
    #: Worker가 contract_chunk.embedding에 적재할 벡터. 임베딩 전에는 None.
    embedding: list[float] | None = None

    @property
    def page(self) -> int:
        """DB의 `page` 단일 컬럼 호환용. 범위 분리 협의가 끝나면 뺀다."""
        return self.page_start

    @property
    def spans_pages(self) -> bool:
        return self.page_start != self.page_end


def _line_offsets(clause: Clause) -> list[int]:
    """조항 안 각 줄의 전체 텍스트 기준 시작 offset."""
    offsets, cursor = [], clause.char_start
    for line, _page in clause.lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    return offsets


def _split_clause(
    clause: Clause, max_tokens: float
) -> list[tuple[list[tuple[str, int]], int]]:
    """긴 조항을 줄 단위로 나눈다. 반환은 (줄 묶음, 시작 줄 인덱스) 목록.

    줄 단위로 나누는 이유는 페이지 정보가 줄에 붙어 있어서다. 문자 단위로
    자르면 각 조각이 몇 페이지인지 다시 계산해야 하고, 그러다 문장 중간을
    끊으면 애초에 고치려던 문제로 돌아간다.

    끊을 자리는 문장이 끝나는 줄을 우선한다.
    """
    groups: list[tuple[list[tuple[str, int]], int]] = []
    buf: list[tuple[str, int]] = []
    buf_start = 0
    tokens = 0.0

    for i, (line, page) in enumerate(clause.lines):
        cost = estimate_tokens(line) + _TOK_PER_OTHER  # 줄바꿈 1자
        # 넘칠 때만 끊는다. 첫 줄 하나만으로 넘치면 어쩔 수 없이 그대로 둔다.
        if buf and tokens + cost > max_tokens:
            groups.append((buf, buf_start))
            buf, buf_start, tokens = [], i, 0.0
        buf.append((line, page))
        tokens += cost
        # 여유가 얼마 안 남았고 문장이 끝났으면 여기서 끊는 편이 낫다.
        if tokens > max_tokens * 0.7 and _SENTENCE_END.search(line):
            groups.append((buf, buf_start))
            buf, buf_start, tokens = [], i + 1, 0.0

    if buf:
        groups.append((buf, buf_start))
    return groups


def build_chunks(
    clauses: list[Clause],
    lang: str,
    doc_hash: str,
    *,
    max_tokens: float = MAX_TOKENS,
    min_indexable_chars: int = MIN_INDEXABLE_CHARS,
) -> list[Chunk]:
    """조항 목록 → 청크 목록. 조항 하나가 청크 하나가 되는 것이 기본이다."""
    chunks: list[Chunk] = []

    for clause in clauses:
        offsets = _line_offsets(clause)

        if estimate_tokens(clause.text) <= max_tokens:
            groups = [(clause.lines, 0)]
        else:
            groups = _split_clause(clause, max_tokens)

        for lines, start_i in groups:
            text = "\n".join(ln for ln, _ in lines)
            if not text.strip():
                continue
            idx = len(chunks)
            pages = [p for _, p in lines]
            chunks.append(
                Chunk(
                    # 내용에 대해 결정론적이고 문서 안에서 유일한 id.
                    # Task2가 추출값의 출처를 되짚고, 같은 청크가 여러 field에
                    # 걸릴 때 중복을 제거하는 조인 키다.
                    chunk_id=f"{doc_hash[:12]}-{idx:04d}",
                    chunk_index=idx,
                    clause_no=clause.clause_no,
                    clause_title=clause.title,
                    clause_kind=clause.kind,
                    lang=lang,
                    text=text,
                    page_start=min(pages),
                    page_end=max(pages),
                    char_start=offsets[start_i],
                    char_end=offsets[start_i] + len(text),
                    indexable=len(text.strip()) >= min_indexable_chars,
                )
            )

    return chunks


@dataclass
class ChunkStats:
    """진단용 — 청킹이 의도대로 됐는지 한눈에 본다."""

    total: int
    indexable: int
    spanning_pages: int
    over_limit: int
    split_clauses: int
    by_kind: dict[str, int] = field(default_factory=dict)


def chunk_stats(chunks: list[Chunk], clauses: list[Clause]) -> ChunkStats:
    by_kind: dict[str, int] = {}
    for c in chunks:
        by_kind[c.clause_kind.value] = by_kind.get(c.clause_kind.value, 0) + 1
    return ChunkStats(
        total=len(chunks),
        indexable=sum(1 for c in chunks if c.indexable),
        spanning_pages=sum(1 for c in chunks if c.spans_pages),
        over_limit=sum(1 for c in chunks if estimate_tokens(c.text) > MAX_TOKENS),
        split_clauses=len(chunks) - len(clauses),
        by_kind=by_kind,
    )

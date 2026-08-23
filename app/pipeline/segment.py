"""페이지 텍스트 → 조항 단위 분해.

조항은 페이지를 넘어가므로 페이지별로 나눠서 분해할 수 없다. 전체 텍스트를
이어붙여 분해하되, **각 줄이 몇 페이지에서 왔는지를 함께 들고 다닌다.**
그 정보로 chunk.py가 `page_start`/`page_end`를 만든다.

별지(Schedule)를 본문 조항과 동급으로 다루는 것이 핵심이다. T5·T6 템플릿은
권리 명세(작품·권리·지역·기간·독점성·금액)를 전부 별지에 넣고 본문에는
"별지 1에 정한다"만 쓴다. 별지가 직전 조항에 흡수되면 추출이 통째로 어긋난다.
실제로 CTR-KO-0015의 권리 명세가 제18조에 통째로 먹힌 적이 있다.

의존성은 표준 라이브러리뿐 — CI에서 그대로 돈다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

FRONT_MATTER = "__FRONT_MATTER__"
UNSEGMENTED = "__UNSEGMENTED__"


class ClauseKind(StrEnum):
    FRONT_MATTER = "FRONT_MATTER"
    ARTICLE = "ARTICLE"
    SCHEDULE = "SCHEDULE"
    GRANT_ITEM = "GRANT_ITEM"
    UNSEGMENTED = "UNSEGMENTED"


# 본문 조항 머리. 언어 판별에도 쓴다.
CLAUSE_PATTERNS = {
    "ko": re.compile(r"^\s*제\s*(\d+)\s*조\s*[(（]?\s*([^)）]*)[)）]?\s*$"),
    "ja": re.compile(r"^\s*第\s*(\d+)\s*条\s*[(（]?\s*([^)）]*)[)）]?\s*$"),
    "en": re.compile(
        r"^\s*(?:Article|Clause|Section)\s+(\d+)\s*[(（]?\s*([^)）]*)[)）]?\s*$"
    ),
}

# 별지 머리.
# 주의: 일본어는 `別紙1`처럼 공백 없이 붙는다. CJK 뒤에는 \b가 먹지 않으므로
# 단어 경계 대신 \s*를 명시해야 한다.
SCHEDULE_PATTERNS = {
    "ko": re.compile(r"^\s*(별지)\s*(\d+)\s*[—\-–:]?\s*(.*)$"),
    "ja": re.compile(r"^\s*(別紙)\s*(\d+)\s*[—\-–:]?\s*(.*)$"),
    "en": re.compile(
        r"^\s*(Schedule|Exhibit|Appendix|Annex)\s+(\d+)\s*[—\-–:]?\s*(.*)$"
    ),
}

# 별지 안에서 개별 권리부여를 나누는 머리.
GRANT_ITEM_PATTERNS = {
    "ko": re.compile(r"^\s*(개별\s*이용허락)\s*(\d+)\s*$"),
    "ja": re.compile(r"^\s*(個別(?:利用)?許諾)\s*(\d+)\s*$"),
    "en": re.compile(
        r"^\s*(Individual\s+Lic[e|s]nce|Individual\s+License|Grant)\s+(\d+)\s*$"
    ),
}

# 머리말/꼬리말 — 조항 텍스트에서 제거한다.
NOISE_PATTERNS = [
    re.compile(r"NOT FOR EXECUTION", re.I),
    re.compile(r"^\s*\|?\s*\d+\s*/\s*\d+\s*$"),
]


@dataclass
class Clause:
    clause_no: str
    kind: ClauseKind
    title: str
    text: str
    char_start: int
    char_end: int
    #: (줄 텍스트, 페이지 번호). 청킹이 페이지 범위를 계산하는 근거.
    lines: list[tuple[str, int]]

    @property
    def page_start(self) -> int:
        return self.lines[0][1]

    @property
    def page_end(self) -> int:
        return self.lines[-1][1]

    @property
    def pages(self) -> list[int]:
        return sorted({p for _, p in self.lines})

    @property
    def spans_pages(self) -> bool:
        return self.page_start != self.page_end


def strip_noise(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    return None if any(p.search(stripped) for p in NOISE_PATTERNS) else line


def detect_language(lines: list[str]) -> str:
    """조항 머리 패턴이 가장 많이 맞는 언어. 하나도 안 맞으면 unknown."""
    hits = {
        lang: sum(1 for ln in lines if pat.match(ln))
        for lang, pat in CLAUSE_PATTERNS.items()
    }
    best = max(hits, key=lambda k: hits[k])
    return best if hits[best] else "unknown"


def _collect_heads(
    numbered: list[tuple[str, int]], lang: str
) -> list[tuple[int, ClauseKind, str, str]]:
    """분해 지점 수집 — (줄 인덱스, 종류, 라벨, 제목)."""
    article = CLAUSE_PATTERNS.get(lang)
    schedule = SCHEDULE_PATTERNS.get(lang)
    item = GRANT_ITEM_PATTERNS.get(lang)
    heads = []
    for i, (line, _page) in enumerate(numbered):
        if article and (m := article.match(line)):
            label = {"ko": f"제{m.group(1)}조", "ja": f"第{m.group(1)}条"}.get(
                lang, f"Article {m.group(1)}"
            )
            heads.append((i, ClauseKind.ARTICLE, label, (m.group(2) or "").strip()))
        elif schedule and (m := schedule.match(line)):
            heads.append(
                (
                    i,
                    ClauseKind.SCHEDULE,
                    f"{m.group(1)} {m.group(2)}",
                    (m.group(3) or "").strip(),
                )
            )
        elif item and (m := item.match(line)):
            heads.append((i, ClauseKind.GRANT_ITEM, f"{m.group(1)} {m.group(2)}", ""))
    return heads


def segment(pages, lang: str | None = None) -> tuple[str, str, list[Clause]]:
    """페이지들 → (언어, 전체 텍스트, 조항 목록).

    `pages`는 `.text`와 `.page`를 가진 객체면 된다(extract.Page 또는 OCR 결과).
    반환하는 `char_start`/`char_end`는 **전체 텍스트 기준** offset이며,
    Evidence Anchoring의 기준선이 된다.
    """
    numbered: list[tuple[str, int]] = []
    for pg in pages:
        for raw in pg.text.split("\n"):
            if (line := strip_noise(raw)) is not None:
                numbered.append((line, pg.page))

    if lang is None:
        lang = detect_language([ln for ln, _ in numbered])

    full_text = "\n".join(ln for ln, _ in numbered)

    # 각 줄의 시작 offset (줄바꿈 1자 포함)
    offsets, cursor = [], 0
    for line, _ in numbered:
        offsets.append(cursor)
        cursor += len(line) + 1

    clauses: list[Clause] = []

    def add(
        clause_no: str, title: str, start_i: int, end_i: int, kind: ClauseKind
    ) -> None:
        if start_i >= end_i:
            return
        seg = numbered[start_i:end_i]
        body = "\n".join(ln for ln, _ in seg)
        if not body.strip():
            return
        clauses.append(
            Clause(
                clause_no=clause_no,
                kind=kind,
                title=title,
                text=body,
                char_start=offsets[start_i],
                char_end=offsets[end_i - 1] + len(seg[-1][0]),
                lines=list(seg),
            )
        )

    heads = _collect_heads(numbered, lang)
    if heads:
        add(FRONT_MATTER, "표제·당사자·전문", 0, heads[0][0], ClauseKind.FRONT_MATTER)
        for n, (i, kind, label, title) in enumerate(heads):
            end = heads[n + 1][0] if n + 1 < len(heads) else len(numbered)
            add(label, title, i, end, kind)
    else:
        # 조항 머리를 하나도 못 찾은 경우. 통째로 한 덩어리로 두고 뒤에서 처리한다.
        add(UNSEGMENTED, "", 0, len(numbered), ClauseKind.UNSEGMENTED)

    return lang, full_text, clauses

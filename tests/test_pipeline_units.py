"""파이프라인 순수 함수 단위 테스트.

torch·pdfplumber 없이 도는 부분만 다룬다. ML 의존성은 requirements-ml.txt로
분리돼 있어 CI에는 없다.
"""

from __future__ import annotations

import pytest

from app.pipeline.chunk import MAX_TOKENS, build_chunks, estimate_tokens
from app.pipeline.normalize import count_cjk_compatibility, normalize_text
from app.pipeline.route import PageSignals, TextSource, route
from app.pipeline.segment import Clause, ClauseKind, detect_language, segment, strip_noise


# ── normalize ────────────────────────────────────────────────────────────
def test_cjk_호환한자를_정규형으로_바꾼다():
    """JP PDF가 利(U+5229) 대신 U+F9DD를 내보낸다. 실측 28건 전부에서 발생."""
    compat = "利"  # CJK COMPATIBILITY IDEOGRAPH-F9DD
    assert count_cjk_compatibility(compat) == 1
    assert normalize_text(compat) == "利"
    assert count_cjk_compatibility(normalize_text(compat)) == 0


def test_정규화가_길이를_보존한다():
    """offset 기반 Evidence Anchoring이 성립하려면 길이가 보존돼야 한다."""
    text = "利用許諾契約書 第1条 (目的)"
    assert len(normalize_text(text)) == len(text)


def test_소프트하이픈_줄끝은_지우고_문장내부는_하이픈으로():
    # 줄끝 하이프네이션 -> 소프트하이픈만 제거, 줄바꿈은 유지
    assert normalize_text("agree­\nment") == "agree\nment"
    # 문장 내부 -> 눈에 보이는 하이픈이므로 일반 하이픈으로
    assert normalize_text("2026­01­01") == "2026-01-01"


# ── route ────────────────────────────────────────────────────────────────
def _sig(**kw) -> PageSignals:
    base = dict(
        char_count=2000, chars_per_kpx=2.3, image_coverage=0.0, image_count=0, bad_char_count=0
    )
    return PageSignals(**{**base, **kw})


def test_정상_디지털페이지는_텍스트레이어():
    assert route(_sig()) is TextSource.TEXT_LAYER


def test_문자밀도가_낮으면_ocr():
    """래스터화한 스캔본 실측 밀도는 0.000이었다."""
    assert route(_sig(char_count=0, chars_per_kpx=0.0)) is TextSource.OCR


def test_밀도_0_152는_정상으로_남는다():
    """정상 페이지 최소 실측값(JP). 임계 0.30이면 오탐 27건이 났었다."""
    assert route(_sig(char_count=300, chars_per_kpx=0.152)) is TextSource.TEXT_LAYER


def test_이미지가_덮고_텍스트가_빈약하면_ocr():
    assert route(_sig(chars_per_kpx=0.4, image_coverage=0.95)) is TextSource.OCR


def test_깨진문자가_있으면_교차검증():
    assert route(_sig(bad_char_count=3)) is TextSource.VERIFY


# ── segment ──────────────────────────────────────────────────────────────
class _Page:
    def __init__(self, page: int, text: str):
        self.page, self.text = page, text


KO_DOC = """계약서
제1조 (목적)
본 계약은 목적을 정한다.
제3조 (이용허락)
개별 권리는 별지 1에 정한다.
별지 1 — 개별 이용허락 명세
개별 이용허락 1
이용지역은 대한민국으로 한다.
"""


def test_한국어_조항_별지_개별허락을_모두_분해한다():
    lang, _full, clauses = segment([_Page(1, KO_DOC)])
    assert lang == "ko"
    kinds = [c.kind for c in clauses]
    assert ClauseKind.FRONT_MATTER in kinds
    assert ClauseKind.SCHEDULE in kinds
    assert ClauseKind.GRANT_ITEM in kinds
    assert [c.clause_no for c in clauses if c.kind is ClauseKind.ARTICLE] == ["제1조", "제3조"]


def test_별지가_직전_조항에_흡수되지_않는다():
    """CTR-KO-0015의 권리 명세가 제18조에 통째로 먹힌 회귀."""
    _lang, _full, clauses = segment([_Page(1, KO_DOC)])
    sched = next(c for c in clauses if c.kind is ClauseKind.SCHEDULE)
    assert "이용지역" not in next(c for c in clauses if c.clause_no == "제3조").text
    assert sched.clause_no == "별지 1"


def test_일본어_별지는_공백없이_붙는다():
    """`別紙1` — CJK 뒤에는 \\b가 먹지 않아 예전에 못 잡았다."""
    doc = "第1条 (目的)\n本契約は目的を定める。\n別紙1 — 個別利用許諾明細\n利用地域は日本とする。"
    lang, _full, clauses = segment([_Page(1, doc)])
    assert lang == "ja"
    assert any(c.kind is ClauseKind.SCHEDULE for c in clauses)


def test_offset이_전체텍스트를_가리킨다():
    _lang, full, clauses = segment([_Page(1, KO_DOC)])
    for c in clauses:
        assert full[c.char_start : c.char_end] == c.text


def test_페이지를_넘는_조항은_시작과_끝_페이지를_모두_안다():
    pages = [_Page(1, "제1조 (목적)\n앞부분"), _Page(2, "뒷부분")]
    _lang, _full, clauses = segment(pages, lang="ko")
    art = next(c for c in clauses if c.clause_no == "제1조")
    assert (art.page_start, art.page_end) == (1, 2)
    assert art.spans_pages


def test_노이즈_제거():
    assert strip_noise("  NOT FOR EXECUTION  ") is None
    assert strip_noise("3 / 8") is None
    assert strip_noise("제1조 (목적)") == "제1조 (목적)"


def test_조항머리가_없으면_unknown():
    assert detect_language(["그냥 문장입니다."]) == "unknown"


# ── chunk ────────────────────────────────────────────────────────────────
def _clause(text: str, pages: list[int], kind=ClauseKind.ARTICLE) -> Clause:
    lines = list(zip(text.split("\n"), pages, strict=True))
    return Clause(
        clause_no="제1조",
        kind=kind,
        title="목적",
        text=text,
        char_start=0,
        char_end=len(text),
        lines=lines,
    )


def test_조항이_페이지를_넘어도_하나의_청크로_남는다():
    """핵심 회귀. 예전에는 페이지 경계에서 잘려 27자 조각이 생겼다."""
    clause = _clause("제12조 (계약기간)\n갱신은 별도 서면\n합의에 의한다.", [2, 2, 3])
    chunks = build_chunks([clause], "ko", "abc123def456")
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (2, 3)
    assert "합의에 의한다." in chunks[0].text


def test_토큰_추정은_과대추정_쪽이다():
    """분할 판정에서 과소추정은 조용한 잘림을 부른다."""
    assert estimate_tokens("가나다") == pytest.approx(3.0)
    assert estimate_tokens("abcd") == pytest.approx(1.4)


def test_한계를_넘는_조항만_나뉜다():
    short = _clause("제1조 (목적)\n짧다.", [1, 1])
    assert len(build_chunks([short], "ko", "h" * 12)) == 1

    long_lines = ["제2조 (긴조항)"] + ["가" * 100 for _ in range(8)]
    long = _clause("\n".join(long_lines), [1] * len(long_lines))
    chunks = build_chunks([long], "ko", "h" * 12)
    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= MAX_TOKENS for c in chunks)


def test_별지_제목만_있는_청크는_색인에서_빠진다():
    """86건에서 23건 발생. 전부 별지 제목이고 내용은 GRANT_ITEM에 따로 있다."""
    heading = _clause("별지 1 — 개별 이용허락 명세", [5], kind=ClauseKind.SCHEDULE)
    chunk = build_chunks([heading], "ko", "h" * 12)[0]
    assert chunk.indexable is False


def test_chunk_id는_같은_입력에_같은_값():
    clause = _clause("제1조 (목적)\n" + "본문이 충분히 길어야 색인 대상이 된다. " * 3, [1, 1])
    a = build_chunks([clause], "ko", "deadbeef0000")
    b = build_chunks([clause], "ko", "deadbeef0000")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert a[0].chunk_id.startswith("deadbeef0000-")

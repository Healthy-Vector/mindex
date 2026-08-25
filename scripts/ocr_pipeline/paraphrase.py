"""평가용 표현 치환 — held-out 집합을 만든다 (Phase 4).

## 왜 필요한가

어휘 점수식의 패턴을 합성데이터를 보면서 썼다. 그래서 같은 데이터로 채점하면
정답 청크의 70%가 어휘 0.7 이상을 받고, 어휘가 실패하는 경우가 556건 중
**1건**뿐이다. 의미검색이 기여할 여지 자체가 없어서 **hybrid 가중치를 정할 수
없다.**

실제 계약서는 회사마다 표현이 다르다. `이용지역은`이라고 쓰는 곳도 있고
`서비스 대상 권역은`이라고 쓰는 곳도 있다. 그 상황을 흉내내서, 어휘가
흔들릴 때 의미검색이 얼마나 메우는지를 잰다.

## 무엇을 바꾸고 무엇을 남기나

**바꾸는 것 — 라벨 표현.** `이용지역`·`이용기간`·`계약대가`처럼 회사마다 다르게
쓰는 항목 이름. 어휘 패턴이 이것들에 매달려 있다.

**남기는 것 — 내용어.** 날짜·국가명·금액·SVOD 같은 업계 표준 약어.
이것들까지 바꾸면 문서의 의미 자체가 훼손돼서, 의미검색도 못 찾는 게 당연해진다.
그러면 실험이 아무것도 말해주지 않는다.

## 정답에도 똑같이 적용한다

청크만 바꾸고 정답을 그대로 두면 문자열 대조가 깨져서 전부 실패로 잡힌다.
청크와 정답에 같은 치환을 적용해야 회수 문제의 난이도만 달라진다.
"""

from __future__ import annotations

import re

#: 라벨 표현 → 같은 뜻의 다른 표현.
#:
#: 긴 것부터 적용해야 `이용지역은`이 `이용지역` 규칙에 먼저 걸린다.
#: `지역은` 규칙이 먼저 돌면 `이용권역은`이라는 어색한 말이 남는다.
PARAPHRASES: dict[str, str] = {
    # ── territory ──────────────────────────────────────────────
    "이용지역": "서비스 대상 권역",
    "이용 지역": "서비스 대상 권역",
    "지역은": "권역은",
    "許諾地域": "配信対象エリア",
    "利用地域": "配信対象エリア",
    "地域は": "エリアは",
    "shall be limited to the territory": "shall be limited to the distribution area",
    "Territory": "Distribution Area",
    "territory": "distribution area",
    # ── rights_type ────────────────────────────────────────────
    "이용방식": "서비스 형태",
    "利用方法": "サービス形態",
    "exploitation": "commercial use",
    "Exploitation": "Commercial use",
    "licensed use": "permitted use",
    "licenced use": "permitted use",
    # ── period ─────────────────────────────────────────────────
    "이용기간": "서비스 제공 기간",
    "利用期間": "サービス提供期間",
    "License Period": "Availability Window",
    "Licence Period": "Availability Window",
    "license period": "availability window",
    "licence period": "availability window",
    # ── exclusivity ────────────────────────────────────────────
    "독점적으로 허락": "배타적으로 부여",
    "비독점적으로 허락": "비배타적으로 부여",
    "독점성은": "배타성은",
    "비독점": "비배타",
    "독점": "배타",
    "独占的に許諾": "排他的に付与",
    "非独占的": "非排他的",
    "独占性は": "排他性は",
    "独占": "排他",
    "Exclusivity": "Rights Basis",
    "exclusivity": "rights basis",
    # ── payment ────────────────────────────────────────────────
    "총 계약대가": "총 라이선스료",
    "계약대가": "라이선스료",
    "契約対価": "ライセンス料",
    "지급통화": "결제 통화",
    "支払通貨": "決済通貨",
    "payment currency": "settlement currency",
    "License Fee": "Royalty",
    "Licence Fee": "Royalty",
    "total consideration": "aggregate amount",
    "지급한다": "송금한다",
    "支払う": "送金する",
    "shall pay": "shall remit",
}

def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


# 글자 사이 어디에나 공백이 낄 수 있게 만든다.
#
# PDF 는 줄이 꽉 차면 아무 데서나 끊는다. 영문은 `the License\nPeriod is` 처럼
# 단어 사이가 갈리고, **CJK 는 공백이 없어서 단어 한가운데가 갈린다** —
# 실제로 `利用\n方法` 이 나온다. 리터럴로 찾으면 정답지(canonical Markdown,
# 한 줄)에만 걸리고 PDF 추출문에는 안 걸려서, 양쪽에 다른 치환이 적용되고
# 문자열 대조가 통째로 깨진다.
#
# 평가 전용 도구라 과하게 관대한 매칭의 위험(`단독\n점유` 를 `독점` 으로 오인)은
# 감수한다. 잘못 걸려도 held-out 집합의 문장이 조금 달라질 뿐이다.
_LOOKUP = {_squash(k): v for k, v in PARAPHRASES.items()}
_PATTERN = re.compile(
    "|".join(
        r"\s*".join(re.escape(ch) for ch in k)
        for k in sorted(_LOOKUP, key=len, reverse=True)
    )
)


def paraphrase(text: str) -> str:
    """라벨 표현을 같은 뜻의 다른 표현으로 바꾼다."""
    return _PATTERN.sub(lambda m: _LOOKUP[_squash(m.group(0))], text)


def count_hits(text: str) -> int:
    """몇 군데가 바뀌는지. 치환이 실제로 먹었는지 확인용."""
    return len(_PATTERN.findall(text))

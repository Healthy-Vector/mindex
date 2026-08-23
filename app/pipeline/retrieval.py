"""필드별 청크 회수 — Task2(LLM 추출·정규화)가 받는 최종 형태.

## 왜 어휘 점수를 먼저 두는가

의미검색만으로는 안 된다. 실측(2000청크)에서 e5 코사인이 좁은 구간에 눌려 있다.

    청크 간 코사인:  min 0.681  중앙 0.778  p95 0.855

폭이 0.17뿐이라 (1) 절대 임계값을 쓸 수 없고 (2) argmax가 내용이 아니라 잡음으로
정해진다. 실제로 27자 조각 하나가 territory·exclusivity·payment·parties
네 필드에서 동시에 1위를 한 사례가 있었다. 516개(86문서×6필드) 기준 1위 오염률은
**의미 23.6% vs 어휘 0.4%** 였다.

여기에 더해 **DISTRACTOR는 부정 신호로만 걷힌다.** 제18조(준거법)의 "대한민국
법률에 따라 해석한다"는 territory가 아닌데, 순수 의미유사도로는 구분이 어렵다.
명시적 감점이 효과적이다.

의미 점수는 조합용으로 두고, 가중치는 Ground Truth로 측정해서 정한다.

## 필드 이름에 대한 경고

`rights_type`은 회수 질의 이름으로만 쓴다. **추출 결과 필드로 굳으면 안 된다.**
ERD v3에서 이 축은 `legal_right`(저작재산권의 지분권)와 `exploitation_mode`
(이용형태)로 분리돼 있고, 프로젝트가 두 축을 절대 합치지 않는다고 못박았다.
합치면 R3(권리 위계)·R4(이용형태) 판정이 불가능해진다.
Ground Truth도 `LEGAL_RIGHT`/`EXPLOITATION_MODE`로 이미 나뉘어 있다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

LEXICAL_SCORER = "lexical-v0"

#: 필드별 의미검색 질의. 다국어 모델이라 세 언어를 한 문자열에 섞어 둔다.
FIELD_QUERIES: dict[str, str] = {
    "territory": "이용 허락 지역 licensed territory 許諾地域",
    "rights_type": "허락된 이용 방식과 권리 종류 licensed rights exploitation mode 利用方法",
    "period": "이용 허락 기간 시작일 종료일 licence period 利用期間",
    "exclusivity": "독점 여부 exclusive or non-exclusive 独占",
    "payment": "계약 대가 지급 조건 licence fee payment 対価",
    "parties": "계약 당사자 licensor licensee 契約当事者",
}

# positive : 있으면 가점 (패턴, 가중치)
# negative : 있으면 감점 — DISTRACTOR 제거용
# kind_prior : 조항 종류별 사전 가중
FIELD_SPECS: dict[str, dict] = {
    "territory": {
        "positive": [
            (r"이용지역|이용 지역|許諾地域|利用地域|Territory|territor", 3.0),
            (r"지역은|地域は|shall be limited to the territory", 2.0),
            (
                r"대한민국|일본|미국|台湾|シンガポール|Korea|Japan|United States|Taiwan",
                1.0,
            ),
            (r"WORLDWIDE|전세계|全世界|ASIA|APAC", 1.5),
        ],
        "negative": [
            # 준거법·관할법원의 국가명은 이용지역이 아니다
            (
                r"준거법|법률에 따라 해석|관할법원|準拠法|管轄裁判所|Governing Law|jurisdiction",
                4.0,
            ),
            (r"주소|본점|所在地|address", 1.5),
        ],
        "kind_prior": {
            "GRANT_ITEM": 2.0,
            "SCHEDULE": 1.5,
            "ARTICLE": 1.0,
            "FRONT_MATTER": 0.3,
        },
    },
    "rights_type": {
        "positive": [
            (r"전송권|복제권|배포권|공중송신권|公衆送信権|複製権|頒布権", 3.0),
            (r"SVOD|AVOD|TVOD|주문형|見放題|配信|streaming|video on demand", 2.5),
            (r"이용방식|利用方法|exploitation|licen[cs]ed use", 2.0),
            (r"방송|放送|broadcast|극장|劇場|theatrical", 1.5),
        ],
        "negative": [
            (r"정의조항은|定義は|definitions? (?:shall|do) not", 2.0),
            (r"유보된다|留保|reserved to the licensor", 1.0),
        ],
        "kind_prior": {
            "GRANT_ITEM": 2.0,
            "SCHEDULE": 1.3,
            "ARTICLE": 1.0,
            "FRONT_MATTER": 0.3,
        },
    },
    "period": {
        "positive": [
            (r"이용기간|利用期間|Licen[cs]e Period|licence period", 3.0),
            # 실제 날짜가 적혀 있으면 그 조항이 기간의 출처일 가능성이 높다.
            # PDF가 문장 중간에 줄바꿈을 넣으므로 숫자와 단위 사이에 \s* 를 둔다.
            (r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", 3.0),
            (r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", 3.0),
            (r"\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s*\d{4}", 2.5),
            (r"\d{4}[-/]\d{2}[-/]\d{2}", 2.0),
            (r"부터.{0,25}까지|から.{0,25}まで|from .{0,40} (?:to|until|through)", 2.0),
        ],
        "negative": [
            # 계약기간은 이용기간이 아니다 — 프로젝트가 명시적으로 금지한 혼동
            (
                r"계약기간은|계약의 존속기간|契約期間|(?:Term of (?:this )?Agreement|Agreement Term)",
                3.5,
            ),
            (r"보관한다|3년간|retention", 1.5),
        ],
        "kind_prior": {
            "GRANT_ITEM": 2.0,
            "SCHEDULE": 1.3,
            "ARTICLE": 1.0,
            "FRONT_MATTER": 0.3,
        },
    },
    "exclusivity": {
        "positive": [
            (r"독점적으로 허락|비독점적으로 허락|独占的に許諾|非独占的", 3.5),
            (r"독점성은|独占性は|exclusivity", 3.0),
            (r"독점|비독점|exclusive|non-exclusive|sole", 2.0),
        ],
        "negative": [
            (r"전속관할|専属的合意管轄|exclusive jurisdiction", 4.0),
        ],
        "kind_prior": {
            "GRANT_ITEM": 2.0,
            "SCHEDULE": 1.3,
            "ARTICLE": 1.0,
            "FRONT_MATTER": 0.3,
        },
    },
    "payment": {
        "positive": [
            (r"계약대가|契約対価|총 계약대가|Licen[cs]e Fee|total consideration", 3.5),
            (r"지급통화|支払通貨|payment currency", 3.0),
            (r"[\d,]{4,}(?:\.\d{2})?\s*(?:KRW|USD|JPY|원|円)", 3.0),
            (r"지급한다|支払う|shall pay", 1.5),
            (r"영업일 이내|営業日以内|business days", 1.0),
        ],
        "negative": [
            (r"비밀|秘密|confidential", 2.5),
            (r"준거법|準拠法|governing law", 2.5),
            (r"불가항력|不可抗力|force majeure", 2.5),
        ],
        "kind_prior": {
            "SCHEDULE": 2.0,
            "GRANT_ITEM": 1.3,
            "ARTICLE": 1.0,
            "FRONT_MATTER": 0.5,
        },
    },
    "parties": {
        "positive": [
            (r"계약 당사자|契約当事者|Part(?:y|ies)", 3.0),
            (r"허락자|이용자|許諾者|利用者|Licensor|Licensee", 2.5),
            (r"대표자|代表者|representative", 2.0),
            (r"주식회사|株式会社|Co\.,? Ltd|Inc\.|LLC", 1.5),
            (r"법인등록번호|法人登録番号|registration number", 2.0),
        ],
        "negative": [
            (r"통지는|通知は|notices? shall be", 2.0),
            (r"양도|譲渡|assignment", 1.5),
        ],
        "kind_prior": {
            "FRONT_MATTER": 2.5,
            "GRANT_ITEM": 1.0,
            "SCHEDULE": 1.0,
            "ARTICLE": 0.6,
        },
    },
}

# 정규식은 매번 컴파일하지 않는다. 2000청크 × 6필드 × 패턴 수만큼 돈다.
_COMPILED = {
    field_name: {
        "positive": [(re.compile(p, re.I | re.S), w) for p, w in spec["positive"]],
        "negative": [(re.compile(p, re.I | re.S), w) for p, w in spec["negative"]],
        "kind_prior": spec["kind_prior"],
        # 근거 표시용 원본 패턴
        "labels": {p: p.split("|")[0] for p, _ in spec["positive"] + spec["negative"]},
    }
    for field_name, spec in FIELD_SPECS.items()
}


@dataclass
class Hit:
    chunk_id: str
    score: float
    lexical: float
    semantic: float | None
    reasons: list[str] = field(default_factory=list)


def score_lexical(text: str, kind: str, field_name: str) -> tuple[float, list[str]]:
    """청크 하나가 한 필드에 얼마나 관련 있는지. (0~1 점수, 매칭 근거)

    양성 신호가 하나도 없으면 즉시 0을 준다. 조항 종류 가중(`kind_prior`)만으로
    점수가 붙으면 아무 관련 없는 청크가 상위를 채운다 — 실제로 0.209짜리 잡음이
    top-k를 메운 적이 있다.
    """
    spec = _COMPILED[field_name]
    positive = 0.0
    penalty = 0.0
    reasons: list[str] = []

    for pat, weight in spec["positive"]:
        hits = len(pat.findall(text))
        if hits:
            # 같은 신호가 반복돼도 이득을 체감시킨다
            positive += weight * (1 + math.log(hits)) if hits > 1 else weight
            reasons.append("+" + spec["labels"][pat.pattern])

    if positive <= 0:
        return 0.0, []

    for pat, weight in spec["negative"]:
        if pat.search(text):
            penalty += weight
            reasons.append("-" + spec["labels"][pat.pattern])

    raw = (positive - penalty) * spec["kind_prior"].get(kind, 1.0)
    # 0~1로 눌러 담는다. 12점 근처에서 포화한다.
    return round(1 / (1 + math.exp(-(raw - 4) / 3)), 4), reasons


def retrieve(
    chunks,
    *,
    top_k: int = 5,
    min_score: float = 0.15,
    semantic_weight: float = 0.0,
    query_vectors: dict[str, list[float]] | None = None,
) -> dict[str, list[Hit]]:
    """필드별로 관련 청크를 점수순으로 묶는다.

    `semantic_weight`가 0이면 순수 어휘 회수다(기본값). 0보다 크면 `query_vectors`와
    청크 임베딩의 코사인을 가중 합산한다. 가중치는 Ground Truth로 측정해서 정한다.

    색인 제외 청크(별지 제목 등)는 후보에서 빠진다.
    """
    pool = [c for c in chunks if c.indexable]
    out: dict[str, list[Hit]] = {}

    for field_name in FIELD_SPECS:
        qv = (query_vectors or {}).get(field_name)
        use_semantic = semantic_weight > 0 and qv is not None

        scored: list[Hit] = []
        for c in pool:
            lex, reasons = score_lexical(c.text, str(c.clause_kind), field_name)
            sem = None
            if use_semantic and c.embedding is not None:
                # 양쪽 다 L2 정규화돼 있으므로 내적이 곧 코사인이다
                sem = sum(a * b for a, b in zip(c.embedding, qv, strict=True))
            total = (
                lex
                if sem is None
                else (1 - semantic_weight) * lex + semantic_weight * sem
            )
            if total >= min_score:
                scored.append(
                    Hit(
                        chunk_id=c.chunk_id,
                        score=round(total, 4),
                        lexical=lex,
                        semantic=round(sem, 4) if sem is not None else None,
                        reasons=reasons,
                    )
                )

        scored.sort(key=lambda h: -h.score)
        out[field_name] = scored[:top_k]

    return out

"""파싱 결과(*.parse.json) → RetrievalBundle 생성.

Task2(LLM 추출·정규화)가 받는 최종 형태다. 필드별로 관련 청크를 점수와 함께 묶어 준다.

    python scripts/build_retrieval_bundle.py docs/handoff/samples/*.parse.json -o <폴더>

## 점수 산정에 대하여

지금은 **어휘 기반 baseline(`lexical-v0`)**이다. 임베딩 모델을 붙이면
`semantic-e5-v1`으로 교체하고 두 점수를 합치는 hybrid로 간다.
어휘 baseline을 먼저 두는 이유는 두 가지다.

1. 계약서의 핵심 필드는 정형 표현이 강해서(`이용지역은`, `독점적으로 허락한다`)
   어휘 신호만으로도 상당히 잡힌다.
2. **DISTRACTOR를 걷어내려면 부정 신호가 필요하다.** 예를 들어 제18조(준거법)의
   "대한민국 법률에 따라 해석한다"는 territory가 아니다. 순수 의미유사도만으로는
   이걸 걸러내기 어렵고, 명시적 감점이 효과적이다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "mindex.retrieval-bundle.v0.1"
SCORER = "lexical-v0"

# Task2가 요청한 retrieval 대상 field 6종.
#   positive : 있으면 가점 (패턴, 가중치)
#   negative : 있으면 감점 — DISTRACTOR 제거용
#   kind_prior : 조항 종류별 사전 가중
FIELD_SPECS: dict[str, dict] = {
    "territory": {
        "positive": [
            (r"이용지역|이용 지역|許諾地域|利用地域|Territory|territor", 3.0),
            (r"지역은|地域は|shall be limited to the territory", 2.0),
            (r"대한민국|일본|미국|台湾|シンガポール|Korea|Japan|United States|Taiwan", 1.0),
            (r"WORLDWIDE|전세계|全世界|ASIA|APAC", 1.5),
        ],
        "negative": [
            # 준거법·관할법원의 국가명은 이용지역이 아니다
            (r"준거법|법률에 따라 해석|관할법원|準拠法|管轄裁判所|Governing Law|jurisdiction", 4.0),
            (r"주소|본점|所在地|address", 1.5),
        ],
        "kind_prior": {"GRANT_ITEM": 2.0, "SCHEDULE": 1.5, "ARTICLE": 1.0, "FRONT_MATTER": 0.3},
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
        "kind_prior": {"GRANT_ITEM": 2.0, "SCHEDULE": 1.3, "ARTICLE": 1.0, "FRONT_MATTER": 0.3},
    },
    "period": {
        "positive": [
            (r"이용기간|利用期間|Licen[cs]e Period|licence period", 3.0),
            # 실제 날짜가 적혀 있으면 그 조항이 기간의 출처일 가능성이 높다.
            # 언어별 표기를 모두 잡는다. PDF가 문장 중간에 줄바꿈을 넣으므로
            # 숫자와 단위 사이에 \s* 를 둔다.
            (r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", 3.0),
            (r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", 3.0),
            (r"\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s*\d{4}", 2.5),
            (r"\d{4}[-/]\d{2}[-/]\d{2}", 2.0),
            (r"부터.{0,25}까지|から.{0,25}まで|from .{0,40} (?:to|until|through)", 2.0),
        ],
        "negative": [
            # 계약기간은 이용기간이 아니다 — 프로젝트가 명시적으로 금지한 혼동
            (r"계약기간은|계약의 존속기간|契約期間|(?:Term of (?:this )?Agreement|Agreement Term)", 3.5),
            (r"보관한다|3년간|retention", 1.5),
        ],
        "kind_prior": {"GRANT_ITEM": 2.0, "SCHEDULE": 1.3, "ARTICLE": 1.0, "FRONT_MATTER": 0.3},
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
        "kind_prior": {"GRANT_ITEM": 2.0, "SCHEDULE": 1.3, "ARTICLE": 1.0, "FRONT_MATTER": 0.3},
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
        "kind_prior": {"SCHEDULE": 2.0, "GRANT_ITEM": 1.3, "ARTICLE": 1.0, "FRONT_MATTER": 0.5},
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
        "kind_prior": {"FRONT_MATTER": 2.5, "GRANT_ITEM": 1.0, "SCHEDULE": 1.0, "ARTICLE": 0.6},
    },
}


def score_chunk(text: str, kind: str, spec: dict) -> tuple[float, list[str]]:
    """청크 하나가 한 field에 얼마나 관련 있는지. (점수, 매칭근거)

    양성 신호가 하나도 없으면 0을 준다. 조항 종류 가중만으로 점수가 붙으면
    아무 관련 없는 청크가 상위 k를 채운다.
    """
    positive = 0.0
    penalty = 0.0
    reasons: list[str] = []

    for pattern, weight in spec["positive"]:
        hits = len(re.findall(pattern, text, re.I | re.S))
        if hits:
            # 반복 등장의 이득을 체감시킨다
            positive += weight * (1 + math.log(hits)) if hits > 1 else weight
            reasons.append(f"+{pattern.split('|')[0]}")

    if positive <= 0:
        return 0.0, []

    for pattern, weight in spec["negative"]:
        if re.search(pattern, text, re.I | re.S):
            penalty += weight
            reasons.append(f"-{pattern.split('|')[0]}")

    raw = (positive - penalty) * spec["kind_prior"].get(kind, 1.0)
    # 0~1로 눌러 담는다. 12점 근처에서 포화한다.
    return round(1 / (1 + math.exp(-(raw - 4) / 3)), 4), reasons


def build_bundle(parse: dict, top_k: int, min_score: float) -> dict:
    chunks = parse["chunks"]
    doc = parse["document"]

    fields: dict[str, list[dict]] = {}
    used_ids: set[str] = set()

    for field, spec in FIELD_SPECS.items():
        scored = []
        for chunk in chunks:
            score, reasons = score_chunk(chunk["chunk_text"], chunk["clause_kind"], spec)
            if score >= min_score:
                scored.append((score, reasons, chunk))
        scored.sort(key=lambda x: -x[0])

        hits = []
        for score, reasons, chunk in scored[:top_k]:
            used_ids.add(chunk["chunk_id"])
            hits.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "text": chunk["chunk_text"],
                    "page": chunk["page"],
                    "clause": chunk["clause_no"],
                    "location": chunk["location"],
                    "score": score,
                    "matched_field": field,
                    "match_reasons": reasons,
                }
            )
        fields[field] = hits

    # 같은 청크가 여러 field에 걸린다. 본문은 여기에 한 번만 두고
    # fields[] 는 chunk_id 로 참조하게 하면 중복이 사라진다.
    referenced = [
        {
            "chunk_id": c["chunk_id"],
            "text": c["chunk_text"],
            "page": c["page"],
            "clause": c["clause_no"],
            "clause_kind": c["clause_kind"],
            "lang": c["lang"],
            "location": c["location"],
            "embedding": c.get("embedding"),
        }
        for c in chunks
        if c["chunk_id"] in used_ids
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "file_name": doc["file_name"],
            "file_hash": doc["file_hash"],
            "mime_type": doc["mime_type"],
            "page_count": doc["page_count"],
            "language": doc["language"],
            "text_source_summary": doc["text_source_summary"],
            "embedding_model": doc.get("embedding_model"),
            "embedding_dim": doc.get("embedding_dim"),
            "embedded": doc.get("embedded", False),
        },
        "retrieval": {
            "scorer": SCORER,
            "top_k": top_k,
            "min_score": min_score,
            "field_count": len(fields),
            "chunk_total": len(chunks),
            "chunk_referenced": len(referenced),
        },
        "fields": fields,
        "chunks": referenced,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("parse_files", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=0.15)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.parse_files:
        if not path.exists():
            print(f"건너뜀 (없음): {path}", file=sys.stderr)
            continue
        parse = json.loads(path.read_text(encoding="utf-8"))
        bundle = build_bundle(parse, args.top_k, args.min_score)
        dest = args.out / path.name.replace(".parse.json", ".retrieval.json")
        dest.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = " ".join(f"{f}={len(v)}" for f, v in bundle["fields"].items())
        print(f"{bundle['document']['file_name']}: {summary} -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

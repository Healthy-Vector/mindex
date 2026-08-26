"""회수 평가용 정답지 생성 (Phase 3a).

    PYTHONPATH=. python scripts/build_goldset.py

`testdata/k-rights/annotations/phase_h_actual_evidence.json`의 Evidence 781건을
회수 필드별 정답으로 재구성해 `eval/retrieval_goldset.json`에 쓴다.

## 왜 별도 산출물로 만드나

평가를 돌릴 때마다 라벨 매핑을 코드 안에서 즉석으로 하면, 매핑이 바뀌어도
아무도 모른다. 정답지를 파일로 고정하면 **무엇을 정답으로 삼았는지가 리뷰
대상**이 된다.

## 왜 chunk_id가 아니라 텍스트로 거는가

`chunk_id`는 문서 해시 + 순번이라 **청킹 방식을 바꾸면 전부 바뀐다.**
실제로 페이지 분할에서 조항 단위로 옮기면서 모든 id가 달라졌다.
chunk_id 기반 정답지는 만들자마자 썩는다. Evidence 텍스트는 문서가 바뀌지
않는 한 그대로다.

## 파이프라인에 의존하지 않는다

정답지는 주석 파일에서만 만든다. 파싱 결과를 섞으면 "파이프라인이 못 찾은
것"과 "애초에 정답이 아닌 것"이 구분되지 않는다. 그 판정은 평가 쪽이 한다.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

EVIDENCE = Path("testdata/k-rights/annotations/phase_h_actual_evidence.json")
MANIFEST = Path("testdata/k-rights/manifests/contract_pdf_manifest.json")
OUT = Path("eval/retrieval_goldset.json")

SCHEMA_VERSION = "mindex.retrieval-goldset.v1"

#: Evidence 라벨 → 회수 필드.
#:
#: `rights_type` 하나에 라벨 둘이 들어간다. Ground Truth 쪽이 `LEGAL_RIGHT`
#: (저작재산권의 지분권)와 `EXPLOITATION_MODE`(이용형태)를 이미 분리해 두었고,
#: 프로젝트가 두 축을 절대 합치지 않는다고 못박았다. 회수 질의 이름이
#: `rights_type` 하나인 것이 임시 방편이며, **추출 결과 단계에서는 분리해야
#: 한다.** 정답지는 어느 라벨에서 왔는지를 `label`에 남긴다.
LABEL_TO_FIELD = {
    "TERRITORY": "territory",
    "LICENSE_PERIOD": "period",
    "EXCLUSIVITY": "exclusivity",
    "LEGAL_RIGHT": "rights_type",
    "EXPLOITATION_MODE": "rights_type",
    "PAYMENT": "payment",
}

#: 회수는 하지만 채점할 정답이 없는 필드.
#:
#: 조용히 빼면 "6필드 전부 검증했다"는 착각이 남는다. 명시적으로 기록한다.
UNEVALUABLE = {
    "parties": (
        "정답 라벨이 없다. 당사자 정보에 대응할 만한 것은 IDENTITY_EVIDENCE "
        "2건뿐이라 86건 채점에 쓸 수 없다. 이 필드의 회수 품질은 측정되지 않는다."
    )
}


def main() -> int:
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence = data["actual_evidence"]

    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("contracts")
    pdf_by_id = {r["contract_id"]: r["pdf_path"] for r in rows}

    by_contract: dict[str, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    label_counts: collections.Counter[str] = collections.Counter()

    for e in evidence:
        field = LABEL_TO_FIELD.get(e["label_id"])
        if field is None:
            continue
        label_counts[e["label_id"]] += 1
        by_contract[e["contract_id"]][field].append(
            {
                "evidence_id": e["evidence_id"],
                "label": e["label_id"],
                "text": e["text"],
                "page_start": e["page_start"],
                "page_end": e["page_end"],
                # canonical Markdown 기준 offset. PDF 추출문 기준이 아니므로
                # 채점에 직접 쓰지 않고 참고용으로만 남긴다.
                "canonical_char_start": e["start_char"],
                "canonical_char_end": e["end_char"],
            }
        )

    contracts = []
    for cid in sorted(by_contract):
        fields = {
            f: sorted(v, key=lambda x: x["evidence_id"])
            for f, v in by_contract[cid].items()
        }
        contracts.append(
            {
                "contract_id": cid,
                "pdf_path": f"testdata/k-rights/{pdf_by_id[cid]}",
                "answer_count": sum(len(v) for v in fields.values()),
                "fields": fields,
            }
        )

    total = sum(c["answer_count"] for c in contracts)
    per_field = collections.Counter(
        f for c in contracts for f, v in c["fields"].items() for _ in v
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": str(EVIDENCE).replace("\\", "/"),
        "source_evidence_total": len(evidence),
        "match_unit": "정규화 후 공백 제거 텍스트의 포함 관계",
        "note": (
            "정답은 chunk_id가 아니라 Evidence 텍스트로 건다. chunk_id는 청킹 방식을 "
            "바꾸면 전부 달라지므로 정답지의 키가 될 수 없다."
        ),
        "label_to_field": LABEL_TO_FIELD,
        "label_counts": dict(sorted(label_counts.items())),
        "unevaluable_fields": UNEVALUABLE,
        "answer_total": total,
        "answers_per_field": dict(sorted(per_field.items())),
        "contract_count": len(contracts),
        "contracts": contracts,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{OUT}  ({OUT.stat().st_size / 1024:.0f}KB)")
    print(f"  Evidence {len(evidence)}건 중 회수 필드로 매핑된 정답 {total}건")
    print(f"  계약 {len(contracts)}건")
    for f, n in sorted(per_field.items()):
        print(f"    {f:12} {n:>3}")
    for f, why in UNEVALUABLE.items():
        print(f"    {f:12}   0  <- 측정 불가: {why.splitlines()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

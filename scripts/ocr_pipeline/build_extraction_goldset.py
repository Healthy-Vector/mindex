"""Task2 필드 추출 정답지 생성 — `eval/extraction_goldset.json`.

`ground_truth.json`에서 **필드 추출 채점에 필요한 것만** 추려 평평하게 편다.
충돌 판정(scenarios·findings)과 Evidence 위치는 빼고, 계약서를 읽어 필드값을
얼마나 정확히 뽑았는지만 본다.

    python scripts/ocr_pipeline/build_extraction_goldset.py

## 회수 정답지(`retrieval_goldset.json`)와 무엇이 다른가

    retrieval_goldset   "이 필드의 근거가 어느 조항인가"      Task1 채점
    extraction_goldset  "그 조항에서 어떤 값을 뽑아야 하나"    Task2 채점

## 왜 `field_status`를 그대로 남기나

**`ABSENT`와 `UNRESOLVED`는 오답이 아니라 정답이다.**

    ABSENT       평가 대상 문서에 해당 필드의 근거가 없음
    UNRESOLVED   관련 문언은 있으나 canonical 값 하나로 확정할 수 없음

`UNRESOLVED`인 기간에 날짜를 지어내면 **오답이자 위험한 오답**이다 — 없는
권리기간을 만들어내는 것이기 때문이다. 그래서 채점은 두 축으로 해야 한다.

    ① status 를 맞혔는가   (확정 가능/불가를 옳게 판단했는가)
    ② values 를 맞혔는가   (status 가 PRESENT_* 일 때만 의미 있다)

status만 맞히고 값이 틀리면 부분 점수다. 반대로 값이 맞아도 `UNRESOLVED`를
`PRESENT`로 단정했다면 그건 운이 좋았을 뿐이다.

## 뺀 것과 그 이유

    value_origin              저작 출처. 규격이 평가 export에서 생략 가능하다고 명시
    evidence_requirement_ids  Evidence 정답지(phase_h_actual_evidence.json)의 몫
    scenarios / findings      충돌 판정 채점용이지 추출 채점용이 아니다
    payment                   86건 전부 NOT_YET_PROJECTED — 측정 불가(아래 참조)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

GT = Path("testdata/k-rights/annotations/ground_truth.json")
REGISTRY = Path("testdata/k-rights/authoring/content_registry.yaml")
MANIFEST = Path("testdata/k-rights/manifests/contract_pdf_manifest.json")
OUT = Path("eval/extraction_goldset.json")

SCHEMA_VERSION = "mindex.extraction-goldset.v1"

#: 언어 코드(문서) → content_registry 의 제목 키.
#: 언어는 ISO 639-1(JA)이고 국가는 ISO 3166-1(JP)이라 서로 다른 값이다.
#: 합성데이터 내부 식별자는 JP를 쓰므로 둘 다 받는다.
TITLE_KEY = {"KO": "title_ko", "EN": "title_en", "JA": "title_jp", "JP": "title_jp"}


def load_titles() -> dict[str, dict]:
    """content_id / asset_id → 언어별 제목.

    GT는 작품을 `C007` 같은 dataset ID로 가리키는데, 이 ID는 DB payload에
    넣지 않기로 규격이 못박고 있다. 즉 **Task2 출력에는 ID가 없고 제목만
    있다.** 제목으로 대조할 수 있어야 `content` 필드가 채점 가능해진다.
    """
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for c in reg["contents"]:
        out[c["content_id"]] = {
            "ko": c.get("title_ko"),
            "en": c.get("title_en"),
            "ja": c.get("title_jp"),
            "kind": c.get("content_type"),
        }
    for a in reg.get("related_assets", []):
        out[a["asset_id"]] = {
            "ko": a.get("title_ko"),
            "en": a.get("title_en"),
            "ja": a.get("title_jp"),
            "kind": a.get("asset_type"),
            "parent_content_id": a.get("parent_content_id"),
            "relationship_type": a.get("relationship_type"),
        }
    return out


def build_fields(g: dict, titles: dict[str, dict], lang: str) -> dict:
    """GT의 grant 하나 → 채점용 필드 묶음.

    모든 필드가 `status`를 최상단에 갖도록 모양을 통일한다. GT는 필드마다
    값 키가 다른데(`values` / `value` / `start`·`end`), 그대로 두면 채점
    코드가 필드별 분기로 뒤덮인다.
    """
    c = g["content"]
    ids = c["content_ids"] + c["related_asset_ids"]
    key = {"KO": "ko", "EN": "en", "JA": "ja", "JP": "ja"}.get(lang, "ko")

    return {
        "content": {
            "status": c["field_status"],
            # dataset ID는 채점에 쓰지 않는다. 추적용으로만 남긴다.
            "_ids": ids,
            # 실제 대조 기준. 계약서 언어의 제목이 본문에 나온다.
            "titles": [titles[i][key] for i in ids if i in titles],
            "titles_all_langs": [titles[i] for i in ids if i in titles],
            "scope_type": c["scope_type"],
            "relationship_type": c["relationship_type"],
            "included_scope_values": c["included_scope_values"],
            "excluded_scope_values": c["excluded_scope_values"],
        },
        "legal_right": {
            "status": g["legal_right"]["field_status"],
            "values": g["legal_right"]["values"],
        },
        "exploitation_mode": {
            "status": g["exploitation_mode"]["field_status"],
            "values": g["exploitation_mode"]["values"],
        },
        "territory": {
            "status": g["territory"]["field_status"],
            "values": g["territory"]["values"],
            "excluded_values": g["territory"]["excluded_values"],
            "defined_values": g["territory"]["defined_values"],
        },
        "license_period": {
            "status": g["license_period"]["field_status"],
            "start": g["license_period"]["start"],
            "end": g["license_period"]["end"],
            # UNRESOLVED / PRESENT_DERIVED 일 때 근거가 되는 원문 표현.
            # 예: "three years from first commercial release; release date unavailable"
            "expression": g["license_period"]["expression"],
        },
        "exclusivity": {
            "status": g["exclusivity"]["field_status"],
            "value": g["exclusivity"]["value"],
        },
        "authority": {
            "status": g["authority_constraints"]["field_status"],
            "may_sublicense": g["authority_constraints"]["may_sublicense"],
            "allowed_recipient_types": g["authority_constraints"][
                "allowed_recipient_types"
            ],
            "target_recipient_type": g["authority_constraints"][
                "target_recipient_type"
            ],
        },
        "scope_modifiers": {
            # 리스트 자체에는 status가 없다. 항목마다 따로 갖는다.
            "count": len(g["scope_modifiers"]),
            "items": [
                {
                    "modifier_type": m["modifier_type"],
                    "dimension": m["dimension"],
                    "status": m["field_status"],
                    "values": m.get("values", []),
                }
                for m in g["scope_modifiers"]
            ],
        },
    }


def main() -> int:
    for p in (GT, REGISTRY):
        if not p.exists():
            print(f"없음: {p}", file=sys.stderr)
            return 1

    gt = json.loads(GT.read_text(encoding="utf-8"))
    titles = load_titles()
    grants_by_contract: dict[str, list[dict]] = {}
    for g in gt["rights_grants"]:
        grants_by_contract.setdefault(g["contract_id"], []).append(g)

    pdf_by_id = {}
    if MANIFEST.exists():
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pdf_by_id = {r["contract_id"]: r["pdf_path"] for r in man["contracts"]}

    contracts = []
    status_counter: dict[str, Counter] = {}
    for c in gt["contracts"]:
        cid = c["contract_id"]
        lang = c["language"]
        rows = []
        for g in grants_by_contract.get(cid, []):
            fields = build_fields(g, titles, lang)
            for name, f in fields.items():
                if "status" in f:
                    status_counter.setdefault(name, Counter())[f["status"]] += 1
            rows.append({"grant_id": g["grant_id"], "fields": fields})
        contracts.append(
            {
                "contract_id": cid,
                "language": lang,
                "agreement_type": c["agreement_type"],
                "pdf_path": pdf_by_id.get(cid),
                "grant_count": len(rows),
                "grants": rows,
            }
        )

    doc = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "ground_truth": str(GT).replace("\\", "/"),
            "gt_version": gt["version"],
            "gt_phase": gt["phase"],
            "content_registry": str(REGISTRY).replace("\\", "/"),
        },
        "scoring": {
            "axes": [
                "status — 확정 가능/불가를 옳게 판단했는가",
                "value  — status 가 PRESENT_* 일 때만 의미가 있다",
            ],
            "status_semantics": {
                "PRESENT_EXPLICIT": "문서에 명시됨",
                "PRESENT_DERIVED": "명시 문언에서 결정적으로 계산됨. 값이 채워져 있다",
                "UNRESOLVED": "문언은 있으나 canonical 값 하나로 확정 불가. 값을 지어내면 오답",
                "ABSENT": "문서에 근거가 없음. 부정 사실이 아니다(없다고 false로 전달하지 않는다)",
                "EXTERNAL_REFERENCE": "외부 문서로 값이 위임됨. 임의 전개하지 않는다",
            },
            "content_matching": (
                "dataset ID(C007 등)는 DB payload에 넣지 않기로 규격이 정했으므로 "
                "Task2 출력에는 없다. `titles`(계약서 언어 기준)로 대조한다. "
                "`_ids`는 추적용이며 채점에 쓰지 않는다."
            ),
            "grant_matching": (
                "계약당 grant가 여러 개면(2개 4건, 3개 2건) 예측과 정답을 짝지어야 한다. "
                "`grant_id` 는 Task2 출력에 없으므로 순서에 의존하지 말고 "
                "(content, territory, legal_right) 조합으로 최적 매칭할 것."
            ),
        },
        "unmeasurable": {
            "payment": (
                "86건 전부 payment_projection.status = NOT_YET_PROJECTED 라 "
                "정답 값이 없다. 채점하면 조용히 0%로 집계되어 결함처럼 보이므로 "
                "명시적으로 제외한다. 라벨이 생기면 이 항목을 지우고 다시 만든다."
            ),
        },
        "summary": {
            "contract_count": len(contracts),
            "grant_count": sum(c["grant_count"] for c in contracts),
            "grants_per_contract": dict(
                sorted(Counter(c["grant_count"] for c in contracts).items())
            ),
            "status_distribution": {
                k: dict(v.most_common()) for k, v in sorted(status_counter.items())
            },
        },
        "contracts": contracts,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    s = doc["summary"]
    print(f"{OUT}  ({OUT.stat().st_size / 1024:.0f}KB)")
    print(f"계약 {s['contract_count']}건 · grant {s['grant_count']}건")
    print(f"계약당 grant 수: {s['grants_per_contract']}")
    print()
    print(f"{'필드':<20}{'정답 분포'}")
    for name, dist in s["status_distribution"].items():
        parts = "  ".join(f"{k} {v}" for k, v in dist.items())
        print(f"  {name:<18}{parts}")
    print()
    print("측정 불가: payment (정답 라벨 0건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

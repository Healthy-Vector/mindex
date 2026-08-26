"""Task2 필드 추출 정답지 생성 — `eval/extraction_goldset.json`.

**Task2 출력과 같은 모양으로 정답을 만든다.** 그래야 필드 단위로 1:1 대조할 수
있다. 목표 형식은 `k-rights.db-contract-projection.v0.1`이다.

    python scripts/ocr_pipeline/build_extraction_goldset.py

## 정답이 네 곳에 흩어져 있다

`ground_truth.json` 하나로는 안 된다. 요청된 필드 중 계약 기본 정보와 금액이
거기 없다.

    ground_truth.json           권리(grant) 필드 + field_status
    contract_pdf_manifest.json  document_title
    authoring/contract_generation.yaml   agreement_date · parties · 금액
    authoring/content_registry.yaml      작품 제목(언어별)
    taxonomies/territory_ontology.yaml   지역 용어 정의 규칙

## 왜 `field_status`를 따로 싣나

**`ABSENT`와 `UNRESOLVED`는 오답이 아니라 정답이다.**

    UNRESOLVED   문언은 있으나 canonical 값 하나로 확정 불가
    ABSENT       문서에 근거가 없음. 부정 사실이 아니다

`UNRESOLVED`인 기간에 날짜를 지어내면 **오답이자 위험한 오답**이다 — 없는
권리기간을 만들어내는 것이기 때문이다. 그래서 채점이 두 축이어야 한다.

    ① status  확정 가능/불가를 옳게 판단했는가
    ② value   status 가 PRESENT_* 일 때만 의미가 있다

규격은 `field_status`를 DB payload에서 제외하라고 했으므로 `expected` 밖에
`field_status` 블록으로 분리해 둔다. 채점 보조값이지 정답 payload의 일부가
아니다.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

TESTDATA = Path("testdata/k-rights")
GT = TESTDATA / "annotations/ground_truth.json"
MANIFEST = TESTDATA / "manifests/contract_pdf_manifest.json"
GENERATION = TESTDATA / "authoring/contract_generation.yaml"
REGISTRY = TESTDATA / "authoring/content_registry.yaml"
OUT = Path("eval/extraction_goldset.json")

SCHEMA_VERSION = "mindex.extraction-goldset.v2"
TARGET_SCHEMA = "k-rights.db-contract-projection.v0.1"

#: GT의 scope_type → DB projection 규격의 scope_type.
#:
#: 규격 허용값: SERIES | SEASON | EPISODE | EDIT | MANIFESTATION | OST_MASTER
#:              | UNSPECIFIED
#:
#: ⚠️ `DERIVATIVE`(7건)에 대응하는 규격값이 없다. 2차적저작물(리메이크·포맷·
#: 각색)은 "작품의 어느 범위인가" 축이 아니라 별개 축이라 규격 목록에 자리가
#: 없다. 임의로 UNSPECIFIED에 접으면 리메이크 계약과 범위 미특정 계약이
#: 구분되지 않으므로, 원값을 그대로 두고 아래 open_questions에 남긴다.
SCOPE_TYPE_MAP = {
    "WORK": "SERIES",
    "SEASON": "SEASON",
    "EPISODE": "EPISODE",
    "EDIT": "EDIT",
    "RELATED_ASSET": "OST_MASTER",
    "UNRESOLVED": "UNSPECIFIED",
    "DERIVATIVE": "DERIVATIVE",  # 규격 목록에 없음 — open_questions 참조
}

#: 문서 언어 코드 → content_registry 제목 키.
#: 언어는 ISO 639-1(JA), 국가는 ISO 3166-1(JP)로 서로 다른 값이다.
#: 합성데이터 내부 식별자가 JP를 쓰므로 둘 다 받는다.
TITLE_LANG = {"KO": "ko", "EN": "en", "JA": "ja", "JP": "ja"}


def load_titles() -> dict[str, dict]:
    """content_id / asset_id → 언어별 제목과 관계 정보."""
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for c in reg["contents"]:
        out[c["content_id"]] = {
            "subject_type": "CONTENT",
            "ko": c.get("title_ko"),
            "en": c.get("title_en"),
            "ja": c.get("title_jp"),
            "relationship_type": None,
        }
    for a in reg.get("related_assets", []):
        out[a["asset_id"]] = {
            "subject_type": "RELATED_ASSET",
            "ko": a.get("title_ko"),
            "en": a.get("title_en"),
            "ja": a.get("title_jp"),
            "relationship_type": a.get("relationship_type"),
        }
    return out


def build_subjects(content: dict, titles: dict[str, dict], lang: str) -> list[dict]:
    """GT의 content 블록 → 규격의 `subjects[]`.

    GT는 작품을 `C007` 같은 dataset ID로 가리키는데, 그 ID는 DB payload에 넣지
    않기로 규격이 못박고 있다. 즉 **Task2 출력에는 ID가 없고 제목만 있다.**
    계약서 언어의 제목으로 바꿔 둬야 대조가 된다.
    """
    key = TITLE_LANG.get(lang, "ko")
    ids = content["content_ids"] + content["related_asset_ids"]
    scope = SCOPE_TYPE_MAP.get(content["scope_type"], content["scope_type"])

    if not ids:
        # UNRESOLVED 2건 — 어느 작품인지 확정하지 못한 계약이다.
        return [
            {
                "subject_type": None,
                "title": None,
                "scope_type": scope,
                "relationship_type": content["relationship_type"],
            }
        ]

    out = []
    for i in ids:
        meta = titles.get(i, {})
        out.append(
            {
                "subject_type": meta.get("subject_type"),
                "title": meta.get(key),
                "scope_type": scope,
                # GT 쪽 값을 우선하고, 없으면 레지스트리의 관계를 쓴다.
                "relationship_type": content["relationship_type"]
                or meta.get("relationship_type"),
            }
        )
    return out


def build_territory_scopes(t: dict) -> list[dict]:
    """GT의 territory 블록 → 규격의 `territory_scopes[] = {term, members}`.

    GT의 `values`는 **최종 국가 목록이 아니다.** 계약이 지역 용어를 쓰면 거기에
    용어(`ASIA` · `APAC` · `WORLDWIDE`)가 들어가고, 실제 국가는 `defined_values`
    에 따로 있다.

        {"values": ["ASIA"],      "defined_values": ["JP","SG"]}  -> term ASIA,      members JP,SG
        {"values": ["KR"],        "defined_values": []}           -> term KR,        members KR
        {"values": ["WORLDWIDE"], "excluded_values": ["US"]}      -> term WORLDWIDE, members 열거 불가
        {"values": ["APAC"],      "defined_values": []}           -> term APAC,      members 없음(전개 불가)

    territory_ontology.yaml 이 정한 원칙 그대로다 — ASIA·APAC은 기본 멤버가
    없고(`default_members: null`, `automatic_expansion: false`), 정의가 없으면
    임의로 펼치지 않는다.
    """
    terms = t["values"]
    defined = t["defined_values"]
    excluded = t["excluded_values"]
    out = []
    for term in terms:
        if defined:
            members = [c for c in defined if c not in excluded]
        elif len(term) == 2 and term.isupper():
            # 국가 코드 자체가 용어인 경우
            members = [term] if term not in excluded else []
        else:
            # WORLDWIDE / 정의 없는 ASIA·APAC — 열거할 수 없다
            members = None
        out.append(
            {
                "term": term,
                "members": members,
                # 규격은 excluded_values 를 payload 에 안 보내지만, 채점 시
                # "제외를 반영했는가"를 보려면 정답 쪽에는 있어야 한다.
                "_excluded": excluded,
            }
        )
    return out


def build_authority(a: dict) -> dict | None:
    """GT의 authority_constraints → 규격의 `authority`.

    ABSENT(81건)이면 `null`이다. 예시 payload의 두 번째 grant가 그 형태다.
    """
    if a["field_status"] == "ABSENT":
        return None
    return {
        "may_sublicense": a["may_sublicense"],
        "allowed_recipient_types": a["allowed_recipient_types"],
        "target_recipient_type": a["target_recipient_type"],
    }


def build_payment(ct: dict) -> dict | None:
    """commercial_terms → 규격의 `payment = {amount, currency}`.

    규격의 projection 규칙: **명시된 총액을 우선**하고, 없으면 동일 통화의
    중복되지 않는 구성금액만 합산한다. 서로 다른 통화는 환율 없이 합산하지
    않으며 이 경우 null 이다.

    실측상 86건 전부 `contract_value.field_status = PRESENT_EXPLICIT` 라
    총액이 명시돼 있다. 합산 경로는 타지 않는다.

    참고 — `ground_truth.json` 의 `payment_projection` 은 86건 전부
    `NOT_YET_PROJECTED` 라 쓸 수 없다. 원천은 여기다.
    """
    cv = ct.get("contract_value")
    if not cv or cv.get("field_status") != "PRESENT_EXPLICIT":
        return None
    return {"amount": cv["amount"], "currency": cv["currency_of_account"]}


def main() -> int:
    for p in (GT, MANIFEST, GENERATION, REGISTRY):
        if not p.exists():
            print(f"없음: {p}", file=sys.stderr)
            return 1

    gt = json.loads(GT.read_text(encoding="utf-8"))
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gen = yaml.safe_load(GENERATION.read_text(encoding="utf-8"))
    titles = load_titles()

    meta_by_id = {r["contract_id"]: r for r in man["contracts"]}
    gen_by_id = {c["contract_id"]: c for c in gen["contracts"]}
    grants_by_contract: dict[str, list[dict]] = {}
    for g in gt["rights_grants"]:
        grants_by_contract.setdefault(g["contract_id"], []).append(g)

    contracts = []
    status_counter: dict[str, Counter] = {}
    scope_counter: Counter = Counter()

    for c in gt["contracts"]:
        cid = c["contract_id"]
        lang = c["language"]
        meta = meta_by_id.get(cid, {})
        src = gen_by_id.get(cid, {})

        grants, statuses = [], []
        for g in grants_by_contract.get(cid, []):
            grants.append(
                {
                    "_grant_id": g["grant_id"],
                    "subjects": build_subjects(g["content"], titles, lang),
                    "legal_rights": g["legal_right"]["values"],
                    "exploitation_modes": g["exploitation_mode"]["values"],
                    "territory_scopes": build_territory_scopes(g["territory"]),
                    "license_period": {
                        "start": g["license_period"]["start"],
                        "end": g["license_period"]["end"],
                    },
                    "exclusivity": g["exclusivity"]["value"],
                    "authority": build_authority(g["authority_constraints"]),
                }
            )
            st = {
                "grant_id": g["grant_id"],
                "content": g["content"]["field_status"],
                "legal_rights": g["legal_right"]["field_status"],
                "exploitation_modes": g["exploitation_mode"]["field_status"],
                "territory_scopes": g["territory"]["field_status"],
                "license_period": g["license_period"]["field_status"],
                "exclusivity": g["exclusivity"]["field_status"],
                "authority": g["authority_constraints"]["field_status"],
            }
            # UNRESOLVED / PRESENT_DERIVED 의 근거가 되는 원문 표현
            if g["license_period"]["expression"]:
                st["license_period_expression"] = g["license_period"]["expression"]
            statuses.append(st)
            for k, v in st.items():
                if k not in ("grant_id", "license_period_expression"):
                    status_counter.setdefault(k, Counter())[v] += 1
            scope_counter[g["content"]["scope_type"]] += 1

        contracts.append(
            {
                "contract_id": cid,
                "pdf_path": meta.get("pdf_path"),
                "template_family": meta.get("template_family"),
                "expected": {
                    "document_language": lang,
                    "contract": {
                        "title": meta.get("document_title"),
                        "agreement_type": c["agreement_type"],
                        "agreement_date": src.get("agreement_date"),
                        "parties": [
                            {"role": p["role"], "name": p["name"]}
                            for p in src.get("parties", [])
                        ],
                        "rights_grants": grants,
                        "payment": build_payment(src.get("commercial_terms", {})),
                    },
                },
                "field_status": statuses,
            }
        )

    doc = {
        "schema_version": SCHEMA_VERSION,
        "target_payload_schema": TARGET_SCHEMA,
        "sources": {
            "grants_and_status": str(GT).replace("\\", "/"),
            "title": str(MANIFEST).replace("\\", "/") + " → document_title",
            "date_parties_payment": str(GENERATION).replace("\\", "/"),
            "asset_titles": str(REGISTRY).replace("\\", "/"),
        },
        "scoring": {
            "shape": (
                "`expected` 는 Task2 출력(k-rights.db-contract-projection.v0.1)과 "
                "같은 모양이다. 필드 경로를 그대로 맞대면 된다."
            ),
            "axes": [
                "status — 확정 가능/불가를 옳게 판단했는가 (`field_status` 블록)",
                "value  — status 가 PRESENT_* 일 때만 의미가 있다 (`expected` 블록)",
            ],
            "status_semantics": {
                "PRESENT_EXPLICIT": "문서에 명시됨",
                "PRESENT_DERIVED": "명시 문언에서 결정적으로 계산됨. 값이 채워져 있다",
                "UNRESOLVED": "문언은 있으나 canonical 값 하나로 확정 불가. 값을 지어내면 오답",
                "ABSENT": "문서에 근거가 없음. 부정 사실이 아니다",
                "EXTERNAL_REFERENCE": "외부 문서로 값이 위임됨. 임의 전개하지 않는다",
            },
            "grant_matching": (
                "계약당 grant 가 여러 개면(2개 4건, 3개 2건) 예측과 정답을 짝지어야 한다. "
                "`_grant_id` 는 추적용이며 Task2 출력에는 없다. 순서에 의존하지 말고 "
                "(subjects[].title, territory_scopes[].term, legal_rights) 조합으로 "
                "최적 매칭할 것."
            ),
            "underscore_keys": (
                "`_` 로 시작하는 키(`_grant_id`, `_excluded`)는 정답 payload 의 "
                "일부가 아니다. 추적·채점 보조용이므로 대조 대상에서 뺀다."
            ),
            "territory_members_null": (
                "`members: null` 은 '열거할 수 없음'이다(WORLDWIDE, 정의 없는 APAC). "
                "빈 배열과 구분해야 한다 — 빈 배열은 '제외 후 남은 국가가 없음'이다."
            ),
        },
        "open_questions": [
            {
                "id": "scope_type_DERIVATIVE",
                "detail": (
                    "GT 의 scope_type 중 DERIVATIVE(7건: REMAKE·FORMAT·ADAPTATION·"
                    "SECONDARY_USE_UNSPECIFIED)에 대응하는 규격값이 없다. 규격 허용값은 "
                    "SERIES|SEASON|EPISODE|EDIT|MANIFESTATION|OST_MASTER|UNSPECIFIED 다. "
                    "UNSPECIFIED 로 접으면 리메이크 계약과 범위 미특정 계약이 구분되지 "
                    "않으므로 원값 DERIVATIVE 를 그대로 뒀다. 규격에 값을 추가할지 "
                    "결정 필요."
                ),
            },
            {
                "id": "worldwide_members",
                "detail": (
                    "WORLDWIDE 는 집합 표현이라 국가로 열거할 수 없다(territory_ontology "
                    "의 set_expression_examples 참조). members 를 null 로 두고 _excluded "
                    "에 제외 국가를 남겼다. 규격의 {term, members} 만으로는 "
                    "'전세계에서 미국 제외'를 표현할 수 없다."
                ),
            },
        ],
        "summary": {
            "contract_count": len(contracts),
            "grant_count": sum(
                len(c["expected"]["contract"]["rights_grants"]) for c in contracts
            ),
            "grants_per_contract": dict(
                sorted(
                    Counter(
                        len(c["expected"]["contract"]["rights_grants"])
                        for c in contracts
                    ).items()
                )
            ),
            "payment_present": sum(
                1 for c in contracts if c["expected"]["contract"]["payment"]
            ),
            "scope_type_source_distribution": dict(scope_counter.most_common()),
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
    print(f"계약 {s['contract_count']}건 · grant {s['grant_count']}건 "
          f"· 계약당 {s['grants_per_contract']}")
    print(f"payment 있는 계약 {s['payment_present']}/{s['contract_count']}")
    print()
    print("필드별 정답 status 분포")
    for name, dist in s["status_distribution"].items():
        print(f"  {name:<20}" + "  ".join(f"{k} {v}" for k, v in dist.items()))
    print()
    print(f"scope_type 원값: {s['scope_type_source_distribution']}")
    print(f"열린 질문 {len(doc['open_questions'])}건: "
          + ", ".join(q["id"] for q in doc["open_questions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

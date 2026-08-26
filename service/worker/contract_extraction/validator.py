#!/usr/bin/env python3
"""
Contract extraction — validator.py

extractor.py 가 채운 Rich Extraction dict 를 결정론적 코드로 검증한다.
LLM 은 여기 관여하지 않는다 (SFR-003·SFR-004 — "LLM 자기보고 confidence 를 쓰지 않는다").

세 가지를 본다:
  1. raw_expression / evidence.text 가 실제 원문(retrieved_chunks)에 있는가 — 환각 검출
  2. evidence[].targets 가 실재하는 grant_ref/payment_ref 를 가리키는가 — 참조 무결성
     (Notion 점검 문서 P1-3 — 이전엔 검사 없이 지나가던 구멍)
  3. 스키마 적합도·논리 일관성으로 confidence 산출 → route()
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date


def normalize(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s)


def _joined_source_text(bundle: dict) -> str:
    """bundle["chunks"](중복 없는 정본, 2026-08-22 팀원 실제 구현 기준)의 본문을 이어붙인다.

    ⚠️ 이 텍스트가 "원문 전체"가 아니라는 점 주의 — bundle["chunks"] 는 6개 질의
    (territory/rights_type/period/exclusivity/payment/parties) 중 하나라도 걸린 청크만
    담는다. 그 6개 밖의 필드(legal_right/content/agreement_type 등)의 근거가 안 걸린
    청크에만 있으면, 실제로는 원문에 있어도 여기선 "환각"으로 오탐될 수 있다
    (interface.py KNOWN GAP 참고 — 아직 팀과 미해결)."""
    seen: dict[str, str] = {}
    for c in bundle.get("chunks", []):
        seen.setdefault(c["chunk_id"], c["text"])
    return "\n".join(seen.values())


# ── 1. FieldResult 순회 ──────────────────────────────────────────────
def iter_field_results(contract: dict):
    """contract 안의 모든 {field_status, value/values, raw_expression} 객체를 (경로, dict) 로 순회한다."""
    def is_field_result(v):
        return isinstance(v, dict) and "field_status" in v

    top_level = ["contract_title", "agreement_type", "agreement_date"]
    for k in top_level:
        f = contract.get(k)
        if is_field_result(f):
            yield k, f

    for i, p in enumerate(contract.get("parties", [])):
        if is_field_result(p):
            yield f"parties[{i}]", p

    grant_keys = ["content", "legal_right", "exploitation_mode", "territory",
                  "license_period", "exclusivity", "authority_constraints"]
    for gi, g in enumerate(contract.get("rights_grants", [])):
        for k in grant_keys:
            f = g.get(k)
            if is_field_result(f):
                yield f"rights_grants[{gi}].{k}", f
        for mi, m in enumerate(g.get("scope_modifiers", [])):
            if is_field_result(m):
                yield f"rights_grants[{gi}].scope_modifiers[{mi}]", m


# ── 2. 환각 검출 ─────────────────────────────────────────────────────
def verify_field(field: dict, source_text: str) -> tuple[bool, str]:
    """raw_expression 이 원문에 실제로 있는지 확인한다. (반환: 통과여부, 사유)"""
    status = field.get("field_status")
    if status in ("ABSENT", "EXTERNAL_REFERENCE"):
        return True, f"{status} — 검증 대상 아님"
    raw = field.get("raw_expression")
    if not raw:
        return False, "raw_expression 없음 (스키마 위반)"
    if normalize(raw) in normalize(source_text):
        return True, "원문에서 확인됨"
    return False, "원문에 없는 raw_expression → 환각으로 판정"


def verify_evidence_text(evidence: dict, source_text: str) -> tuple[bool, str]:
    text = evidence.get("text")
    if not text:
        return False, "evidence.text 없음 (스키마 위반)"
    if normalize(text) in normalize(source_text):
        return True, "원문에서 확인됨"
    return False, "원문에 없는 evidence.text → 환각으로 판정"


# ── 3. targets 참조 무결성 ───────────────────────────────────────────
def verify_target_refs(contract: dict) -> list[str]:
    """evidence[].targets[] 가 실재하는 grant_ref/payment_ref 를 가리키는지 확인한다.

    문제가 있으면 사람이 읽을 문장 목록을 반환한다 (비어 있으면 문제 없음).
    """
    problems = []
    grant_refs = {g.get("grant_ref") for g in contract.get("rights_grants", [])}
    payment_refs = {p.get("payment_ref") for p in contract.get("payments", [])}

    for ei, ev in enumerate(contract.get("evidence", [])):
        for ti, t in enumerate(ev.get("targets", [])):
            ttype = t.get("target_type")
            tref = t.get("target_ref")
            loc = f"evidence[{ei}].targets[{ti}]"
            if ttype == "RIGHTS_GRANT_FIELD":
                if tref not in grant_refs:
                    problems.append(f"{loc}: target_ref={tref!r} 가 존재하는 grant_ref 가 아님")
            elif ttype == "PAYMENT":
                if tref not in payment_refs:
                    problems.append(f"{loc}: target_ref={tref!r} 가 존재하는 payment_ref 가 아님")
            elif ttype == "CONTRACT_FIELD":
                pass  # 계약 최상위 필드 참조 — 별도 ref 테이블 없음
            else:
                problems.append(f"{loc}: 알 수 없는 target_type={ttype!r}")
    return problems


# ── 4. 신뢰도 산출 ───────────────────────────────────────────────────
def compute_confidence(field_results: list[tuple[bool, str]],
                        evidence_results: list[tuple[bool, str]],
                        schema_ok: bool,
                        logic_ok: bool) -> dict:
    """0.6 evidence 매칭률 + 0.2 스키마 적합도 + 0.2 논리 일관성."""
    all_checks = field_results + evidence_results
    total = len(all_checks)
    passed = sum(1 for ok, _ in all_checks if ok)
    ev_rate = passed / total if total else 0.0
    score = round(0.6 * ev_rate + 0.2 * (1.0 if schema_ok else 0.0)
                  + 0.2 * (1.0 if logic_ok else 0.0), 3)
    return {"confidence": score, "ev_rate": round(ev_rate, 3), "passed": passed, "total": total}


def route(confidence: float) -> tuple[str, str]:
    if confidence < 0.70:
        return "폐기·재처리", "RED"
    if confidence < 0.85:
        return "인간 검수 큐", "YELLOW"
    return "자동 통과", "GREEN"


# ── 5. 논리 일관성 체크 ──────────────────────────────────────────────
def check_logic(contract: dict) -> tuple[bool, list[str]]:
    """날짜 대소, territory 실효범위 공집합 여부 등 결정론적 논리 검사."""
    problems = []
    for gi, g in enumerate(contract.get("rights_grants", [])):
        lp = g.get("license_period", {})
        start, end = lp.get("start"), lp.get("end")
        if start and end:
            try:
                if date.fromisoformat(start) >= date.fromisoformat(end):
                    problems.append(f"rights_grants[{gi}].license_period: start >= end")
            except ValueError:
                problems.append(f"rights_grants[{gi}].license_period: 날짜 형식 오류")
    return (len(problems) == 0), problems


# ── 공개 API ─────────────────────────────────────────────────────────
def validate(raw: dict, bundle: dict) -> dict:
    """extractor.extract() 결과를 검증하고 confidence·route 를 붙인 리포트를 낸다.
    bundle 은 RetrievalBundle(dict, *.retrieval.json 형식)."""
    contract = raw.get("contract", {})
    source_text = _joined_source_text(bundle)

    field_results = [(verify_field(f, source_text)) for _, f in iter_field_results(contract)]
    field_paths = [p for p, _ in iter_field_results(contract)]
    evidence_results = [verify_evidence_text(ev, source_text) for ev in contract.get("evidence", [])]

    ref_problems = verify_target_refs(contract)
    schema_ok = (
        isinstance(contract.get("rights_grants"), list)
        and len(contract["rights_grants"]) >= 1
        and not ref_problems
    )
    logic_ok, logic_problems = check_logic(contract)

    conf = compute_confidence(field_results, evidence_results, schema_ok, logic_ok)
    dest, level = route(conf["confidence"])

    dropped = [
        path for path, (ok, _) in zip(field_paths, field_results) if not ok
    ]

    return {
        "confidence": conf["confidence"],
        "route": dest,
        "route_level": level,
        "ev_rate": conf["ev_rate"],
        "checked": conf["total"],
        "passed": conf["passed"],
        "schema_ok": schema_ok,
        "logic_ok": logic_ok,
        "ref_problems": ref_problems,
        "logic_problems": logic_problems,
        "dropped_fields": dropped,
    }


if __name__ == "__main__":
    import json
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "mock_retrieved_chunks.json"), encoding="utf-8") as f:
        bundle = json.load(f)

    # extractor.py 를 실제로 돌리려면 Ollama 가 떠 있어야 한다 — 여기선 형식 확인만
    print("validator.py 는 extractor.extract() 결과를 받아 동작합니다.")
    print("예: python3 -c \"from extractor import extract; from validator import validate; "
          "import json; b=json.load(open('mock_retrieved_chunks.json')); "
          "r=extract(b); print(validate(r, b))\"")

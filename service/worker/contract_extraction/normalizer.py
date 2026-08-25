#!/usr/bin/env python3
"""
Contract extraction — normalizer.py

스키마 enum(territory/legal_right/exploitation_mode/exclusivity 등)은 이미
extractor 단계의 JSON Schema 강제(format:schema)로 보장된다. 그래도 결정론적
코드로만 계산 가능한 것이 두 가지 남는다 — 이 모듈이 그 둘을 담당한다.

  1. territory 실효범위 계산 — Notion 샘플의 "ASIA 정의는 KR/JP/SG 이지만
     KR carve-out 이 있어 실제 정규화 범위는 JP/SG" 케이스.
     (Notion 점검 문서 P1-4 — 이전엔 계산 로직 자체가 없었음)
  2. 날짜 형식 검증 — schema.json 이 pattern 제약을 못 쓰므로(grammar 미지원)
     프롬프트 지시에만 의존한다. 여기서 한 번 더 형식을 확인한다.
"""
from __future__ import annotations

import re
from datetime import date

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_date(value: str | None) -> bool:
    if not value or not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def expand_territory(territory: dict) -> dict:
    """values/excluded_values/definitions 로부터 실효 국가 집합을 계산한다.

    입력 예 (Notion 샘플 grant-1):
        values=["ASIA"], excluded_values=["KR"],
        definitions=[{"term":"ASIA","members":["KR","JP","SG"]}]
    출력: {"effective": ["JP","SG"], "warnings": []}
    """
    values = territory.get("values") or []
    excluded = territory.get("excluded_values") or []
    definitions = {d["term"]: d.get("members", []) for d in (territory.get("definitions") or [])}

    # 1) values 를 국가 단위로 전개 — 정의가 있으면 펼치고, 없으면 그대로 둔다
    #    (Notion 규칙: "ASIA/APAC 는 계약 정의가 없으면 임의 국가 목록으로 확장하지 않는다")
    expanded: list[str] = []
    warnings: list[str] = []
    for v in values:
        if v in definitions:
            expanded.extend(definitions[v])
        elif v in ("ASIA", "APAC") and v not in definitions:
            warnings.append(f"'{v}' 에 대한 definitions 가 없어 국가로 펼치지 않음 — 그대로 유지")
            expanded.append(v)
        else:
            expanded.append(v)

    # 2) excluded_values 도 같은 방식으로 전개 후 차집합
    excluded_expanded: list[str] = []
    for v in excluded:
        if v in definitions:
            excluded_expanded.extend(definitions[v])
        else:
            excluded_expanded.append(v)

    effective = [c for c in dict.fromkeys(expanded) if c not in excluded_expanded]

    if not effective:
        warnings.append("실효 territory 가 공집합 — values/excluded_values 조합을 확인할 것")

    unexpected_excludes = [v for v in excluded_expanded if v not in expanded]
    if unexpected_excludes:
        warnings.append(
            f"excluded_values 에 values/definitions 범위 밖 항목이 있음: {unexpected_excludes}"
        )

    return {"effective": effective, "warnings": warnings}


def build_territory_scopes(territory: dict) -> list[dict]:
    """Compact DB Projection 의 territory_scopes[] 형태로 변환한다.

    Notion 압축 스키마 예시 기준 — 원래 term(예: "ASIA")은 유지하되,
    members 는 carve-out 이 반영된 실효 국가만 남긴다.
        입력: values=["ASIA"], excluded=["KR"], definitions=[{ASIA:[KR,JP,SG]}]
        출력: [{"term":"ASIA","members":["JP","SG"]}]
    정의가 없는 단일 국가 값은 그 자체로 term=members=[국가코드] 항목이 된다.
    carve-out 으로 완전히 비게 된 term 은 제외한다.
    """
    values = territory.get("values") or []
    excluded = territory.get("excluded_values") or []
    definitions = {d["term"]: d.get("members", []) for d in (territory.get("definitions") or [])}

    excluded_expanded: set[str] = set()
    for v in excluded:
        excluded_expanded.update(definitions.get(v, [v]))

    scopes = []
    for v in values:
        members = definitions.get(v, [v])
        members = [m for m in members if m not in excluded_expanded]
        if members:
            scopes.append({"term": v, "members": members})
    return scopes


def normalize_rights_grant(grant: dict) -> dict:
    """rights_grant 하나에 territory.effective / license_period 검증을 덧붙인다.

    원본 필드는 건드리지 않고 파생 정보만 추가한다 — LLM 출력을 덮어쓰지 않는다는 원칙 유지.
    """
    out = dict(grant)
    territory = grant.get("territory") or {}
    out["_territory_effective"] = expand_territory(territory)
    out["_territory_scopes"] = build_territory_scopes(territory)

    lp = grant.get("license_period") or {}
    date_problems = []
    for k in ("start", "end"):
        v = lp.get(k)
        if v is not None and not is_valid_date(v):
            date_problems.append(f"license_period.{k}={v!r} 가 YYYY-MM-DD 형식이 아님")
    out["_date_problems"] = date_problems
    return out


def normalize_contract(raw: dict) -> dict:
    """extractor 출력 전체에 정규화 파생 필드를 붙인다. validator 이후, projector 이전에 호출."""
    contract = dict(raw.get("contract", {}))
    contract["rights_grants"] = [normalize_rights_grant(g) for g in contract.get("rights_grants", [])]

    date_problems = []
    ad = contract.get("agreement_date", {})
    if ad.get("value") and not is_valid_date(ad["value"]):
        date_problems.append(f"agreement_date.value={ad['value']!r} 가 YYYY-MM-DD 형식이 아님")
    contract["_agreement_date_problems"] = date_problems

    out = dict(raw)
    out["contract"] = contract
    return out


if __name__ == "__main__":
    sample = {
        "field_status": "PRESENT_EXPLICIT",
        "values": ["ASIA"],
        "excluded_values": ["KR"],
        "definitions": [{"term": "ASIA", "members": ["KR", "JP", "SG"]}],
        "raw_expression": "아시아란 대한민국, 일본 및 싱가포르를 의미하되 대한민국은 제외한다",
    }
    print(expand_territory(sample))  # {'effective': ['JP', 'SG'], 'warnings': []}

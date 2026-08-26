"""contract-extraction-worker 결과를 업로드 화면 DTO로 변환한다.

이 모듈은 worker 패키지를 import하지 않는다. 따라서 worker가 별도 브랜치·컨테이너로
배포돼도 ``staging.extract_result.payload``의 JSON 계약만 지키면 API 서버에서 사용할 수
있다. 변환할 수 없는 값은 추측하지 않고 HITL 편집 화면이 수정할 수 있도록 ``None``과
``conversionWarnings``로 남긴다.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from itertools import product
from typing import Any, Iterable, Mapping

WORKER_TO_DB_LEGAL_RIGHT = {
    "INTERACTIVE_TRANSMISSION": "TRANSMISSION",
    "BROADCASTING": "BROADCAST",
    "DERIVATIVE_WORK_CREATION": "DERIVATIVE_WORK_CREATION",
    "EXHIBITION": "PUBLIC_PERFORMANCE",
    "PERFORMANCE": "PUBLIC_PERFORMANCE",
}

WORKER_TO_DB_EXPLOITATION_MODE = {
    "SVOD": "SVOD",
    "AVOD": "AVOD",
    "TVOD": "TVOD",
    "TV_LINEAR": "TV_LINEAR",
    "THEATRICAL": "THEATRICAL",
    "MUSIC_STREAMING": "AUDIO_STREAMING",
    "ON_DEMAND_AUDIOVISUAL": "VOD",
}

WORKER_TO_UI_EXCLUSIVITY = {
    "EXCLUSIVE": "exclusive",
    "NON_EXCLUSIVE": "non_exclusive",
}

_RESOLVED_STATUSES = {"PRESENT_EXPLICIT", "PRESENT_DERIVED"}
_UI_EVIDENCE_FIELD = {
    "legal_right": "legalRight",
    "exploitation_mode": "exploitationMode",
    "territory": "territory",
    "license_period": "period",
    "exclusivity": "exclusivity",
}


def _raw(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """worker 전체 결과 또는 raw 결과만 허용한다."""
    candidate = payload.get("raw", payload)
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get("contract"), Mapping):
        raise ValueError("worker extraction payload의 raw.contract가 필요합니다")
    return candidate


def _field_value(field: Mapping[str, Any] | None) -> Any:
    if not field or field.get("field_status") not in _RESOLVED_STATUSES:
        return None
    return field.get("value")


def _field_values(field: Mapping[str, Any] | None) -> list[str]:
    if not field or field.get("field_status") not in _RESOLVED_STATUSES:
        return []
    return [value for value in field.get("values") or [] if isinstance(value, str)]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _as_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def _party_name(parties: list[Mapping[str, Any]], role: str) -> str | None:
    for party in parties:
        if party.get("role") == role and party.get("name"):
            return str(party["name"])
    return None


def _evidence_index(contract: Mapping[str, Any], confidence: float | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for evidence in contract.get("evidence") or []:
        if not isinstance(evidence, Mapping) or not evidence.get("text"):
            continue
        item = {
            "location": evidence.get("section") or "본문",
            "page": evidence.get("page_start"),
            "clause": evidence.get("section") or "",
            "quote": evidence["text"],
            "confidence": confidence,
        }
        for target in evidence.get("targets") or []:
            if target.get("target_type") != "RIGHTS_GRANT_FIELD":
                continue
            target_ref = target.get("target_ref")
            field = target.get("field")
            if target_ref and field:
                index.setdefault((str(target_ref), str(field)), []).append(item)
    return index


def _field_evidence(
    evidence_index: Mapping[tuple[str, str], list[dict[str, Any]]],
    grant_ref: str,
    field_name: str,
    field: Mapping[str, Any],
    confidence: float | None,
) -> list[dict[str, Any]]:
    entries = evidence_index.get((grant_ref, field_name))
    if entries:
        return entries
    quote = field.get("raw_expression")
    if not quote:
        return []
    return [{"location": "본문", "page": None, "clause": "", "quote": quote, "confidence": confidence}]


def _expand_territories(
    values: list[str], territory_group_members: Mapping[str, list[str]], warnings: list[str]
) -> list[str]:
    countries: list[str] = []
    for value in values:
        members = territory_group_members.get(value)
        if members is not None:
            countries.extend(members)
        elif len(value) == 2 and value.isupper():
            countries.append(value)
        else:
            warnings.append(f"territory 코드 {value}를 화면 국가 목록으로 변환하지 못했습니다")
    return _dedupe(countries)


def _mapped_codes(
    values: list[str], mapping: Mapping[str, str], field_name: str, warnings: list[str]
) -> list[str]:
    mapped: list[str] = []
    for value in values:
        target = mapping.get(value)
        if target is None:
            warnings.append(f"{field_name} 코드 {value}는 현재 운영 참조 데이터에 없습니다")
            continue
        mapped.append(target)
    return _dedupe(mapped)


def _right_rows(
    contract: Mapping[str, Any],
    confidence: float | None,
    territory_group_members: Mapping[str, list[str]],
) -> list[dict[str, Any]]:
    evidence_index = _evidence_index(contract, confidence)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for grant in contract.get("rights_grants") or []:
        grant_ref = str(grant.get("grant_ref") or "")
        legal_field = grant.get("legal_right") or {}
        mode_field = grant.get("exploitation_mode") or {}
        territory_field = grant.get("territory") or {}
        period_field = grant.get("license_period") or {}
        exclusivity_field = grant.get("exclusivity") or {}
        warnings: list[str] = []

        legal_codes = _mapped_codes(
            _field_values(legal_field), WORKER_TO_DB_LEGAL_RIGHT, "legalRight", warnings
        )
        mode_codes = _mapped_codes(
            _field_values(mode_field), WORKER_TO_DB_EXPLOITATION_MODE, "exploitationMode", warnings
        )
        territories = _expand_territories(
            _field_values(territory_field), territory_group_members, warnings
        )
        exclusivity = WORKER_TO_UI_EXCLUSIVITY.get(_field_value(exclusivity_field))
        if _field_value(exclusivity_field) and exclusivity is None:
            warnings.append(
                f"exclusivity 코드 {_field_value(exclusivity_field)}는 화면 값으로 변환하지 못했습니다"
            )

        if not legal_codes:
            legal_codes = [None]
            if legal_field.get("field_status") not in _RESOLVED_STATUSES:
                warnings.append("legalRight가 원문에서 확정되지 않았습니다")
        if not mode_codes:
            mode_codes = [None]
            if mode_field.get("field_status") not in _RESOLVED_STATUSES:
                warnings.append("exploitationMode가 원문에서 확정되지 않았습니다")

        evidence = {
            _UI_EVIDENCE_FIELD[field_name]: _field_evidence(
                evidence_index, grant_ref, field_name, field, confidence
            )
            for field_name, field in (
                ("legal_right", legal_field),
                ("exploitation_mode", mode_field),
                ("territory", territory_field),
                ("license_period", period_field),
                ("exclusivity", exclusivity_field),
            )
        }
        for legal_code, mode_code in product(legal_codes, mode_codes):
            key = (
                grant_ref,
                legal_code,
                mode_code,
                tuple(territories),
                period_field.get("start"),
                period_field.get("end"),
                exclusivity,
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "contentAssetId": None,
                    "territories": territories,
                    "legalRight": legal_code,
                    "exploitationMode": mode_code,
                    "exclusivity": exclusivity,
                    "period": {
                        "start": period_field.get("start"),
                        "end": period_field.get("end"),
                    },
                    "conditionsRaw": {
                        "authorityConstraints": grant.get("authority_constraints"),
                        "scopeModifiers": grant.get("scope_modifiers") or [],
                        "workerGrantRef": grant_ref or None,
                    },
                    "evidence": evidence,
                    "conversionWarnings": list(warnings),
                }
            )
    return rows


def to_upload_result(
    payload: Mapping[str, Any],
    *,
    ip_candidates: Iterable[Mapping[str, Any]] = (),
    territory_group_members: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """worker 결과 JSONB를 ``GET /extract/{tmpid}``의 ``result`` DTO로 바꾼다.

    ``ip_candidates``와 ``territory_group_members``는 API 계층이 DB에서 조회해 주입한다.
    이 함수는 순수 변환만 수행하므로 worker 배포 브랜치와 독립적으로 테스트할 수 있다.
    """
    raw = _raw(payload)
    contract = raw["contract"]
    validation = payload.get("validation") if isinstance(payload.get("validation"), Mapping) else {}
    confidence = validation.get("confidence")
    parties = [party for party in contract.get("parties") or [] if isinstance(party, Mapping)]
    payments = [payment for payment in contract.get("payments") or [] if isinstance(payment, Mapping)]
    payment = payments[0] if payments else {}
    groups = territory_group_members or {}

    return {
        "contractInfo": {
            "title": _field_value(contract.get("contract_title")),
            # D-36 — 판정·저장에 쓰는 당사자를 DTO에도 싣는다. 화면이 patch로 고칠 수
            # 있고, 안 고치면 서버가 이 값을 그대로 쓴다. counterparty는 화면이 이미
            # 쓰고 있는 이름이라 grantee와 같은 값으로 남겨둔다.
            "grantor": _party_name(parties, "GRANTOR"),
            "grantee": _party_name(parties, "GRANTEE"),
            "counterparty": _party_name(parties, "GRANTEE"),
            "signedDate": _field_value(contract.get("agreement_date")),
            "lang": str(raw.get("document", {}).get("language") or "").lower() or None,
            "amount": _as_number(payment.get("amount")),
            "currency": payment.get("currency"),
        },
        "rights": _right_rows(contract, confidence, groups),
        "ipCandidates": [dict(candidate) for candidate in ip_candidates],
        # worker payload에는 문서 전체 텍스트를 보관하지 않는다. 빈 값은 화면에서
        # 원문 미리보기 기능이 별도 API/저장소를 통해 제공돼야 한다는 뜻이다.
        "rawText": "",
        "confidence": confidence,
    }

#!/usr/bin/env python3
"""
Contract extraction — projector.py

Rich Extraction(내부 검증용, field_status+raw_expression 포함) 을
Compact DB Projection(Notion v0.2 "DB 전달용 compact schema") 으로 축약한다.

이 단계에서 사라지는 것:
  - field_status, raw_expression (검증엔 이미 썼으니 DB엔 안 실어도 됨)
  - grant_ref/payment_ref/evidence_ref (payload 내부 임시 참조 — DB 밖으로 안 나감, ID 정책 §10)
  - evidence[] 전체 (DB 프로젝션에는 없음 — 별도 경로로 필요하면 원본 Rich Extraction 을 참조)

normalizer.normalize_contract() 를 먼저 거친 dict 를 받는다 (territory_scopes 계산 때문).
"""
from __future__ import annotations


def _value(field: dict | None):
    return field.get("value") if field else None


def _values(field: dict | None):
    return field.get("values") if field else []


def _project_party(p: dict) -> dict:
    return {"role": p.get("role"), "name": p.get("name")}


def _project_subject(s: dict) -> dict:
    return {
        "subject_type": s.get("subject_type"),
        "title": s.get("title"),
        "scope_type": s.get("scope_type"),
        "relationship_type": s.get("relationship_type"),
    }


def _project_authority(a: dict | None) -> dict | None:
    if not a or a.get("field_status") == "ABSENT":
        return None
    return {
        "may_sublicense": a.get("may_sublicense"),
        "allowed_recipient_types": a.get("allowed_recipient_types") or [],
        "target_recipient_type": a.get("target_recipient_type"),
    }


def _project_grant(g: dict) -> dict:
    content = g.get("content") or {}
    return {
        "subjects": [_project_subject(s) for s in content.get("subjects", [])],
        "legal_rights": _values(g.get("legal_right")) or [],
        "exploitation_modes": _values(g.get("exploitation_mode")) or [],
        # normalizer.normalize_rights_grant() 가 붙인 파생 필드 — carve-out 반영된 실효 범위
        "territory_scopes": g.get("_territory_scopes", []),
        "license_period": {
            "start": (g.get("license_period") or {}).get("start"),
            "end": (g.get("license_period") or {}).get("end"),
        },
        "exclusivity": _value(g.get("exclusivity")),
        "authority": _project_authority(g.get("authority_constraints")),
    }


def _project_payments(payments: list[dict]) -> list[dict]:
    return [{"amount": p.get("amount"), "currency": p.get("currency")} for p in payments]


def project(normalized: dict, request_id: str, source_document_ref: str) -> dict:
    """normalizer.normalize_contract() 출력을 받아 Compact DB Projection 을 만든다."""
    contract = normalized.get("contract", {})

    payload_contract = {
        "title": _value(contract.get("contract_title")),
        "agreement_type": _value(contract.get("agreement_type")),
        "agreement_date": _value(contract.get("agreement_date")),
        "parties": [_project_party(p) for p in contract.get("parties", [])],
        "rights_grants": [_project_grant(g) for g in contract.get("rights_grants", [])],
        # Notion 압축 스키마 예시는 payment 단수형이지만, Rich 스키마는 배열(payments[])이라
        # 다건 지급을 그대로 보존한다 (동일 지급의무 중복 생성 금지 규칙은 Task 1/2 이전 단계 책임).
        "payments": _project_payments(contract.get("payments", [])),
    }

    return {
        "request_id": request_id,
        "source_document_ref": source_document_ref,
        "payload": {
            "schema_version": "k-rights.db-contract-projection.v0.1",
            "document_language": normalized.get("document", {}).get("language"),
            "contract": payload_contract,
        },
    }


if __name__ == "__main__":
    # 최소 형태 확인 — 실제 값은 extractor→normalizer 를 거쳐야 채워진다
    demo = {
        "document": {"language": "KO"},
        "contract": {
            "contract_title": {"value": "테스트 계약", "field_status": "PRESENT_EXPLICIT"},
            "agreement_type": {"value": "DIRECT_LICENSE", "field_status": "PRESENT_DERIVED"},
            "agreement_date": {"value": "2026-01-01", "field_status": "PRESENT_EXPLICIT"},
            "parties": [{"role": "GRANTOR", "name": "A사"}, {"role": "GRANTEE", "name": "B사"}],
            "rights_grants": [],
            "payments": [{"payment_ref": "payment-1", "amount": "100.00", "currency": "USD"}],
        },
    }
    import json
    print(json.dumps(project(demo, "req-1", "ref-1"), ensure_ascii=False, indent=2))

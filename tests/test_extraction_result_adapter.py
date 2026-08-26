from app.services.extraction_result import to_upload_result


def field(value, raw=None, status="PRESENT_EXPLICIT"):
    return {"field_status": status, "value": value, "raw_expression": raw}


def values(values_, raw=None, status="PRESENT_EXPLICIT"):
    return {"field_status": status, "values": values_, "raw_expression": raw}


def test_worker_payload_maps_to_upload_screen_dto():
    payload = {
        "raw": {
            "document": {"language": "KO"},
            "contract": {
                "contract_title": field("겨울의 신호 이용허락계약서", "겨울의 신호 이용허락계약서"),
                "agreement_date": field("2027-03-01", "2027년 3월 1일"),
                "parties": [
                    {"role": "GRANTOR", "name": "해솔미디어", "field_status": "PRESENT_EXPLICIT", "raw_expression": "해솔미디어"},
                    {"role": "GRANTEE", "name": "온웨이브", "field_status": "PRESENT_EXPLICIT", "raw_expression": "온웨이브"},
                ],
                "payments": [{"amount": "300000.00", "currency": "USD"}],
                "rights_grants": [
                    {
                        "grant_ref": "grant-1",
                        "legal_right": values(["INTERACTIVE_TRANSMISSION"], "전송권"),
                        "exploitation_mode": values(["SVOD"], "구독형 VOD"),
                        "territory": values(["APAC"], "아시아·태평양"),
                        "license_period": {"field_status": "PRESENT_EXPLICIT", "start": "2027-07-01", "end": "2029-06-30", "raw_expression": "2027년 7월 1일부터 2029년 6월 30일까지"},
                        "exclusivity": field("EXCLUSIVE", "독점"),
                        "authority_constraints": {"field_status": "ABSENT", "raw_expression": None},
                        "scope_modifiers": [],
                    }
                ],
                "evidence": [
                    {"text": "전송권", "section": "제3조", "page_start": 2, "targets": [{"target_type": "RIGHTS_GRANT_FIELD", "target_ref": "grant-1", "field": "legal_right"}]}
                ],
            },
        },
        "validation": {"confidence": 0.918},
    }

    result = to_upload_result(
        payload,
        ip_candidates=[{"ipId": 7, "title": "겨울의 신호", "score": 0.94}],
        territory_group_members={"APAC": ["KR", "JP", "SG"]},
    )

    assert result["contractInfo"] == {
        "title": "겨울의 신호 이용허락계약서",
        "grantor": "해솔미디어",
        "grantee": "온웨이브",
        "counterparty": "온웨이브",
        "signedDate": "2027-03-01",
        "lang": "ko",
        "amount": 300000,
        "currency": "USD",
    }
    assert result["ipCandidates"][0]["ipId"] == 7
    right = result["rights"][0]
    assert right["legalRight"] == "TRANSMISSION"
    assert right["exploitationMode"] == "SVOD"
    assert right["territories"] == ["KR", "JP", "SG"]
    assert right["evidence"]["legalRight"] == [{
        "location": "제3조", "page": 2, "clause": "제3조", "quote": "전송권", "confidence": 0.918
    }]


def test_unresolved_or_unknown_worker_values_are_not_guessed():
    payload = {
        "raw": {
            "document": {"language": "JP"},
            "contract": {
                "contract_title": field("계약"),
                "agreement_date": field("2027-01-01"),
                "parties": [],
                "payments": [],
                "evidence": [],
                "rights_grants": [
                    {
                        "grant_ref": "grant-1",
                        "legal_right": values([], "범위 미정", "UNRESOLVED"),
                        "exploitation_mode": values(["DIGITAL_DISTRIBUTION_UNSPECIFIED"], "미특정 이용"),
                        "territory": values(["ASIA"], "아시아"),
                        "license_period": {"field_status": "UNRESOLVED", "start": None, "end": None, "raw_expression": "공개일 기준"},
                        "exclusivity": field("NON_EXCLUSIVE", "비독점"),
                        "authority_constraints": {"field_status": "ABSENT", "raw_expression": None},
                        "scope_modifiers": [],
                    }
                ],
            },
        },
        "validation": {"confidence": 0.7},
    }

    right = to_upload_result(payload)["rights"][0]

    assert right["legalRight"] is None
    assert right["exploitationMode"] is None
    assert right["territories"] == []
    assert right["period"] == {"start": None, "end": None}
    assert right["exclusivity"] == "non_exclusive"
    assert len(right["conversionWarnings"]) == 3

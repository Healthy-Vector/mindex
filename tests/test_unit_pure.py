"""DB 없이 도는 순수 단위 테스트 (P2-DB 정렬 후)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.auth import PinRequest, TokenResponse
from app.schemas.common import camelize_json_keys
from app.schemas.contracts import ChunkIn, VerifyRequest
from app.schemas.ips import AssetIn, IpListItem, IpOut
from app.schemas.search import SearchRequest
from app.services.territory import to_daterange_literal, end_inclusive_from_upper
from app.services.ip_norm import norm_key
from app.services.display import compute_display


def test_daterange_literal_is_half_open():
    assert to_daterange_literal(date(2027, 1, 1), date(2028, 12, 31)) == "[2027-01-01,2029-01-01)"


def test_end_inclusive_from_upper():
    assert end_inclusive_from_upper(date(2029, 1, 1)) == date(2028, 12, 31)
    assert end_inclusive_from_upper(None) is None


def test_norm_key_removes_space_and_punct():
    assert norm_key("  겨울의 신호! ") == norm_key("겨울의신호")
    assert norm_key("The Office (US)") == norm_key("theofficeus")


def test_display_states():
    today = date(2026, 8, 25)
    assert compute_display(date(2027, 1, 1), date(2028, 1, 1), today)[0] == "BEFORE_TERM"
    assert compute_display(date(2026, 1, 1), date(2027, 1, 1), today)[0] == "IN_TERM"
    assert compute_display(date(2026, 1, 1), date(2026, 9, 10), today)[0] == "EXPIRING"
    assert compute_display(date(2024, 1, 1), date(2026, 1, 1), today)[0] == "EXPIRED"
    assert compute_display(None, None, today) == (None, None)


def test_pin_api_does_not_expose_team_id():
    assert PinRequest.model_validate({"pin": "1234"}).pin == "1234"
    with pytest.raises(ValidationError):
        PinRequest.model_validate({"pin": "12ab"})
    body = TokenResponse(
        session_token="jwt",
        expires_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        ttl_seconds=900,
    ).model_dump(by_alias=True, mode="json")
    assert body["sessionToken"] == "jwt"
    assert body["ttlSeconds"] == 900
    assert "teamId" not in body


def test_contract_requires_nonempty_rights():
    with pytest.raises(ValidationError):
        VerifyRequest.model_validate({
            "grantor": "C사",
            "grantee": "T사",
            "ipId": 1,
            "fileName": "a.pdf",
            "filePath": "contracts/a.pdf",
            "fileHash": "abc",
            "rights": [],
        })


def test_conflict_report_json_keys_are_recursively_camelized():
    report = camelize_json_keys({
        "constraint_name": "no_exclusive_overlap",
        "exception_detail": "detail",
        "conflicts": [{
            "incoming": {
                "legal_right": "TRANSMISSION",
                "exploitation_mode": "SVOD",
            },
            "existing_grant_id": 4512,
            "existing_contract_id": 87,
            "overlap_period": "[2027-07-01,2028-07-01)",
            "legal_right_relation": "same",
            "exploitation_mode_relation": "same",
            "blocking_layer": "no_exclusive_overlap",
        }],
    })

    assert report["constraintName"] == "no_exclusive_overlap"
    assert report["exceptionDetail"] == "detail"
    conflict = report["conflicts"][0]
    assert conflict["incoming"]["legalRight"] == "TRANSMISSION"
    assert conflict["incoming"]["exploitationMode"] == "SVOD"
    assert conflict["existingGrantId"] == 4512
    assert conflict["existingContractId"] == 87
    assert conflict["overlapPeriod"] == "[2027-07-01,2028-07-01)"
    assert conflict["legalRightRelation"] == "same"
    assert conflict["exploitationModeRelation"] == "same"
    assert conflict["blockingLayer"] == "no_exclusive_overlap"


def test_chunk_page_range_is_validated_and_aliased():
    chunk = ChunkIn.model_validate({
        "chunkText": "제8조",
        "pageStart": 3,
        "pageEnd": 4,
    })
    assert chunk.model_dump(by_alias=True)["pageStart"] == 3
    with pytest.raises(ValidationError):
        ChunkIn.model_validate({"chunkText": "제8조", "pageStart": 4, "pageEnd": 3})


def test_search_period_and_limit_are_validated():
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"limit": 0})
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({
            "filters": {"period": {"start": "2027-01-02", "end": "2027-01-01"}}
        })


def test_ip_asset_scope_fields_are_validated_and_aliased():
    with pytest.raises(ValidationError):
        AssetIn.model_validate({"scopeType": "SERIES_ALL", "episodeNo": 1})
    body = IpOut(
        ip_id=12,
        title="겨울의 신호",
        kind="DRAMA",
        activity="active",
    ).model_dump(by_alias=True, mode="json")
    assert body["ipId"] == 12
    assert body["contractCount"] == 0


def test_ip_search_metadata_is_aliased():
    body = IpListItem(
        ip_id=12,
        title="겨울왕국",
        kind="ANIMATION",
        activity="active",
        score=0.98,
        matched_on="title",
        matched_text="겨울왕국",
    ).model_dump(by_alias=True, mode="json")
    assert body["score"] == 0.98
    assert body["matchedOn"] == "title"
    assert body["matchedText"] == "겨울왕국"

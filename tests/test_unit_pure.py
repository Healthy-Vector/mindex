"""DB 없이 도는 순수 단위 테스트 (P2-DB 정렬 후)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.auth import PinRequest, TokenResponse
from app.schemas.common import camelize_json_keys
from app.schemas.contracts import ChunkIn, VerifyRequest
from app.schemas.ips import AssetIn, AssetPatch, IpListItem, IpOut
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
    # draft 는 기간과 무관하게 계약 전 — signed_date 는 상태 판정에 쓰지 않는다.
    assert compute_display(
        date(2027, 1, 1), date(2028, 1, 1), today, contract_status="draft"
    ) == ("PRE_CONTRACT", None, None)
    assert compute_display(None, None, today) == (None, None, None)
    assert compute_display(date(2026, 1, 1), None, today) == (None, None, None)

    # 유효기간 전 — daysToExpiry 는 시작일까지 남은 일수(양수), tier 없음.
    assert compute_display(date(2027, 1, 1), date(2028, 1, 1), today) == (
        "BEFORE_TERM", 129, None,
    )
    # 기간 만료 — daysToExpiry 는 종료일(포함) 이후 경과 일수(음수).
    assert compute_display(date(2024, 1, 1), date(2026, 1, 1), today) == (
        "EXPIRED", -237, None,
    )
    # 기간 중 — 잔여 90일 이상.
    assert compute_display(date(2026, 1, 1), date(2027, 1, 1), today)[0] == "IN_TERM"


def test_display_expiring_tier_boundaries():
    """프론트 lib/contractStatus.js 의 경계와 정확히 일치해야 한다.

    잔여(daysToExpiry) >= 90 이면 IN_TERM, 미만이면 EXPIRING 이고
    tier 는 <=30 → 30, <=60 → 60, 그 외 → 90.
    """
    today = date(2026, 8, 25)
    start = date(2026, 1, 1)

    def at(days_left: int):
        # end_inclusive = max_upper - 1일 이므로 max_upper 는 today + days_left + 1.
        return compute_display(start, today + timedelta(days=days_left + 1), today)

    assert at(91) == ("IN_TERM", 91, None)
    assert at(90) == ("IN_TERM", 90, None)
    assert at(89) == ("EXPIRING", 89, 90)
    assert at(61) == ("EXPIRING", 61, 90)
    assert at(60) == ("EXPIRING", 60, 60)
    assert at(31) == ("EXPIRING", 31, 60)
    assert at(30) == ("EXPIRING", 30, 30)
    assert at(1) == ("EXPIRING", 1, 30)
    # 종료일 당일(잔여 0)까지는 아직 만료가 아니다.
    assert at(0) == ("EXPIRING", 0, 30)


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


def test_search_period_and_pagination_are_validated():
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"page": 0})
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


def test_asset_patch_merges_with_current_row_before_validating():
    """부분 수정은 기존 행과 병합한 뒤에 scope 정합성을 본다.

    보내지 않은 필드는 기존 값이 남고, 명시적 null 은 값을 비운다 —
    둘을 구분하지 못하면 "title 만 고쳤는데 seasonNo 가 지워지는" 사고가 난다.
    """
    current = {
        "scope_type": "SEASON", "title": "시즌 2", "asset_type": "MAIN",
        "season_no": 2, "episode_no": None, "edition_code": None,
    }

    merged = AssetPatch.model_validate({"title": "시즌 II"}).merged_with(current)

    assert merged.title == "시즌 II"
    assert merged.scope_type == "SEASON"
    assert merged.season_no == 2

    cleared = AssetPatch.model_validate(
        {"scopeType": "SERIES_ALL", "seasonNo": None}
    ).merged_with(current)
    assert cleared.scope_type == "SERIES_ALL"
    assert cleared.season_no is None


def test_asset_patch_merge_rejects_scope_mismatch_left_behind():
    """scopeType 만 넓히면 기존 seasonNo/episodeNo 가 남아 DB CHECK 를 때린다.

    DB 까지 내려가 500 으로 새어나가지 않도록 병합 시점에 ValidationError 로 잡는다.
    """
    current = {
        "scope_type": "EPISODE", "title": "1화", "asset_type": "MAIN",
        "season_no": 1, "episode_no": 1, "edition_code": None,
    }

    with pytest.raises(ValidationError):
        AssetPatch.model_validate({"scopeType": "SERIES_ALL"}).merged_with(current)

    with pytest.raises(ValidationError):
        AssetPatch.model_validate({"editionCode": "DC"}).merged_with(current)

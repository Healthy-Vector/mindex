"""P2-DB 정렬 API 통합 테스트 (실 DB 필요). §8 취지 유지."""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

from tests.conftest import requires_db, body
from tests.test_staging_verify_api import worker_payload


@requires_db
def test_verify_leaves_no_rows(client, conn, clean_db):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM rights_grant")
    before = cur.fetchone()[0]
    conn.commit()
    r = client.post("/api/contracts/verify", json=body(clean_db))
    assert r.status_code == 200 and r.json()["batchResult"] in ("APPLIED", "CONFLICTED")
    cur.execute("SELECT count(*) FROM rights_grant")
    conn.commit()
    assert cur.fetchone()[0] == before


@requires_db
def test_confirm_applied(client, clean_db):
    r = client.post("/api/contracts", json=body(clean_db, source_tmpid=None))
    assert r.status_code == 201
    j = r.json()
    assert j["batchResult"] == "APPLIED" and j["hasConflict"] is False
    assert j["contractId"] and j["contractHistoryId"]


def _confirm(client, clean_db, *, start_offset, end_offset, territory):
    """오늘 기준 상대 기간으로 계약 1건을 확정한다.

    territory 를 건마다 다르게 줘야 독점 권리끼리 겹쳐 CONFLICTED 로 빠지지 않는다.
    """
    today = date.today()
    created = client.post(
        "/api/contracts",
        json=body(
            clean_db,
            territory=territory,
            start=(today + timedelta(days=start_offset)).isoformat(),
            end=(today + timedelta(days=end_offset)).isoformat(),
        ),
    )
    assert created.status_code == 201, created.text
    assert created.json()["hasConflict"] is False
    return created.json()["contractId"]


@requires_db
def test_contract_list_filters_by_display_state(client, clean_db):
    today = date.today()
    contract_id = _confirm(
        client, clean_db, start_offset=10, end_offset=365, territory="KR"
    )

    response = client.get(
        "/api/contracts",
        params={"displayStates": "BEFORE_TERM", "include_processing": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["id"] == contract_id
    assert item["displayState"] == "BEFORE_TERM"
    assert item["periodStart"] == (today + timedelta(days=10)).isoformat()
    assert item["periodEnd"] == (today + timedelta(days=365)).isoformat()
    assert item["expiringTier"] is None


@requires_db
def test_contract_list_filters_by_multiple_display_states(client, clean_db):
    before_term = _confirm(
        client, clean_db, start_offset=10, end_offset=365, territory="KR"
    )
    expiring = _confirm(
        client, clean_db, start_offset=-100, end_offset=20, territory="JP"
    )
    _confirm(client, clean_db, start_offset=-400, end_offset=-10, territory="US")

    response = client.get(
        "/api/contracts", params={"displayStates": "before_term, EXPIRING"}
    )

    assert response.status_code == 200
    payload = response.json()
    # 소문자·공백이 섞여도 정규화되고, EXPIRED 1건은 걸러진다.
    assert payload["total"] == 2
    by_id = {item["id"]: item for item in payload["items"]}
    assert set(by_id) == {before_term, expiring}
    assert by_id[before_term]["displayState"] == "BEFORE_TERM"
    assert by_id[expiring]["displayState"] == "EXPIRING"
    # 잔여 20일 → tier 30.
    assert by_id[expiring]["expiringTier"] == 30
    assert by_id[expiring]["daysToExpiry"] == 20


@requires_db
def test_contract_list_rejects_unknown_display_state(client, clean_db):
    response = client.get("/api/contracts", params={"displayStates": "BEFORE_TERM,NOPE"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@requires_db
def test_contract_detail_exposes_expiring_tier(client, clean_db):
    contract_id = _confirm(
        client, clean_db, start_offset=-100, end_offset=45, territory="KR"
    )
    token = client.post("/api/auth/pin", json={"pin": "1234"}).json()["sessionToken"]

    response = client.get(
        f"/api/contracts/{contract_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["displayState"] == "EXPIRING"
    assert detail["daysToExpiry"] == 45
    assert detail["expiringTier"] == 60


@requires_db
def test_confirm_conflict_reports_p2_shape(client, clean_db):
    # 1건 확정(독점) → 겹치는 2번째 확정은 CONFLICTED + P2 conflict_report
    assert client.post("/api/contracts", json=body(clean_db)).json()["batchResult"] == "APPLIED"
    r2 = client.post("/api/contracts", json=body(clean_db, start="2027-06-01", end="2028-06-30"))
    assert r2.status_code == 201
    j = r2.json()
    assert j["hasConflict"] is True and j["batchResult"] == "CONFLICTED"
    rep = j["conflictReport"]
    assert rep and "conflicts" in rep and rep["conflicts"][0]["incoming"]["legalRight"] == "TRANSMISSION"
    assert "blockingLayer" in rep["conflicts"][0]


@requires_db
def test_ip_search_ranks_title_inside_ocr_text_first(client, conn, clean_db):
    cur = conn.cursor()
    cur.execute("INSERT INTO ip(title, kind) VALUES ('겨울왕국', 'ANIMATION')")
    cur.execute("INSERT INTO ip(title, kind) VALUES ('겨울 정원', 'DRAMA')")
    conn.commit()

    response = client.get("/api/ips", params={"q": "겨울왕국 시즌2"})

    assert response.status_code == 200
    result = response.json()
    assert result["items"][0]["title"] == "겨울왕국"
    assert result["items"][0]["matchedOn"] == "title"
    assert result["items"][0]["matchedText"] == "겨울왕국"
    assert result["items"][0]["score"] >= 0.98

    match_response = client.get("/api/ips/match", params={"q": "겨울왕국 시즌2"})
    assert match_response.status_code == 200
    match = match_response.json()["matches"][0]
    assert match["title"] == "겨울왕국"
    assert match["matchedOn"] == "title"
    assert match["score"] >= 0.98


@requires_db
def test_cancel_frees(client, conn, clean_db):
    cid = client.post("/api/contracts", json=body(clean_db)).json()["contractId"]
    token = client.post("/api/auth/pin", json={"pin": "1234"}).json()["sessionToken"]
    rc = client.post(f"/api/contracts/{cid}/cancel", headers={"Authorization": f"Bearer {token}"})
    assert rc.status_code == 200
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM rights_grant WHERE contract_id=%s AND status='active'", (cid,))
    conn.commit()
    assert cur.fetchone()[0] == 0


@requires_db
def test_detail_without_session_401(client, clean_db):
    cid = client.post("/api/contracts", json=body(clean_db)).json()["contractId"]
    assert client.get(f"/api/contracts/{cid}").status_code == 401


@requires_db
def test_apac_expands(client, conn, clean_db):
    r = client.post("/api/contracts/verify", json=body(clean_db, territory="APAC"))
    assert r.status_code == 200


@requires_db
def test_refs_return_two_taxonomy_axes(client):
    r = client.get("/api/refs?types=legalRight,exploitationMode")
    assert r.status_code == 200
    assert r.json()["legalRights"]
    assert r.json()["exploitationModes"]
    assert "rightsType" not in r.json()


@requires_db
def test_ip_activity_patch_is_part_of_update_api(client, clean_db):
    r = client.patch(f"/api/ips/{clean_db['ip_id']}", json={"activity": "deactive"})
    assert r.status_code == 200
    assert r.json()["activity"] == "deactive"
    assert r.json()["ipId"] == clean_db["ip_id"]
    assert client.get("/api/ips").json()["total"] == 0


@requires_db
def test_get_ip_detail_includes_inactive_ip(client, clean_db):
    ip_id = clean_db["ip_id"]
    assert client.patch(f"/api/ips/{ip_id}", json={"activity": "deactive"}).status_code == 200

    response = client.get(f"/api/ips/{ip_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ipId"] == ip_id
    assert payload["activity"] == "deactive"
    assert payload["assets"]


@requires_db
def test_get_ip_detail_returns_404_and_match_route_stays_reachable(client, clean_db):
    assert client.get("/api/ips/999999").status_code == 404
    match = client.get("/api/ips/match", params={"q": "겨울"})
    assert match.status_code == 200
    assert match.json()["matches"][0]["ipId"] == clean_db["ip_id"]


@requires_db
def test_internal_overlap_is_rejected(client, clean_db):
    payload = body(clean_db)
    payload["rights"].append(dict(payload["rights"][0]))
    r = client.post("/api/contracts/verify", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"


@requires_db
def test_source_tmpid_must_be_done_and_cannot_be_reused(client, conn, clean_db):
    tmpid = uuid.uuid4()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO staging.pdf_blob(tmpid,data,filename) VALUES (%s,%s,%s)",
        (str(tmpid), b"pdf", "a.pdf"),
    )
    cur.execute(
        "INSERT INTO staging.extract_job(tmpid,status) VALUES (%s,'DONE')",
        (str(tmpid),),
    )
    cur.execute(
        "INSERT INTO staging.extract_result(tmpid,payload) VALUES (%s,%s::jsonb)",
        (
            str(tmpid),
            json.dumps(worker_payload(), ensure_ascii=False),
        ),
    )
    conn.commit()

    first = client.post("/api/contracts", json=body(clean_db, source_tmpid=tmpid))
    assert first.status_code == 201
    cur.execute("SELECT consumed_at FROM staging.extract_job WHERE tmpid=%s", (str(tmpid),))
    assert cur.fetchone()[0] is not None
    again = client.post("/api/contracts", json=body(clean_db, source_tmpid=tmpid))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_CONFIRMED"


# ── 18. 권리 대상(content_asset) 행 단위 관리 ────────────────────────────
# 전체 교체가 아니라 행 단위로 여는 이유는 §18 참고 — 빈 배열 하나로 기존 자산을
# 통째로 지우는 사고를 구조적으로 막는다.


def _new_ip(client, title):
    created = client.post("/api/ips", json={"title": title, "kind": "DRAMA"})
    assert created.status_code == 201, created.text
    return created.json()


@requires_db
def test_create_ip_asset_appends_row(client, clean_db):
    ip_id = clean_db["ip_id"]
    response = client.post(
        f"/api/ips/{ip_id}/assets",
        json={"scopeType": "SEASON", "title": "시즌 2", "seasonNo": 2},
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["contentAssetId"] > 0
    assert created["scopeType"] == "SEASON" and created["seasonNo"] == 2

    # 기존 SERIES_ALL 이 지워지지 않고 옆에 추가된다.
    assets = client.get(f"/api/ips/{ip_id}").json()["assets"]
    assert {a["contentAssetId"] for a in assets} == {clean_db["asset_id"], created["contentAssetId"]}


@requires_db
def test_patch_ip_asset_updates_only_sent_fields(client, clean_db):
    ip_id = clean_db["ip_id"]
    asset_id = client.post(
        f"/api/ips/{ip_id}/assets",
        json={"scopeType": "SEASON", "title": "시즌 2", "seasonNo": 2},
    ).json()["contentAssetId"]

    response = client.patch(f"/api/ips/{ip_id}/assets/{asset_id}", json={"title": "시즌 II"})

    assert response.status_code == 200, response.text
    patched = response.json()
    assert patched["title"] == "시즌 II"
    assert patched["scopeType"] == "SEASON" and patched["seasonNo"] == 2


@requires_db
def test_ip_asset_must_belong_to_path_ip(client, clean_db):
    """asset_id 만 갈아끼워 남의 IP 자산을 건드리는 경로(IDOR)를 막는다."""
    other = _new_ip(client, "여름의 신호")
    other_asset_id = other["assets"][0]["contentAssetId"]

    patched = client.patch(
        f"/api/ips/{clean_db['ip_id']}/assets/{other_asset_id}", json={"title": "가로채기"}
    )
    assert patched.status_code == 404
    assert patched.json()["error"]["code"] == "NOT_FOUND"

    deleted = client.delete(f"/api/ips/{clean_db['ip_id']}/assets/{other_asset_id}")
    assert deleted.status_code == 404

    # 남의 자산은 그대로다.
    assert client.get(f"/api/ips/{other['ipId']}").json()["assets"][0]["title"] == other["assets"][0]["title"]


@requires_db
def test_asset_referenced_by_rights_grant_is_read_only(client, clean_db):
    """이미 판정된 권리의 대상 범위가 사후에 바뀌면 판정 결과가 거짓이 된다."""
    assert client.post("/api/contracts", json=body(clean_db)).status_code == 201
    ip_id, asset_id = clean_db["ip_id"], clean_db["asset_id"]

    patched = client.patch(f"/api/ips/{ip_id}/assets/{asset_id}", json={"title": "바꾸기"})
    assert patched.status_code == 409
    assert patched.json()["error"]["code"] == "ASSET_IN_USE"
    assert patched.json()["error"]["details"]["rightsGrantCount"] >= 1

    deleted = client.delete(f"/api/ips/{ip_id}/assets/{asset_id}")
    assert deleted.status_code == 409
    assert deleted.json()["error"]["code"] == "ASSET_IN_USE"


@requires_db
def test_last_asset_cannot_be_deleted(client, clean_db):
    """마지막 행이 사라지면 save_rights_batch() 의 기본 자산 조회가 깨진다."""
    ip_id, asset_id = clean_db["ip_id"], clean_db["asset_id"]

    blocked = client.delete(f"/api/ips/{ip_id}/assets/{asset_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["details"].get("assetCount") == 1

    # 한 행 더 만들면 지울 수 있다.
    extra = client.post(f"/api/ips/{ip_id}/assets", json={"scopeType": "SERIES_ALL"}).json()
    assert client.delete(f"/api/ips/{ip_id}/assets/{extra['contentAssetId']}").status_code == 204
    assert len(client.get(f"/api/ips/{ip_id}").json()["assets"]) == 1


@requires_db
def test_patch_asset_scope_merge_violation_is_400(client, clean_db):
    """scopeType 만 넓히면 기존 seasonNo 가 남아 DB CHECK 위반 — 500 이 아니라 400 이다."""
    ip_id = clean_db["ip_id"]
    asset_id = client.post(
        f"/api/ips/{ip_id}/assets",
        json={"scopeType": "EPISODE", "seasonNo": 1, "episodeNo": 1},
    ).json()["contentAssetId"]

    response = client.patch(f"/api/ips/{ip_id}/assets/{asset_id}", json={"scopeType": "SERIES_ALL"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# ── D-41: 비활성 IP는 새 계약을 만들 수 없다 ──────────────────
def _deactivate(client, ip_id):
    r = client.patch(f"/api/ips/{ip_id}", json={"activity": "deactive"})
    assert r.status_code == 200, r.text


@requires_db
def test_verify_rejects_new_contract_for_inactive_ip(client, clean_db):
    """contractId 없이(=새 계약) 비활성 IP를 걸면 검증 단계에서부터 막힌다."""
    _deactivate(client, clean_db["ip_id"])

    response = client.post("/api/contracts/verify", json=body(clean_db))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IP_INACTIVE"


@requires_db
def test_confirm_rejects_new_contract_for_inactive_ip(client, clean_db):
    """확정도 같은 규칙 — 새 계약 행 생성은 활성 IP가 필요하다."""
    _deactivate(client, clean_db["ip_id"])

    response = client.post("/api/contracts", json=body(clean_db))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IP_INACTIVE"


@requires_db
def test_renewal_of_inactive_ip_is_also_rejected(client, clean_db):
    """연장(mode=new)도 contractId가 없는 신규 계약 행이므로 동일하게 막힌다.

    화면은 연장을 "법적으로 별개인 신규 계약"으로 취급해 contractId를 보내지
    않는다(ContractDetailContent.jsx) — 서버 쪽에서 보면 이미 서명된 계약이
    있었다는 사실과 무관하게 그냥 또 하나의 신규 계약 요청이다.
    """
    signed = client.post("/api/contracts", json=body(clean_db))
    assert signed.status_code == 201, signed.text

    _deactivate(client, clean_db["ip_id"])

    renewal = client.post(
        "/api/contracts/verify",
        json=body(clean_db, start="2028-01-01", end="2028-12-31"),
    )

    assert renewal.status_code == 409
    assert renewal.json()["error"]["code"] == "IP_INACTIVE"


@requires_db
def test_adding_version_to_existing_contract_ignores_ip_activity(client, clean_db):
    """contractId가 있으면(기존 계약에 버전 추가) activity를 다시 보지 않는다.

    그 IP 연결은 계약이 처음 만들어질 때 이미 유효했다 — 이후 IP가
    비활성화됐다고 기존 계약의 버전 추가(draft 추가·최종본 등록)까지 막히면
    안 된다.
    """
    draft = client.post(
        "/api/contracts/verify",
        json=body(clean_db, exclusivity="non_exclusive"),
    )
    assert draft.status_code == 200
    # verify는 아무것도 남기지 않으므로 실제 계약 행은 confirm으로 만든다.
    created = client.post(
        "/api/contracts",
        json={**body(clean_db, exclusivity="non_exclusive"), "documentKind": "draft"},
    )
    assert created.status_code == 201, created.text
    contract_id = created.json()["contractId"]

    _deactivate(client, clean_db["ip_id"])

    revision = client.post(
        "/api/contracts",
        json={
            **body(clean_db, exclusivity="non_exclusive", start="2029-01-01", end="2029-12-31"),
            "contractId": contract_id,
            "documentKind": "final",
        },
    )

    assert revision.status_code == 201, revision.text
    assert revision.json()["batchResult"] in {"APPLIED", "CONFLICTED"}


@requires_db
def test_active_ip_new_contract_still_works(client, clean_db):
    """활성 IP는 그대로 통과한다 — 회귀 확인용."""
    response = client.post("/api/contracts/verify", json=body(clean_db))
    assert response.status_code == 200

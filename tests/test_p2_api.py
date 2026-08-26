"""P2-DB 정렬 API 통합 테스트 (실 DB 필요). §8 취지 유지."""
from __future__ import annotations

import json
import uuid

from tests.conftest import requires_db, body


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
        (str(tmpid), json.dumps({"rights": []})),
    )
    conn.commit()

    first = client.post("/api/contracts", json=body(clean_db, source_tmpid=tmpid))
    assert first.status_code == 201
    cur.execute("SELECT consumed_at FROM staging.extract_job WHERE tmpid=%s", (str(tmpid),))
    assert cur.fetchone()[0] is not None
    again = client.post("/api/contracts", json=body(clean_db, source_tmpid=tmpid))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_CONFIRMED"

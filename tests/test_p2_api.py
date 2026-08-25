"""P2-DB 정렬 API 통합 테스트 (실 DB 필요). §8 취지 유지."""
from __future__ import annotations

import uuid

from tests.conftest import requires_db, body


@requires_db
def test_verify_leaves_no_rows(client, conn, clean_db):
    cur = conn.cursor(); cur.execute("SELECT count(*) FROM rights_grant"); before = cur.fetchone()[0]; conn.commit()
    r = client.post("/api/contracts/verify", json=body(clean_db))
    assert r.status_code == 200 and r.json()["batchResult"] in ("APPLIED", "CONFLICTED")
    cur.execute("SELECT count(*) FROM rights_grant"); conn.commit()
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
    assert rep and "conflicts" in rep and rep["conflicts"][0]["incoming"]["legal_right"] == "TRANSMISSION"
    assert "blocking_layer" in rep["conflicts"][0]


@requires_db
def test_cancel_frees(client, conn, clean_db):
    cid = client.post("/api/contracts", json=body(clean_db)).json()["contractId"]
    token = client.post("/api/auth/pin", json={"teamId": clean_db["team_id"], "pin": "1234"}).json()["token"]
    rc = client.post(f"/api/contracts/{cid}/cancel", headers={"Authorization": f"Bearer {token}"})
    assert rc.status_code == 200
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM rights_grant WHERE contract_id=%s AND status='active'", (cid,)); conn.commit()
    assert cur.fetchone()[0] == 0


@requires_db
def test_detail_without_session_401(client, clean_db):
    cid = client.post("/api/contracts", json=body(clean_db)).json()["contractId"]
    assert client.get(f"/api/contracts/{cid}").status_code == 401


@requires_db
def test_apac_expands(client, conn, clean_db):
    r = client.post("/api/contracts/verify", json=body(clean_db, territory="APAC"))
    assert r.status_code == 200

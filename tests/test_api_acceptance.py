"""§8.2 API 동작 (A1~A12). 실 DB + TestClient 필요."""
from __future__ import annotations

import uuid

from tests.conftest import requires_db, insert_grant, make_verify_body


def _seed_existing_exclusive(conn, clean_db):
    """clean_db 팀에 JP·SVOD·2024~2028 독점 active 권리 1건을 심는다."""
    cur = conn.cursor()
    insert_grant(
        cur,
        {
            "team_id": clean_db["team_id"], "asset_id": clean_db["asset_id"],
            "contract_a": clean_db["contract_a"], "history_a": clean_db["history_a"],
        },
        "A", territory="JP", rights_type="SVOD",
        period="[2024-01-01,2028-01-01)", exclusivity="exclusive",
    )
    conn.commit()


@requires_db
def test_A1_verify_leaves_no_rows(client, conn, clean_db):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM master.rights_grant")
    before = cur.fetchone()[0]
    conn.commit()
    r = client.post("/api/contracts/verify", json=make_verify_body(clean_db))
    assert r.status_code == 200
    cur.execute("SELECT count(*) FROM master.rights_grant")
    conn.commit()
    assert cur.fetchone()[0] == before


@requires_db
def test_A2_verify_conflict_200(client, conn, clean_db):
    _seed_existing_exclusive(conn, clean_db)
    r = client.post("/api/contracts/verify", json=make_verify_body(clean_db))
    assert r.status_code == 200
    body = r.json()
    assert body["hasConflict"] is True
    assert body["conflicts"][0]["existing"]["rightsGrantId"]


@requires_db
def test_A3_confirm_conflict_201(client, conn, clean_db):
    _seed_existing_exclusive(conn, clean_db)
    tmpid = str(uuid.uuid4())
    r = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid))
    assert r.status_code == 201
    body = r.json()
    assert body["historyStatus"] == "conflicted"
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM master.rights_grant WHERE status='conflicted'")
    conn.commit()
    assert cur.fetchone()[0] >= 1


@requires_db
def test_A4_confirm_conflict_current_history_not_updated(client, conn, clean_db):
    _seed_existing_exclusive(conn, clean_db)
    tmpid = str(uuid.uuid4())
    r = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid))
    cid = r.json()["contractId"]
    cur = conn.cursor()
    cur.execute("SELECT current_history_id FROM master.contract WHERE id=%s", (cid,))
    conn.commit()
    assert cur.fetchone()[0] is None


@requires_db
def test_A5_confirm_success_clears_staging(client, conn, clean_db):
    tmpid = str(uuid.uuid4())
    cur = conn.cursor()
    cur.execute("INSERT INTO staging.pdf_blob(tmpid,data) VALUES (%s,%s)", (tmpid, b"x"))
    cur.execute("INSERT INTO staging.extract_job(tmpid,status) VALUES (%s,'DONE')", (tmpid,))
    cur.execute("INSERT INTO staging.extract_result(tmpid,payload) VALUES (%s,'{}')", (tmpid,))
    conn.commit()
    r = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid))
    assert r.status_code == 201
    for t in ("pdf_blob", "extract_job", "extract_result"):
        cur.execute(f"SELECT count(*) FROM staging.{t} WHERE tmpid=%s", (tmpid,))
        assert cur.fetchone()[0] == 0
    conn.commit()


@requires_db
def test_A6_double_confirm_same_tmpid_409(client, clean_db):
    tmpid = str(uuid.uuid4())
    r1 = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid))
    assert r1.status_code == 201
    r2 = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid))
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "ALREADY_CONFIRMED"


@requires_db
def test_A7_revision_supersedes(client, conn, clean_db):
    tmpid1 = str(uuid.uuid4())
    r1 = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid1))
    cid = r1.json()["contractId"]
    tmpid2 = str(uuid.uuid4())
    body = make_verify_body(clean_db, mode="revision", source_tmpid=tmpid2)
    body["contractId"] = cid
    r2 = client.post("/api/contracts", json=body)
    assert r2.status_code == 201
    cur = conn.cursor()
    cur.execute(
        "SELECT terminated_reason FROM master.rights_grant "
        "WHERE contract_id=%s AND status='terminated'", (cid,)
    )
    conn.commit()
    reasons = [row[0] for row in cur.fetchall()]
    assert "superseded" in reasons


@requires_db
def test_A8_cancel_frees_exclude(client, conn, clean_db):
    # 확정 → 취소 → 같은 조건 재확정이 충돌 없이 성공
    t1 = str(uuid.uuid4())
    r1 = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=t1))
    cid = r1.json()["contractId"]
    token = client.post("/api/auth/pin", json={"teamId": clean_db["team_id"], "pin": "1234"}).json()["token"]
    rc = client.post(f"/api/contracts/{cid}/cancel", json={"reason": "cancelled"},
                     headers={"Authorization": f"Bearer {token}"})
    assert rc.status_code == 200
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM master.rights_grant WHERE contract_id=%s AND status='active'", (cid,))
    conn.commit()
    assert cur.fetchone()[0] == 0
    t2 = str(uuid.uuid4())
    r2 = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=t2))
    assert r2.json()["hasConflict"] is False


@requires_db
def test_A9_detail_without_session_401(client, clean_db):
    r = client.get(f"/api/contracts/{clean_db['contract_a']}")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "SESSION_EXPIRED"


@requires_db
def test_A10_list_without_session_200(client, clean_db):
    r = client.get("/api/contracts")
    assert r.status_code == 200


@requires_db
def test_A11_detail_conflict_same_schema(client, conn, clean_db):
    _seed_existing_exclusive(conn, clean_db)
    tmpid = str(uuid.uuid4())
    cr = client.post("/api/contracts", json=make_verify_body(clean_db, source_tmpid=tmpid))
    cid = cr.json()["contractId"]
    token = client.post("/api/auth/pin", json={"teamId": clean_db["team_id"], "pin": "1234"}).json()["token"]
    r = client.get(f"/api/contracts/{cid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["hasConflict"] is True
    assert body["conflictReport"] is not None
    assert "rights" in body and "history" in body


@requires_db
def test_A12_apac_expands_checked_rows(client, conn, clean_db):
    body = make_verify_body(clean_db, territory="APAC")
    r = client.post("/api/contracts/verify", json=body)
    assert r.status_code == 200
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM master.territory_group_country WHERE group_code='APAC'")
    conn.commit()
    apac_n = cur.fetchone()[0]
    assert r.json()["checkedRows"] == apac_n

"""verify/confirm의 staging 병합 경로와 세대별 조회 API 테스트 (D-34).

DB가 필요하다. `@requires_db`가 붙은 항목은 PostgreSQL 없이는 스킵된다.
"""
from __future__ import annotations

import json
import uuid

import pytest

from tests.conftest import requires_db


PDF_BYTES = b"%PDF-1.4 staging test\n"


def worker_payload(
    *,
    title="겨울의 신호",
    start="2027-01-01",
    end="2027-12-31",
    territory="KR",
):
    """contract-extraction-worker가 staging.extract_result.payload에 남기는 모양."""
    quote = "제8조 (권리의 부여) 본 계약에 따라 …"
    return {
        "raw": {
            "schema_version": "1.0",
            "document": {"language": "KO"},
            "contract": {
                "contract_title": {
                    "field_status": "PRESENT_EXPLICIT",
                    "value": title,
                    "raw_expression": title,
                },
                "agreement_date": {
                    "field_status": "PRESENT_EXPLICIT",
                    "value": "2026-12-01",
                    "raw_expression": "2026-12-01",
                },
                "parties": [
                    {
                        "role": "GRANTOR",
                        "name": "해솔미디어",
                        "field_status": "PRESENT_EXPLICIT",
                        "raw_expression": "해솔미디어",
                    },
                    {
                        "role": "GRANTEE",
                        "name": "웨이브플랫폼",
                        "field_status": "PRESENT_EXPLICIT",
                        "raw_expression": "웨이브플랫폼",
                    },
                ],
                "rights_grants": [
                    {
                        "grant_ref": "grant-1",
                        "content": {
                            "field_status": "PRESENT_EXPLICIT",
                            "subjects": [
                                {
                                    "subject_type": "CONTENT",
                                    "title": title,
                                    "scope_type": "SERIES",
                                    "relationship_type": None,
                                }
                            ],
                            "raw_expression": title,
                        },
                        "legal_right": {
                            "field_status": "PRESENT_EXPLICIT",
                            "values": ["INTERACTIVE_TRANSMISSION"],
                            "raw_expression": quote,
                        },
                        "exploitation_mode": {
                            "field_status": "PRESENT_EXPLICIT",
                            "values": ["SVOD"],
                            "raw_expression": quote,
                        },
                        "territory": {
                            "field_status": "PRESENT_EXPLICIT",
                            "values": [territory],
                            "raw_expression": quote,
                        },
                        "license_period": {
                            "field_status": "PRESENT_EXPLICIT",
                            "start": start,
                            "end": end,
                            "raw_expression": quote,
                        },
                        "exclusivity": {
                            "field_status": "PRESENT_EXPLICIT",
                            "value": "EXCLUSIVE",
                            "raw_expression": quote,
                        },
                        "authority_constraints": None,
                        "scope_modifiers": [],
                    }
                ],
                "payments": [],
                "evidence": [],
            },
        },
        "validation": {"confidence": 0.91},
    }


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    """계약 원본 저장소를 테스트 임시 디렉터리로 돌린다."""
    monkeypatch.setattr("app.services.storage.storage_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def done_job(conn):
    """DONE 상태의 staging 작업 한 벌(pdf_blob + extract_job + extract_result)."""

    def _make(payload=None):
        tmpid = str(uuid.uuid4())
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO staging.pdf_blob (tmpid, data, filename, byte_size) "
            "VALUES (%s::uuid, %s, %s, %s)",
            (tmpid, PDF_BYTES, "계약서.pdf", len(PDF_BYTES)),
        )
        cur.execute(
            "INSERT INTO staging.extract_job (tmpid, status) VALUES (%s::uuid, 'DONE')",
            (tmpid,),
        )
        cur.execute(
            "INSERT INTO staging.extract_result (tmpid, payload) VALUES (%s::uuid, %s::jsonb)",
            (tmpid, json.dumps(payload or worker_payload(), ensure_ascii=False)),
        )
        conn.commit()
        return tmpid

    return _make


def stored_payload(conn, tmpid):
    cur = conn.cursor()
    cur.execute("SELECT payload FROM staging.extract_result WHERE tmpid=%s::uuid", (tmpid,))
    return cur.fetchone()[0]


def session_token(client):
    return client.post("/api/auth/pin", json={"pin": "1234"}).json()["sessionToken"]


# ── ⑥·⑦ verify가 staging에 반영하고 저장된 값으로 판정한다 ────
@requires_db
def test_verify_persists_edit_and_judges_stored_value(client, clean_db, conn, done_job):
    tmpid = done_job()

    response = client.post(
        "/api/contracts/verify",
        json={
            "tmpId": tmpid,
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "patch": {"contractInfo": {"title": "사용자가 고친 제목"}},
        },
    )

    assert response.status_code == 200
    assert response.json()["batchResult"] in {"APPLIED", "CONFLICTED"}

    payload = stored_payload(conn, tmpid)
    assert payload["edited"]["contractInfo"]["title"] == "사용자가 고친 제목"
    # 워커 원본은 그대로 남는다 — 덮어쓰지 않는다.
    assert payload["raw"]["contract"]["contract_title"]["value"] == "겨울의 신호"


@requires_db
def test_verify_accumulates_patches(client, clean_db, conn, done_job):
    """재검증은 이전 수정본 위에 얹힌다."""
    tmpid = done_job()
    base = {
        "tmpId": tmpid,
        "grantor": "해솔미디어",
        "grantee": "웨이브플랫폼",
        "ipId": clean_db["ip_id"],
    }
    client.post("/api/contracts/verify", json={**base, "patch": {"contractInfo": {"title": "1차"}}})
    client.post(
        "/api/contracts/verify", json={**base, "patch": {"contractInfo": {"currency": "USD"}}}
    )

    edited = stored_payload(conn, tmpid)["edited"]
    assert edited["contractInfo"]["title"] == "1차"
    assert edited["contractInfo"]["currency"] == "USD"


@requires_db
def test_verify_rejects_unknown_tmpid(client, clean_db):
    response = client.post(
        "/api/contracts/verify",
        json={
            "tmpId": str(uuid.uuid4()),
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXTRACT_NOT_READY"


def test_verify_rejects_patch_without_tmpid(client):
    """patch는 staging 경로 전용이다. DB 없이도 스키마 단계에서 걸린다."""
    response = client.post(
        "/api/contracts/verify",
        json={"grantor": "A", "grantee": "B", "patch": {"contractInfo": {}}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@requires_db
def test_extract_polling_returns_edited(client, clean_db, conn, done_job):
    tmpid = done_job()
    client.post(
        "/api/contracts/verify",
        json={
            "tmpId": tmpid,
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "patch": {"contractInfo": {"title": "고친 제목"}},
        },
    )

    result = client.get(f"/api/extract/{tmpid}").json()["result"]
    assert result["contractInfo"]["title"] == "고친 제목"
    # 후보는 저장된 값이 아니라 조회 시점에 다시 뽑는다.
    assert "ipCandidates" in result


# ── ⑧ 확정이 staging 값을 읽어 저장하고 원본을 옮긴다 ─────────
@requires_db
def test_confirm_reads_staging_and_stores_pdf(client, clean_db, conn, done_job, storage_dir):
    tmpid = done_job()
    client.post(
        "/api/contracts/verify",
        json={
            "tmpId": tmpid,
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
        },
    )

    # rights를 보내지 않는다 — 서버가 staging에서 읽어 채운다(B안).
    response = client.post(
        "/api/contracts",
        json={
            "tmpId": tmpid,
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    )

    assert response.status_code == 201, response.text
    saved = response.json()
    contract_id, history_id = saved["contractId"], saved["contractHistoryId"]

    cur = conn.cursor()
    cur.execute(
        "SELECT file_path, file_name, file_hash FROM contract_history WHERE id=%s",
        (history_id,),
    )
    file_path, file_name, file_hash = cur.fetchone()

    # 경로는 서버가 정한다 — 클라이언트가 보낸 값이 아니다.
    assert file_path == f"{contract_id}/{history_id}.pdf"
    assert file_name == "계약서.pdf"
    assert len(file_hash) == 64
    assert (storage_dir / file_path).read_bytes() == PDF_BYTES


@requires_db
def test_confirm_ignores_client_supplied_file_path(client, clean_db, conn, done_job, storage_dir):
    """staging 경로에서는 클라이언트가 filePath를 넣어도 무시된다."""
    tmpid = done_job()
    response = client.post(
        "/api/contracts",
        json={
            "tmpId": tmpid,
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "filePath": "/etc/passwd",
            "fileHash": "deadbeef",
            "documentKind": "final",
        },
    )
    assert response.status_code == 201, response.text
    history_id = response.json()["contractHistoryId"]

    cur = conn.cursor()
    cur.execute("SELECT file_path FROM contract_history WHERE id=%s", (history_id,))
    assert cur.fetchone()[0] != "/etc/passwd"


# ── 9번 세대별 원본 PDF ───────────────────────────────────────
@requires_db
def test_file_endpoint_serves_requested_version(client, clean_db, conn, done_job, storage_dir):
    tmpid = done_job()
    saved = client.post(
        "/api/contracts",
        json={
            "tmpId": tmpid,
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    ).json()
    token = session_token(client)

    response = client.get(
        f"/api/contracts/{saved['contractId']}/file",
        params={"historyId": saved["contractHistoryId"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.content == PDF_BYTES


@requires_db
def test_file_endpoint_rejects_history_of_other_contract(
    client, clean_db, conn, done_job, storage_dir
):
    """historyId만 갈아끼워 남의 계약 원본을 받아갈 수 없다."""
    first = client.post(
        "/api/contracts",
        json={
            "tmpId": done_job(),
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    ).json()
    second = client.post(
        "/api/contracts",
        json={
            "tmpId": done_job(worker_payload(territory="JP")),
            "grantor": "해솔미디어",
            "grantee": "다른상대",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    ).json()
    token = session_token(client)

    response = client.get(
        f"/api/contracts/{first['contractId']}/file",
        params={"historyId": second["contractHistoryId"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_SOURCE_FILE"


@requires_db
def test_file_endpoint_rejects_path_outside_storage(client, clean_db, conn, storage_dir):
    """예전 자유 문자열 경로(절대 경로)는 저장소 밖이라 거부된다 — 임의 파일 읽기 차단."""
    outside = storage_dir.parent / "secret.env"
    outside.write_bytes(b"SECRET=1")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contract (grantor, grantee) VALUES ('A','B') RETURNING id"
    )
    contract_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO contract_history "
        "  (contract_id, version, status, file_name, file_path, file_hash) "
        "VALUES (%s, 1, 'applied', 'x.pdf', %s, 'h') RETURNING id",
        (contract_id, str(outside)),
    )
    history_id = cur.fetchone()[0]
    conn.commit()
    token = session_token(client)

    response = client.get(
        f"/api/contracts/{contract_id}/file",
        params={"historyId": history_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


# ── 8번 세대별 상세 ───────────────────────────────────────────
@requires_db
def test_detail_by_history_id_returns_that_generation(
    client, clean_db, conn, done_job, storage_dir
):
    saved = client.post(
        "/api/contracts",
        json={
            "tmpId": done_job(),
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    ).json()
    token = session_token(client)

    detail = client.get(
        f"/api/contracts/{saved['contractId']}",
        params={"historyId": saved["contractHistoryId"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["rights"], "그 세대의 권리가 나와야 한다"


@requires_db
def test_detail_rejects_history_of_other_contract(client, clean_db, conn, done_job, storage_dir):
    first = client.post(
        "/api/contracts",
        json={
            "tmpId": done_job(),
            "grantor": "해솔미디어",
            "grantee": "웨이브플랫폼",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    ).json()
    second = client.post(
        "/api/contracts",
        json={
            "tmpId": done_job(worker_payload(territory="JP")),
            "grantor": "해솔미디어",
            "grantee": "다른상대",
            "ipId": clean_db["ip_id"],
            "documentKind": "final",
        },
    ).json()
    token = session_token(client)

    detail = client.get(
        f"/api/contracts/{first['contractId']}",
        params={"historyId": second["contractHistoryId"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 404

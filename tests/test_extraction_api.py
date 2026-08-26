from __future__ import annotations

import json

from tests.conftest import requires_db


@requires_db
def test_upload_enqueues_pdf_and_returns_queued_job(client, conn, clean_db):
    response = client.post(
        "/api/extract",
        data={"mode": "new"},
        files={"file": ("source.pdf", b"%PDF-1.7 test document", "application/pdf")},
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "QUEUED"
    assert accepted["filename"] == "source.pdf"
    assert accepted["byteSize"] == len(b"%PDF-1.7 test document")

    cur = conn.cursor()
    cur.execute(
        "SELECT b.data, b.filename, b.byte_size, j.status "
        "FROM staging.pdf_blob b JOIN staging.extract_job j ON j.tmpid=b.tmpid "
        "WHERE b.tmpid=%s",
        (accepted["tmpid"],),
    )
    stored_data, filename, byte_size, status = cur.fetchone()
    assert bytes(stored_data) == b"%PDF-1.7 test document"
    assert (filename, byte_size, status) == ("source.pdf", 22, "QUEUED")

    polled = client.get(f"/api/extract/{accepted['tmpid']}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "QUEUED"
    assert polled.json()["queuePosition"] == 0
    assert polled.json()["result"] is None


@requires_db
def test_done_job_returns_frontend_dto_and_ip_candidates(client, conn, clean_db):
    uploaded = client.post(
        "/api/extract",
        data={"mode": "new"},
        files={"file": ("source.pdf", b"%PDF-1.7 test document", "application/pdf")},
    ).json()
    tmpid = uploaded["tmpid"]

    cur = conn.cursor()
    cur.execute("UPDATE ip SET title='Demo Series' WHERE id=%s", (clean_db["ip_id"],))
    payload = {
        "raw": {
            "document": {"language": "EN"},
            "contract": {
                "contract_title": {
                    "field_status": "PRESENT_EXPLICIT",
                    "value": "Demo Series license",
                },
                "parties": [{"role": "GRANTEE", "name": "Licensee"}],
                "payments": [],
                "rights_grants": [
                    {"content": {"subjects": [{"title": "Demo Series"}]}}
                ],
            },
        },
        "validation": {"confidence": 0.91},
    }
    cur.execute("UPDATE staging.extract_job SET status='DONE' WHERE tmpid=%s", (tmpid,))
    cur.execute(
        "INSERT INTO staging.extract_result(tmpid, payload) VALUES (%s, %s::jsonb)",
        (tmpid, json.dumps(payload)),
    )
    conn.commit()

    response = client.get(f"/api/extract/{tmpid}")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["contractInfo"] == {
        "title": "Demo Series license",
        "counterparty": "Licensee",
        "signedDate": None,
        "lang": "en",
        "amount": None,
        "currency": None,
    }
    assert result["confidence"] == 0.91
    assert result["ipCandidates"][0]["ipId"] == clean_db["ip_id"]
    assert result["ipCandidates"][0]["matchedBy"] == "title"


def test_upload_rejects_non_pdf_without_db():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/extract",
            data={"mode": "new"},
            files={"file": ("source.txt", b"not a PDF", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"

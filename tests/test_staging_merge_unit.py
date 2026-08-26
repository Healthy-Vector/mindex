"""verify/confirm staging 병합 경로의 순수 단위 테스트 (D-34).

DB 없이 도는 것만 둔다. merge patch 적용 규칙과 계약 원본 PDF 저장 경로
해석(경로 탈출 차단 포함)이 대상이다.
"""
from __future__ import annotations

import pytest

from app.services.merge_patch import apply_merge_patch
from app.services.staging_edit import index_chunks
from app.services.storage import (
    resolve_contract_pdf,
    sha256_hex,
    stored_pdf_name,
)


# ── RFC 7386 merge patch ─────────────────────────────────────
def test_merge_patch_replaces_scalar():
    target = {"contractInfo": {"title": "원본", "currency": "KRW"}}
    patched = apply_merge_patch(target, {"contractInfo": {"title": "수정본"}})
    assert patched["contractInfo"] == {"title": "수정본", "currency": "KRW"}


def test_merge_patch_null_deletes_key():
    target = {"contractInfo": {"title": "원본", "amount": 1000}}
    patched = apply_merge_patch(target, {"contractInfo": {"amount": None}})
    assert patched["contractInfo"] == {"title": "원본"}


def test_merge_patch_replaces_array_wholesale():
    """RFC 7386은 배열을 원소 단위로 병합하지 않는다 — rights 전체 교체 규칙의 근거."""
    target = {"rights": [{"legalRight": "TRANSMISSION"}, {"legalRight": "BROADCAST"}]}
    patched = apply_merge_patch(target, {"rights": [{"legalRight": "SVOD"}]})
    assert patched["rights"] == [{"legalRight": "SVOD"}]


def test_merge_patch_does_not_mutate_target():
    target = {"contractInfo": {"title": "원본"}}
    apply_merge_patch(target, {"contractInfo": {"title": "수정본"}})
    assert target["contractInfo"]["title"] == "원본"


def test_merge_patch_adds_missing_branch():
    patched = apply_merge_patch({}, {"contractInfo": {"title": "새 값"}})
    assert patched == {"contractInfo": {"title": "새 값"}}


def test_merge_patch_non_object_patch_replaces_target():
    assert apply_merge_patch({"a": 1}, "치환") == "치환"


# ── 저장 경로 ────────────────────────────────────────────────
def test_stored_pdf_name_is_relative():
    """DB에는 storage_dir 기준 상대 경로만 남긴다 — 디렉터리를 옮겨도 살아남는다."""
    assert stored_pdf_name(101, 344) == "101/344.pdf"


def test_resolve_contract_pdf_returns_path_inside_storage(tmp_path):
    target = tmp_path / "101" / "344.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-1.4\n")
    assert resolve_contract_pdf("101/344.pdf", storage_dir=tmp_path) == target


def test_resolve_contract_pdf_rejects_absolute_path_outside_storage(tmp_path):
    """클라이언트가 넣어둔 절대 경로로 서버 파일을 읽어가는 걸 막는다."""
    outside = tmp_path.parent / "secret.env"
    outside.write_bytes(b"SECRET=1")
    assert resolve_contract_pdf(str(outside), storage_dir=tmp_path) is None


def test_resolve_contract_pdf_rejects_traversal(tmp_path):
    (tmp_path.parent / "secret.env").write_bytes(b"SECRET=1")
    assert resolve_contract_pdf("../secret.env", storage_dir=tmp_path) is None


def test_resolve_contract_pdf_returns_none_when_missing(tmp_path):
    assert resolve_contract_pdf("101/344.pdf", storage_dir=tmp_path) is None


@pytest.mark.parametrize("value", ["", None])
def test_resolve_contract_pdf_handles_empty(value, tmp_path):
    assert resolve_contract_pdf(value, storage_dir=tmp_path) is None


def test_sha256_hex_is_stable():
    assert sha256_hex(b"%PDF-1.4\n") == sha256_hex(b"%PDF-1.4\n")
    assert len(sha256_hex(b"x")) == 64


def test_index_chunks_uses_worker_payload_without_request_body():
    rows = index_chunks(
        {
            "chunks": [
                {
                    "clause_no": "제3조",
                    "text": "독점적 전송권을 허락한다.",
                    "lang": "ko",
                    "page_start": 2,
                    "page_end": 2,
                    "embedding": [0.25] * 1024,
                }
            ]
        }
    )

    assert rows == [
        {
            "clause_no": "제3조",
            "chunk_text": "독점적 전송권을 허락한다.",
            "lang": "ko",
            "page_start": 2,
            "page_end": 2,
            "embedding": "[" + ",".join(["0.25"] * 1024) + "]",
        }
    ]

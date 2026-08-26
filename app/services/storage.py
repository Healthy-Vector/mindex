"""계약 원본 PDF의 서버 내부 저장소 (D-34).

object storage는 도입하지 않기로 했다(O-12 일부 해소) — 서버 내부 디렉터리
하나를 정하고 확정(⑧) 시점에 `staging.pdf_blob.data`를 그리로 쓴다.

**경로는 서버가 정한다.** 예전에는 `contract_history.file_path`가 클라이언트가
보낸 자유 문자열이었고 `GET /contracts/{id}/file`이 그 값을 그대로 열었다 —
`/etc/passwd` 같은 경로를 넣어 확정하면 서버 파일이 그대로 내려가는 임의 파일
읽기였다. 이제 저장 경로는 `{contract_id}/{history_id}.pdf` 규칙으로 서버가
만들고, 읽을 때는 `resolve_contract_pdf()`가 저장소 밖을 가리키는 값을 거른다.

DB에는 저장소 기준 **상대 경로**만 남긴다. 저장 디렉터리를 옮겨도 기존 행이
그대로 살아있게 하려는 것이다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Union

from app.core.config import get_settings


def storage_root() -> Path:
    """설정된 계약 원본 저장 디렉터리."""
    return Path(get_settings().contract_storage_dir)


def stored_pdf_name(contract_id: int, history_id: int) -> str:
    """DB `contract_history.file_path`에 기록할 상대 경로."""
    return f"{contract_id}/{history_id}.pdf"


def write_contract_pdf(
    data: bytes,
    contract_id: int,
    history_id: int,
    *,
    storage_dir: Optional[Path] = None,
) -> str:
    """PDF 바이트를 저장소에 쓰고 DB에 남길 상대 경로를 돌려준다."""
    root = Path(storage_dir) if storage_dir is not None else storage_root()
    relative = stored_pdf_name(contract_id, history_id)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative


def resolve_contract_pdf(
    stored_path: Union[str, None],
    *,
    storage_dir: Optional[Path] = None,
) -> Optional[Path]:
    """저장된 경로를 실제 파일로 해석한다. 저장소 밖이거나 없으면 ``None``.

    절대 경로·`..` 모두 저장소 밖으로 벗어나므로 여기서 걸린다. 과거에 자유
    문자열로 들어간 행(`/tmp/contract.pdf`, `s3://...`)도 같은 이유로 걸러진다.
    """
    if not stored_path:
        return None

    root = Path(storage_dir) if storage_dir is not None else storage_root()
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / stored_path).resolve()
    except (OSError, ValueError):
        return None

    if candidate != resolved_root and resolved_root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def sha256_hex(data: bytes) -> str:
    """원본 PDF 해시. 동일 파일 재업로드 탐지에 쓰인다."""
    return hashlib.sha256(data).hexdigest()

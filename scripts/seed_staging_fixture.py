"""staging fixture 한 건을 적재하고 계약 검증·확정 요청 JSON을 생성한다.

기본 동작은 DB를 변경하지 않는 dry-run이다. 실제 적재는 ``--apply``를 명시해야
하며, PDF 원본·DONE 작업·추출 결과를 같은 tmpid로 한 트랜잭션에 저장한다.

사용 예:

    python scripts/seed_staging_fixture.py --ip-id 1 --content-asset-id 1
    python scripts/seed_staging_fixture.py --apply --ip-id 1 --content-asset-id 1
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings  # noqa: E402

DEFAULT_FIXTURE = Path("KO/T1/DIRECT_LICENSE/CTR-KO-0011.json")

LEGAL_RIGHT_MAP = {
    "INTERACTIVE_TRANSMISSION": "TRANSMISSION",
    "BROADCASTING": "BROADCAST",
    "DERIVATIVE_WORK_CREATION": "DERIVATIVE_WORK_CREATION",
    "EXHIBITION": "PUBLIC_PERFORMANCE",
    "PERFORMANCE": "PUBLIC_PERFORMANCE",
}

EXPLOITATION_MODE_MAP = {
    "SVOD": "SVOD",
    "AVOD": "AVOD",
    "TVOD": "TVOD",
    "TV_LINEAR": "TV_LINEAR",
    "THEATRICAL": "THEATRICAL",
    "MUSIC_STREAMING": "AUDIO_STREAMING",
    "ON_DEMAND_AUDIOVISUAL": "VOD",
}

EXCLUSIVITY_MAP = {
    "EXCLUSIVE": "exclusive",
    "NON_EXCLUSIVE": "non_exclusive",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"fixture JSON을 읽을 수 없습니다: {path}\n{exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("raw"), dict):
        raise SystemExit(f"worker 결과 형식(raw)이 아닙니다: {path}")
    return value


def resolved_values(field: dict[str, Any], name: str) -> list[str]:
    values = field.get("values") or []
    if field.get("field_status") not in {"PRESENT_EXPLICIT", "PRESENT_DERIVED"} or not values:
        raise ValueError(f"{name}이(가) 미확정이라 P2 요청으로 변환할 수 없습니다")
    return values


def quote(field: dict[str, Any], name: str) -> dict[str, str]:
    raw = field.get("raw_expression")
    if not raw:
        raise ValueError(f"{name}의 원문 근거가 없어 P2 evidence를 만들 수 없습니다")
    return {"quote": raw}


def p2_rights(raw: dict[str, Any], content_asset_id: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...], str, str, str]] = set()
    grants = raw["contract"].get("rights_grants") or []
    if not grants:
        raise ValueError("rights_grants가 비어 있습니다")

    for grant in grants:
        legal_field = grant["legal_right"]
        mode_field = grant["exploitation_mode"]
        territory_field = grant["territory"]
        period_field = grant["license_period"]
        exclusivity_field = grant["exclusivity"]
        legal_codes = resolved_values(legal_field, "legal_right")
        mode_codes = resolved_values(mode_field, "exploitation_mode")
        territories = resolved_values(territory_field, "territory")
        start, end = period_field.get("start"), period_field.get("end")
        if period_field.get("field_status") not in {"PRESENT_EXPLICIT", "PRESENT_DERIVED"} or not start or not end:
            raise ValueError("license_period가 미확정이라 P2 요청으로 변환할 수 없습니다")
        exclusivity = EXCLUSIVITY_MAP.get(exclusivity_field.get("value"))
        if not exclusivity:
            raise ValueError("exclusivity가 미확정이거나 현재 P2 코드에 없습니다")

        try:
            mapped_legal = [LEGAL_RIGHT_MAP[value] for value in legal_codes]
            mapped_modes = [EXPLOITATION_MODE_MAP[value] for value in mode_codes]
        except KeyError as exc:
            raise ValueError(f"현재 P2 참조 데이터에 매핑되지 않은 코드입니다: {exc.args[0]}") from exc

        evidence = {
            "legal_right": quote(legal_field, "legal_right"),
            "exploitation_mode": quote(mode_field, "exploitation_mode"),
            "territory": quote(territory_field, "territory"),
            "period": quote(period_field, "license_period"),
            "exclusivity": quote(exclusivity_field, "exclusivity"),
        }
        for legal_code in mapped_legal:
            for mode_code in mapped_modes:
                key = (legal_code, mode_code, tuple(territories), start, end, exclusivity)
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "contentAssetId": content_asset_id,
                        "legalRight": legal_code,
                        "exploitationMode": mode_code,
                        "territories": territories,
                        "period": {"start": start, "end": end},
                        "exclusivity": exclusivity,
                        "evidence": evidence,
                    }
                )
    return result


def build_requests(
    raw: dict[str, Any],
    pdf_path: Path,
    pdf_bytes: bytes,
    tmpid: uuid.UUID,
    ip_id: int,
    content_asset_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parties = raw["contract"].get("parties") or []
    by_role = {party.get("role"): party.get("name") for party in parties}
    if not by_role.get("GRANTOR") or not by_role.get("GRANTEE"):
        raise ValueError("GRANTOR/GRANTEE 당사자가 모두 필요합니다")

    base = {
        "grantor": by_role["GRANTOR"],
        "grantee": by_role["GRANTEE"],
        "ipId": ip_id,
        "fileName": pdf_path.name,
        "filePath": pdf_path.resolve().as_posix(),
        "fileHash": hashlib.sha256(pdf_bytes).hexdigest(),
        "mimeType": "application/pdf",
        "documentKind": "final",
        "rights": p2_rights(raw, content_asset_id),
    }
    verify_request = copy.deepcopy(base)
    confirm_request = {
        **base,
        "chunks": [],
        "sourceTmpid": str(tmpid),
    }
    return verify_request, confirm_request


def assert_asset_belongs_to_ip(connection, ip_id: int, content_asset_id: int) -> None:
    found = connection.execute(
        text(
            "SELECT 1 FROM content_asset "
            "WHERE id=:content_asset_id AND ip_id=:ip_id"
        ),
        {"ip_id": ip_id, "content_asset_id": content_asset_id},
    ).scalar()
    if found is None:
        raise ValueError("contentAssetId가 지정한 ipId에 속하지 않습니다")


def seed_staging(
    database_url: str,
    tmpid: uuid.UUID,
    pdf_path: Path,
    pdf_bytes: bytes,
    fixture: dict[str, Any],
    ip_id: int,
    content_asset_id: int,
) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            assert_asset_belongs_to_ip(connection, ip_id, content_asset_id)
            existing = connection.execute(
                text("SELECT 1 FROM staging.pdf_blob WHERE tmpid=:tmpid"),
                {"tmpid": str(tmpid)},
            ).scalar()
            if existing is not None:
                raise ValueError(f"이미 존재하는 tmpid입니다: {tmpid}")
            connection.execute(
                text(
                    "INSERT INTO staging.pdf_blob(tmpid, data, filename, byte_size) "
                    "VALUES (:tmpid, :data, :filename, :byte_size)"
                ),
                {
                    "tmpid": str(tmpid),
                    "data": pdf_bytes,
                    "filename": pdf_path.name,
                    "byte_size": len(pdf_bytes),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO staging.extract_job(tmpid, status, stage, attempts) "
                    "VALUES (:tmpid, 'DONE', 'LLM', 1)"
                ),
                {"tmpid": str(tmpid)},
            )
            connection.execute(
                text(
                    "INSERT INTO staging.extract_result(tmpid, payload) "
                    "VALUES (:tmpid, CAST(:payload AS jsonb))"
                ),
                {
                    "tmpid": str(tmpid),
                    "payload": json.dumps(fixture, ensure_ascii=False),
                },
            )
    finally:
        engine.dispose()


def main() -> int:
    repo_root = REPO_ROOT
    default_root = repo_root / "data" / "generated" / "staging-fixtures"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, default=default_root)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--pdf-root", type=Path, default=repo_root.parent / "pdf" / "generated")
    parser.add_argument("--ip-id", type=int, required=True)
    parser.add_argument("--content-asset-id", type=int, required=True)
    parser.add_argument("--tmpid", type=uuid.UUID, default=None)
    parser.add_argument("--apply", action="store_true", help="staging DB에 실제 INSERT")
    parser.add_argument("--output", type=Path, default=None, help="요청 JSON 출력 경로")
    args = parser.parse_args()

    fixture_path = args.fixture if args.fixture.is_absolute() else args.fixture_root / args.fixture
    try:
        relative = fixture_path.resolve().relative_to(args.fixture_root.resolve())
    except ValueError as exc:
        raise SystemExit("fixture는 fixture-root 아래에 있어야 합니다") from exc
    pdf_path = args.pdf_root / relative.with_suffix(".pdf")
    if not fixture_path.is_file():
        raise SystemExit(f"fixture를 찾을 수 없습니다: {fixture_path}")
    if not pdf_path.is_file():
        raise SystemExit(f"원본 PDF를 찾을 수 없습니다: {pdf_path}")

    fixture = read_json(fixture_path)
    pdf_bytes = pdf_path.read_bytes()
    tmpid = args.tmpid or uuid.uuid4()
    try:
        verify_request, confirm_request = build_requests(
            fixture["raw"], pdf_path, pdf_bytes, tmpid, args.ip_id, args.content_asset_id
        )
    except ValueError as exc:
        raise SystemExit(f"요청 JSON 생성 실패: {exc}") from exc

    output = args.output or (
        args.fixture_root / "requests" / f"{fixture_path.stem}-{tmpid}.request.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "fixture": relative.as_posix(),
                "pdf": str(pdf_path.resolve()),
                "tmpid": str(tmpid),
                "verifyRequest": verify_request,
                "confirmRequest": confirm_request,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if args.apply:
        try:
            seed_staging(
                get_settings().database_url,
                tmpid,
                pdf_path,
                pdf_bytes,
                fixture,
                args.ip_id,
                args.content_asset_id,
            )
        except ValueError as exc:
            raise SystemExit(f"staging 적재 실패: {exc}") from exc
        print(f"staging 적재 완료: tmpid={tmpid}")
    else:
        print("dry-run: staging DB에는 아무 것도 저장하지 않았습니다")
        print(f"실제 적재: --apply --tmpid {tmpid}")

    print(f"요청 JSON: {output.resolve()}")
    print("Swagger 순서: POST /api/contracts/verify → POST /api/contracts")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("취소되었습니다", file=sys.stderr)
        raise SystemExit(130) from None

"""staging 추출 결과에 사용자 수정본을 반영하고 판정 입력으로 바꾼다 (D-34).

⑥(사용자 확인·수정)과 ⑦(검증)의 재설계다. 예전에는 화면이 수정값을 들고
있다가 ⑧(확정)에서 전체 페이로드로 한 번에 넘겼고, verify는 staging을 읽지
않았다. 이제 verify가 `tmpid` + merge patch를 받아 **staging에 먼저 반영한 뒤
저장된 값으로 판정**한다. 확정도 같은 값을 읽어 저장한다(B안, D-32/D-33).

## payload 안의 두 shape

`staging.extract_result.payload`는 워커 원본이고 `{raw: {contract: ...},
validation: {...}}` 구조다. 화면이 보는 건 `to_upload_result()`가 만든 DTO
(`contractInfo`/`rights`/...)이고 **그 변환은 단방향·손실이 있다** — 워커 코드가
접히고(EXHIBITION·PERFORMANCE → PUBLIC_PERFORMANCE) territory 그룹이 국가로
전개된다. 역변환기는 만들 수 없다.

그래서 수정본은 워커 원본을 덮어쓰지 않고 같은 payload 안 `edited` 키에 DTO
shape 그대로 넣는다. `raw`가 남아 있어 `to_upload_result()`가 계속 동작하고,
재추출·비교도 가능하다.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import ExtractNotReady, ValidationFailed
from app.schemas.contracts import RightIn
from app.services.extraction_result import to_upload_result
from app.services.merge_patch import apply_merge_patch

EDITED_KEY = "edited"


def territory_groups(db: Session) -> dict[str, list[str]]:
    """`APAC` 같은 그룹 코드를 국가 목록으로 펴기 위한 참조표."""
    rows = db.execute(
        text(
            "SELECT group_code, country_code FROM territory_group_member "
            "ORDER BY group_code, country_code"
        )
    ).mappings()
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        groups[row["group_code"]].append(row["country_code"])
    return dict(groups)


def load_done_extraction(db: Session, tmpid: UUID) -> Mapping[str, Any]:
    """DONE 상태의 추출 결과를 잠금과 함께 읽는다.

    `FOR UPDATE`는 같은 tmpid에 대한 동시 verify가 서로의 수정본을 덮어쓰는 걸
    막는다. 결과 행이 없거나 DONE이 아니면 확정도 검증도 할 수 없다.
    """
    row = db.execute(
        text(
            "SELECT j.status, r.payload FROM staging.extract_job j "
            "JOIN staging.extract_result r ON r.tmpid=j.tmpid "
            "WHERE j.tmpid=:t FOR UPDATE OF j, r"
        ),
        {"t": str(tmpid)},
    ).mappings().first()
    status = row["status"] if row else None
    if status != "DONE":
        raise ExtractNotReady(
            "추출이 끝난(DONE) tmpId만 사용할 수 있습니다",
            details={"status": status},
        )
    return row


def current_dto(db: Session, payload: Mapping[str, Any]) -> dict[str, Any]:
    """화면이 보고 있는 현재값. 수정본이 있으면 그것, 없으면 워커 원본 변환."""
    edited = payload.get(EDITED_KEY)
    if isinstance(edited, Mapping):
        return dict(edited)
    return to_upload_result(payload, territory_group_members=territory_groups(db))


def apply_patch(
    db: Session, payload: Mapping[str, Any], patch: Optional[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """수정본에 patch를 얹어 ``(새 payload, 새 DTO)``를 만든다.

    patch가 없으면 저장된 값을 그대로 쓴다 — 사용자가 아무것도 안 고치고 바로
    검증을 누른 경우다.
    """
    dto = current_dto(db, payload)
    if patch:
        dto = apply_merge_patch(dto, patch)
        if not isinstance(dto, Mapping):
            raise ValidationFailed("patch는 객체여야 합니다")
        dto = dict(dto)

    new_payload = dict(payload)
    new_payload[EDITED_KEY] = dto
    return new_payload, dto


def persist_edited(db: Session, tmpid: UUID, payload: Mapping[str, Any]) -> None:
    """수정본을 staging에 반영한다. `raw`는 그대로 남는다."""
    import json

    db.execute(
        text(
            "UPDATE staging.extract_result SET payload=CAST(:payload AS jsonb) "
            "WHERE tmpid=:t"
        ),
        {"t": str(tmpid), "payload": json.dumps(payload, ensure_ascii=False, default=str)},
    )


def rights_from_dto(dto: Mapping[str, Any]) -> list[RightIn]:
    """DTO의 `rights[]`를 판정 입력(`RightIn`)으로 바꾼다.

    DTO 행은 `RightIn`과 필드가 1:1로 맞고 `conversionWarnings`만 남는데 그건
    무시된다. 워커가 확정하지 못한 값(`legalRight: null` 등)은 사용자가 화면에서
    채우기 전이라는 뜻이므로 400으로 돌려준다 — 판정에 넣을 수 없다.
    """
    rows = dto.get("rights")
    if not isinstance(rows, list) or not rows:
        raise ValidationFailed("검증할 권리가 없습니다. 최소 한 건이 필요합니다")

    rights: list[RightIn] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValidationFailed(
                "rights 원소는 객체여야 합니다", details={"index": index}
            )
        try:
            rights.append(RightIn.model_validate(dict(row)))
        except Exception as ex:  # noqa: BLE001 — pydantic 오류를 400으로 내린다
            raise ValidationFailed(
                "권리 값이 아직 채워지지 않았거나 형식이 올바르지 않습니다",
                details={"index": index, "reason": str(ex).splitlines()[0][:200]},
            ) from ex
    return rights

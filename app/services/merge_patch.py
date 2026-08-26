"""JSON Merge Patch (RFC 7386) 적용기 — verify가 받는 부분수정용 (D-34).

화면은 추출 결과 DTO 전체를 되보내지 않고 사용자가 고친 필드만 보낸다. 그
델타를 저장된 값 위에 얹는 규칙이 RFC 7386이다.

**배열은 원소 단위로 병합하지 않고 통째로 교체한다.** RFC 7386의 규정이며,
`rights`도 여기 해당한다 — staging payload의 권리 행에는 안정적인 식별자가
없어 원소 단위 병합 규칙을 세울 근거가 없다(D-34).
"""
from __future__ import annotations

from typing import Any, Mapping


def apply_merge_patch(target: Any, patch: Any) -> Any:
    """``target``에 ``patch``를 적용한 새 값을 돌려준다. ``target``은 변경하지 않는다."""
    if not isinstance(patch, Mapping):
        # 객체가 아닌 patch는 대상을 그대로 치환한다(배열·스칼라·null 포함).
        return patch

    merged: dict[str, Any] = dict(target) if isinstance(target, Mapping) else {}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = apply_merge_patch(merged.get(key), value)
    return merged

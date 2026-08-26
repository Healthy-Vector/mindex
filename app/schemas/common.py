"""공통 Pydantic 베이스 (지시서 §4.1 §4.6).

- DB snake_case ↔ API camelCase 변환은 여기 한 곳에서만.
- 라우터에서 손으로 dict 를 만들지 않는다.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Page(CamelModel, Generic[T]):
    """페이지네이션 응답 (지시서 §4.6): total/page/size 항상 포함."""

    items: list[T]
    total: int
    page: int
    size: int


def camelize_json_keys(value: Any) -> Any:
    """JSON 객체의 키를 재귀적으로 camelCase로 변환한다.

    Pydantic alias_generator는 ``Any`` 안쪽의 JSONB 키까지 변환하지 않으므로,
    DB JSONB를 API에 노출할 때 이 함수를 명시적으로 사용한다.
    """
    if isinstance(value, Mapping):
        return {to_camel(str(key)): camelize_json_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [camelize_json_keys(item) for item in value]
    return value

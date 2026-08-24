"""공통 Pydantic 베이스 (지시서 §4.1 §4.6).

- DB snake_case ↔ API camelCase 변환은 여기 한 곳에서만.
- 라우터에서 손으로 dict 를 만들지 않는다.
"""
from __future__ import annotations

from typing import Generic, TypeVar

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

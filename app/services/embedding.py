"""쿼리 임베딩 훅 (지시서 §6 15번 4단계).

프로바이더가 구성되지 않으면 None 을 반환한다. 이 경우 벡터 랭킹은 생략되고
SQL 필터로 좁힌 후보를 최신순으로 돌려준다(순서 규칙은 그대로 지킴: 필터→랭킹).

실제 임베딩을 붙이려면 여기서 openai/solar/hyperclova 등을 호출해
vector(1024) 차원의 리스트를 반환하도록 구현한다.
"""
from __future__ import annotations

from typing import Optional


def embed_query(text: str) -> Optional[list[float]]:
    return None  # 미구성: 벡터 랭킹 생략

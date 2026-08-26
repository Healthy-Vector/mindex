"""쿼리 임베딩 훅 (지시서 §6 15번 4단계).

## 왜 LLM_PROVIDER(openai/solar/hyperclova)를 쓰면 안 되는가

이전 버전 docstring은 여기서 openai/solar/hyperclova 를 호출하라고 적어 뒀었다.
틀렸다. `contract_chunk.embedding`은 SFR-005로 고정된 **multilingual-e5-large**
(1024차원, 로컬 구동)로 채워진다. 코사인 비교(`<=>`)가 의미를 가지려면 질의도
**같은 모델, 같은 벡터 공간**으로 임베딩해야 한다.

다른 모델을 쓰면 두 가지로 깨진다.
  1. 차원이 다르면(OpenAI 1536/3072차원 등) `vector(1024)`와 비교하는 SQL이
     그 자리에서 에러를 낸다.
  2. 우연히 차원이 같아도 서로 다른 모델의 벡터 공간은 좌표축 자체가 다르므로
     "가까운 벡터 = 의미가 비슷하다"는 전제가 성립하지 않는다.

`LLM_PROVIDER`는 추출·정규화(LLM 텍스트 생성)용 설정이지 임베딩용이 아니다.
임베딩은 `app/pipeline/embed.py`가 이미 갖고 있는 e5 싱글턴을 그대로 재사용한다
(재구현하지 않는다 — 이미 접두사·정규화·fp16·CI 폴백이 다 돼 있다).

## 임베딩이 없는 환경(CI 등)

`sentence_transformers`가 없으면 None을 반환한다. 이 경우 벡터 랭킹은 생략되고
SQL 필터로 좁힌 후보를 최신순으로 돌려준다(순서 규칙은 그대로 지킴: 필터→랭킹).
"""
from __future__ import annotations

from typing import Optional

from app.pipeline import embed as embed_mod


def embed_query(text: str) -> Optional[list[float]]:
    if not text.strip() or not embed_mod.is_available():
        return None
    return embed_mod.embed_queries([text])[0]

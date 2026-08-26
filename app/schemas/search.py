"""15번 POST /search 스키마 (팀 API 명세 정렬).

`docs/mindex-API설계서.md` §15의 구버전(page/size/score 단일 근거)에서, 팀이
실제로 쓰는 명세(limit/similarity/snippets[])로 갈아탔다. 다만 팀 명세 초안이
확정본은 아니라고 확인돼서 다음은 팀 결정으로 조정했다:
  - `rightsTypes`(단일 배열) 대신 `legalRights`/`exploitationModes`를 그대로
    유지한다 — 두 축을 하나로 합치면 지시서 금지사항("rightsType 단일축
    복구")과 부딪힌다.
  - 이미 동작하던 `period`(라이선스 기간) 필터는 그대로 둔다. `signedFrom`/
    `signedTo`(계약 체결일)는 별개 축이라 새로 추가만 한다.
  - `avgConfidence`는 반환된 `results[]`의 `similarity` 평균이다(팀 확인).
  - `counterparty`(단일 필드) 대신 `contract` 테이블 그대로 `grantor`/`grantee`
    두 필드로 노출한다. `contractTitle` 대신 기존 `title` 명칭을 유지한다
    (팀 결정).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from app.schemas.common import CamelModel


class SearchPeriod(CamelModel):
    start: date
    end: date

    @model_validator(mode="after")
    def end_not_before_start(self) -> "SearchPeriod":
        if self.end < self.start:
            raise ValueError("period.end는 period.start보다 빠를 수 없습니다")
        return self


class SearchFilters(CamelModel):
    legal_rights: Optional[list[str]] = None
    exploitation_modes: Optional[list[str]] = None
    territories: Optional[list[str]] = None
    exclusivity: Optional[Literal["exclusive", "sole", "non_exclusive"]] = None
    period: Optional[SearchPeriod] = None
    #: 계약 체결일(`contract.signed_date`) 범위. 라이선스 기간(`period`)과는
    #: 별개 축이다 — 언제 서명했는지 vs 언제부터 언제까지 쓸 수 있는지.
    signed_from: Optional[date] = None
    signed_to: Optional[date] = None


class SearchRequest(CamelModel):
    query: str = ""
    #: cross면 원문 언어가 질의어 언어와 다른 결과만 남긴다(교차언어 검색).
    mode: Literal["natural", "cross"] = "natural"
    filters: Optional[SearchFilters] = None
    limit: int = Field(default=20, ge=1, le=100)


class Snippet(CamelModel):
    """근거 조각 하나 — 하이브리드 점수(어휘+의미) 상위 N개, 임계값 이상만.

    **조항 본문(`text`)은 싣지 않는다 (D-40).** 어디서 걸렸는지(`clauseNo`·`page`)와
    얼마나 맞는지(`similarity`)만 준다. 원문은 PIN 세션이 필요한 8·9번
    (상세·원본 PDF)에서만 나간다 — 검색 화면이 근거문을 표시하지 않기로 하면서
    응답에서도 뺐다. 화면에 없는 것을 API가 내보내지 않는다.
    """

    chunk_id: int
    page: Optional[int] = None
    clause_no: Optional[str] = None
    similarity: float


class SearchResult(CamelModel):
    contract_id: int
    #: `contract_history.file_name` (최신 세대). 팀 명세의 contractTitle 대신
    #: 기존 title 명칭을 그대로 쓴다(팀 결정).
    title: Optional[str] = None
    #: `contract.grantor`/`grantee` 그대로. counterparty로 한쪽만 묶지 않는다
    #: (팀 결정 — 단일 필드로 합치지 않고 실제 컬럼 그대로 노출).
    grantor: str
    grantee: str
    #: 이 계약의 최고 snippet 점수. snippets가 비면(=임계값 넘는 근거 없음) None —
    #: 그 경우 이 계약은 애초에 results[]에 안 실린다.
    similarity: Optional[float] = None
    #: 구조화 필터가 왜 걸렸는지 태그. 예: "territory:KR", "exclusivity:exclusive"
    matched_filters: list[str] = Field(default_factory=list)
    source_lang: Optional[str] = None
    snippets: list[Snippet] = Field(default_factory=list)


class SearchResponse(CamelModel):
    interpreted: dict[str, Any]
    #: 실제로 실행된 처리 단계. 임베딩을 못 쓰면 VECTOR_RANK가 빠진다
    #: (기존 vector_ranked bool 대체 — 더 서술적).
    stages: list[str]
    results: list[SearchResult]
    #: results[]의 similarity 평균. similarity가 전부 None(벡터 랭킹 자체가
    #: 안 돌았음)이면 None.
    avg_confidence: Optional[float] = None

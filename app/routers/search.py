"""15번 POST /search — 하이브리드 검색 (팀 API 명세 정렬).

순서: 1) 해석 2) filters 우선 3) rights_grant(2축) SQL 후보 축소
4) 후보 안에서만 contract_chunk 어휘(pg_trgm) + 벡터(pgvector) 하이브리드 랭킹.
벡터를 먼저 하지 않는다(§10-11) — 후보 축소 후에만 청크를 본다는 규칙은 그대로다.

## 어휘 + 벡터를 섞는 이유

`contract_chunk`에 `pg_trgm`(09_chunk_search.sql)과 `vector`(04_vector.sql)가
둘 다 이미 있다. Task1의 RAG 회수에서 어휘 단독은 질의 표현이 문서와 조금만
달라도 성능이 크게 떨어졌고(원본 85.6%→held-out 67.4% @1), 그 반대로 벡터
단독은 정확한 법률 용어 일치를 놓치는 경우가 있다 — 두 실패 유형이 달라서
섞으면 서로 보완된다.

## 의미 점수를 정규화하는 이유

e5 코사인이 좁은 구간(실측 0.68~0.86)에 눌려 있어 `1 - dist` 원값을 그대로
쓰면 항상 0.14~0.32 근처라, 0~1 전 구간을 쓰는 어휘 점수와 섞을 때 사실상
어휘가 지배해버린다. 후보군(이번 검색의 `contract_chunk` 전체) 안에서
min-max로 0~1로 펴서 섞는다 — Task1의 `semantic_norm`과 같은 이유·같은 해법.

## snippet은 계약당 최상단 1개만

화면에는 계약당 최고 점수 snippet 1개만 싣는다(화면 담당자 전달 포맷 확정,
팀 결정). `MIN_SNIPPET_SCORE` 미만이면 그 1개도 없다는 뜻이라 —
**임계값을 넘는 snippet이 하나도 없는 계약은 결과에서 아예 뺀다** — "가장 덜
무관한 것"을 억지로 채우지 않는다. 구조화 필터 통과 여부와 무관하게
적용한다.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.search import SearchRequest, SearchResponse, SearchResult, Snippet
from app.services.embedding import embed_query
from app.services.query_interpret import interpret
from app.services.territory import expand_territories, to_daterange_literal

router = APIRouter()

#: 어휘(pg_trgm)와 의미(pgvector)를 섞는 비율. 0이면 어휘만, 1이면 의미만.
#:
#: Task1의 RAG 회수(app/pipeline/retrieval.py DEFAULT_SEMANTIC_WEIGHT)가
#: held-out 집합으로 0.5를 검증해뒀다. 같은 계약서 도메인·같은 e5 모델이라
#: 시작값으로 그대로 가져왔다 — 다만 /search는 질의 패턴이 RAG의 필드형
#: 질의(예: "이용지역")와 다른 자유 문장이라, 이 값 자체를 이 엔드포인트
#: 기준으로 재검증한 것은 아니다. 실사용 로그가 쌓이면 다시 잰다.
HYBRID_WEIGHT = 0.5

#: snippet 하나가 "근거로 보여줄 만하다"고 인정하는 점수 하한선.
#: Task1의 min_score=0.15와 같은 값으로 시작.
MIN_SNIPPET_SCORE = 0.15

#: 계약 하나당 근거로 보여줄 최대 snippet 수. 화면 포맷 확정(팀 결정)으로
#: 최상단 1개만 싣는다.
SNIPPETS_PER_CONTRACT = 1

_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HANJA = re.compile(r"[一-鿿]")


def _detect_lang(query: str) -> str:
    """스크립트 기반 대략 판정 — mode=cross 전용. 정밀 언어 판정이 아니라
    한국어 질의가 한국어 계약을 다시 찾아오는 걸 막는 정도면 충분하다."""
    if _HANGUL.search(query):
        return "ko"
    if _KANA.search(query) or _HANJA.search(query):
        return "ja"
    return "en"


def _effective(interp: dict[str, Any], filters) -> dict[str, Any]:
    eff = {
        "legalRights": list(interp.get("legalRights", [])),
        "exploitationModes": list(interp.get("exploitationModes", [])),
        "territories": list(interp.get("territories", [])),
        "territoryGroups": list(interp.get("territoryGroups", [])),
        "exclusivity": interp.get("exclusivity"),
        "period": interp.get("period"),
        "signedFrom": None,
        "signedTo": None,
    }
    if filters is not None:
        if filters.legal_rights is not None:
            eff["legalRights"] = filters.legal_rights
        if filters.exploitation_modes is not None:
            eff["exploitationModes"] = filters.exploitation_modes
        if filters.territories is not None:
            eff["territories"] = filters.territories
            eff["territoryGroups"] = []
        if filters.exclusivity is not None:
            eff["exclusivity"] = filters.exclusivity
        if filters.period is not None:
            eff["period"] = filters.period.model_dump(mode="json")
        if filters.signed_from is not None:
            eff["signedFrom"] = filters.signed_from.isoformat()
        if filters.signed_to is not None:
            eff["signedTo"] = filters.signed_to.isoformat()
    return eff


def _vec(v) -> str:
    return "[" + ",".join(str(float(x)) for x in v) + "]"


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    interp = interpret(db, body.query)          # 1
    eff = _effective(interp, body.filters)      # 2

    terrs = list(eff["territories"])
    if eff["territoryGroups"]:
        terrs = expand_territories(db, terrs + eff["territoryGroups"])

    clauses = ["TRUE"]
    params: dict[str, Any] = {}
    if eff["legalRights"]:
        clauses.append("rg.legal_right = ANY(:lr)")
        params["lr"] = eff["legalRights"]
    if eff["exploitationModes"]:
        clauses.append("rg.exploitation_mode = ANY(:em)")
        params["em"] = eff["exploitationModes"]
    if terrs:
        clauses.append("rg.territory = ANY(:terrs)")
        params["terrs"] = terrs
    if eff["exclusivity"]:
        clauses.append("rg.exclusivity = CAST(:excl AS exclusivity_kind)")
        params["excl"] = eff["exclusivity"]
    if eff["period"]:
        clauses.append("rg.period && CAST(:period AS daterange)")
        params["period"] = to_daterange_literal(eff["period"]["start"], eff["period"]["end"])

    from_clause = "confirmed_rights_grant rg"
    if eff["signedFrom"] or eff["signedTo"]:
        from_clause += " JOIN contract c ON c.id = rg.contract_id"
        if eff["signedFrom"]:
            clauses.append("c.signed_date >= :signed_from")
            params["signed_from"] = eff["signedFrom"]
        if eff["signedTo"]:
            clauses.append("c.signed_date <= :signed_to")
            params["signed_to"] = eff["signedTo"]

    candidates = [
        int(x) for x in db.execute(
            text(f"SELECT DISTINCT rg.contract_id FROM {from_clause} WHERE " + " AND ".join(clauses)),
            params,
        ).scalars().all()
    ]

    if body.mode == "cross" and candidates:  # 교차언어 — 원문 언어가 질의어와 같은 건 뺀다
        qlang = _detect_lang(body.query)
        candidates = [
            int(x) for x in db.execute(
                text("SELECT id FROM contract WHERE id = ANY(:ids) AND lang IS DISTINCT FROM :qlang"),
                {"ids": candidates, "qlang": qlang},
            ).scalars().all()
        ]

    # matchedFilters — 이 후보들이 실제로 만족한 구조화 조건값(태그로 보여줄 것)
    matched_tags: dict[int, list[str]] = {c: [] for c in candidates}
    if candidates and (eff["legalRights"] or eff["exploitationModes"] or terrs or eff["exclusivity"]):
        tag_rows = db.execute(
            text(
                "SELECT DISTINCT contract_id, territory, legal_right, exploitation_mode, exclusivity "
                "FROM confirmed_rights_grant WHERE contract_id = ANY(:cands)"
            ),
            {"cands": candidates},
        ).all()
        for cid, terr, lr, em, excl in tag_rows:
            tags = matched_tags.setdefault(int(cid), [])
            if terrs:
                tags.append(f"territory:{terr}")
            if eff["legalRights"]:
                tags.append(f"legalRight:{lr}")
            if eff["exploitationModes"]:
                tags.append(f"exploitationMode:{em}")
            if eff["exclusivity"]:
                tags.append(f"exclusivity:{excl}")
    if eff["signedFrom"]:
        for c in candidates:
            matched_tags.setdefault(c, []).append(f"signedDate>={eff['signedFrom']}")
    if eff["signedTo"]:
        for c in candidates:
            matched_tags.setdefault(c, []).append(f"signedDate<={eff['signedTo']}")
    for tags in matched_tags.values():
        tags[:] = sorted(set(tags))

    stages = ["SQL_FILTER"]
    snippets: dict[int, list[Snippet]] = {}
    scores: dict[int, float] = {}
    qvec = embed_query(body.query) if candidates else None
    if qvec and candidates:  # 4
        stages.append("VECTOR_RANK")
        rows = db.execute(
            text(
                """
                WITH scored AS (
                    SELECT
                        ch.id AS chunk_id,
                        ch.contract_id,
                        ch.clause_no,
                        ch.page_start,
                        ch.chunk_text,
                        ch.embedding <=> CAST(:qv AS vector) AS dist,
                        word_similarity(lower(ch.chunk_text), :q) AS lex
                    FROM contract_chunk ch
                    WHERE ch.contract_id = ANY(:cands)
                ),
                norm AS (
                    SELECT
                        chunk_id, contract_id, clause_no, page_start, chunk_text, lex,
                        CASE
                            -- 후보 청크가 1개뿐이거나 전부 거리가 같으면 정규화할
                            -- 분산이 없다. 0으로 두면 "비교 대상이 없다"가
                            -- "무관하다"로 잘못 해석돼 진짜 강한 매치까지 임계값
                            -- 밖으로 밀려난다(실측으로 발견) — 1(=최대한 관련
                            -- 있다고 봄)로 둬서 어휘 점수가 최종 판단을 하게 한다.
                            WHEN max(1 - dist) OVER () = min(1 - dist) OVER () THEN 1
                            ELSE (1 - dist - min(1 - dist) OVER ())
                                 / (max(1 - dist) OVER () - min(1 - dist) OVER ())
                        END AS sem_norm
                    FROM scored
                ),
                ranked_chunks AS (
                    SELECT
                        chunk_id, contract_id, clause_no, page_start, chunk_text,
                        (1 - :w) * lex + :w * COALESCE(sem_norm, 0) AS score,
                        row_number() OVER (
                            PARTITION BY contract_id
                            ORDER BY (1 - :w) * lex + :w * COALESCE(sem_norm, 0) DESC
                        ) AS rn
                    FROM norm
                )
                SELECT contract_id, chunk_id, clause_no, page_start, chunk_text, score
                FROM ranked_chunks
                WHERE rn <= :topn AND score >= :minscore
                ORDER BY contract_id, score DESC
                """
            ),
            {
                "qv": _vec(qvec), "q": body.query.lower(), "w": HYBRID_WEIGHT,
                "cands": candidates, "topn": SNIPPETS_PER_CONTRACT, "minscore": MIN_SNIPPET_SCORE,
            },
        ).all()
        for cid, chunk_id, clause_no, page_start, chunk_text, score in rows:
            cid = int(cid)
            snippets.setdefault(cid, []).append(
                Snippet(chunk_id=int(chunk_id), page=page_start, clause_no=clause_no,
                        text=chunk_text, similarity=float(score))
            )
            scores[cid] = max(scores.get(cid, 0.0), float(score))
        # 임계값 넘는 snippet이 하나도 없는 계약은 결과에서 뺀다 (팀 결정).
        ranked = sorted(snippets, key=lambda c: scores[c], reverse=True)
    else:
        ranked = [
            int(x) for x in db.execute(
                text("SELECT id FROM contract WHERE id = ANY(:ids) ORDER BY created_at DESC"),
                {"ids": candidates},
            ).scalars().all()
        ] if candidates else []
    stages.append("MAPPED")

    window = ranked[: body.limit]
    results: list[SearchResult] = []
    for cid in window:
        c = db.execute(
            text(
                "SELECT c.id, c.grantor, c.grantee, c.lang, "
                "  (SELECT file_name FROM contract_history WHERE contract_id=c.id ORDER BY version DESC LIMIT 1) title "
                "FROM contract c WHERE c.id=:c"
            ),
            {"c": cid},
        ).mappings().first()
        if c:
            results.append(SearchResult(
                contract_id=c["id"], title=c["title"], grantor=c["grantor"], grantee=c["grantee"],
                similarity=scores.get(cid), matched_filters=matched_tags.get(cid, []),
                source_lang=c["lang"], snippets=snippets.get(cid, []),
            ))

    sims = [r.similarity for r in results if r.similarity is not None]
    avg_confidence = sum(sims) / len(sims) if sims else None
    return SearchResponse(interpreted=interp, stages=stages, results=results, avg_confidence=avg_confidence)

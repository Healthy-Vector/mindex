"""15번 POST /search — 하이브리드 검색 (지시서 §6 15번).

순서를 지킨다:
 1) query 해석 → interpreted
 2) filters(사용자 지정)가 있으면 그쪽 우선
 3) rights_grant 를 SQL 로 좁혀 후보 contract_id 집합
 4) 그 집합 안에서만 contract_chunk.embedding 코사인 유사도로 랭킹
벡터 검색을 먼저 하지 않는다(§10-11).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.services.embedding import embed_query
from app.services.query_interpret import interpret
from app.services.team_context import resolve_team_id
from app.services.territory import expand_territories, to_daterange_literal

router = APIRouter()


def _effective(interp: dict[str, Any], filters) -> dict[str, Any]:
    """filters(사용자 지정)가 있으면 해당 축을 덮어쓴다(§15 2단계)."""
    eff = {
        "territories": list(interp.get("territories", [])),
        "territoryGroups": list(interp.get("territoryGroups", [])),
        "rightsTypes": list(interp.get("rightsTypes", [])),
        "exclusivity": interp.get("exclusivity"),
        "period": interp.get("period"),
    }
    if filters is not None:
        if filters.territories is not None:
            eff["territories"] = filters.territories
            eff["territoryGroups"] = []
        if filters.rights_types is not None:
            eff["rightsTypes"] = filters.rights_types
        if filters.exclusivity is not None:
            eff["exclusivity"] = filters.exclusivity
        if filters.period is not None:
            eff["period"] = filters.period
    return eff


def _vector_literal(vec) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    s = get_settings()
    size = body.size or s.page_size_default
    team_id = resolve_team_id(db)

    interp = interpret(db, body.query)          # 1
    eff = _effective(interp, body.filters)      # 2

    # 3) SQL 로 후보 contract_id 좁히기
    terrs = list(eff["territories"])
    if eff["territoryGroups"]:
        terrs = expand_territories(db, terrs + eff["territoryGroups"])
    clauses = ["rg.status='active'", "c.team_id = :team"]
    params: dict[str, Any] = {"team": team_id}
    if terrs:
        clauses.append("rg.territory = ANY(:terrs)")
        params["terrs"] = terrs
    if eff["rightsTypes"]:
        clauses.append("rg.rights_type = ANY(:rts)")
        params["rts"] = eff["rightsTypes"]
    if eff["exclusivity"]:
        clauses.append("rg.exclusivity = :excl")
        params["excl"] = eff["exclusivity"]
    if eff["period"]:
        clauses.append("rg.period && CAST(:period AS daterange)")
        params["period"] = to_daterange_literal(eff["period"]["start"], eff["period"]["end"])

    cand_rows = db.execute(
        text(
            "SELECT DISTINCT rg.contract_id FROM master.rights_grant rg "
            "JOIN master.contract c ON c.id=rg.contract_id WHERE "
            + " AND ".join(clauses)
        ),
        params,
    ).scalars().all()
    candidates = [int(x) for x in cand_rows]

    vector_ranked = False
    ranked_ids: list[int]
    scores: dict[int, float] = {}
    qvec = embed_query(body.query) if candidates else None

    if qvec and candidates:  # 4) 후보 안에서만 벡터 랭킹
        rows = db.execute(
            text(
                "SELECT c.id, min(ch.embedding <=> CAST(:qv AS vector)) AS dist "
                "FROM master.contract_chunk ch "
                "JOIN master.contract_history h ON h.id=ch.contract_history_id "
                "JOIN master.contract c ON c.id=h.contract_id "
                "WHERE c.id = ANY(:cands) GROUP BY c.id ORDER BY dist ASC"
            ),
            {"qv": _vector_literal(qvec), "cands": candidates},
        ).all()
        ranked_ids = [int(r[0]) for r in rows]
        for r in rows:
            scores[int(r[0])] = 1.0 - float(r[1])  # 코사인 유사도
        vector_ranked = True
        # 임베딩이 없는 후보는 뒤에 최신순으로 덧붙임
        missing = [cid for cid in candidates if cid not in set(ranked_ids)]
        if missing:
            rest = db.execute(
                text(
                    "SELECT id FROM master.contract WHERE id = ANY(:ids) "
                    "ORDER BY created_at DESC"
                ),
                {"ids": missing},
            ).scalars().all()
            ranked_ids += [int(x) for x in rest]
    else:
        # 벡터 미구성: 필터 후보를 최신순 (순서 규칙은 지킴 — 필터가 먼저다)
        ranked_ids = [
            int(x)
            for x in db.execute(
                text(
                    "SELECT id FROM master.contract WHERE id = ANY(:ids) "
                    "ORDER BY created_at DESC"
                ),
                {"ids": candidates} if candidates else {"ids": []},
            ).scalars().all()
        ] if candidates else []

    total = len(ranked_ids)
    window = ranked_ids[(body.page - 1) * size : (body.page - 1) * size + size]
    results: list[SearchResult] = []
    for cid in window:
        c = db.execute(
            text("SELECT id, title, counterparty, status FROM master.contract WHERE id=:c"),
            {"c": cid},
        ).mappings().first()
        if c:
            results.append(
                SearchResult(
                    contract_id=c["id"], title=c["title"], counterparty=c["counterparty"],
                    status=c["status"], score=scores.get(cid),
                )
            )

    return SearchResponse(
        interpreted=interp, results=results, total=total,
        page=body.page, size=size, vector_ranked=vector_ranked,
    )

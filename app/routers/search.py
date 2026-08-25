"""15번 POST /search — 하이브리드 검색 (P2-DB 정렬).

순서: 1) 해석 2) filters 우선 3) rights_grant(2축) SQL 후보 축소
4) 후보 안에서만 contract_chunk 벡터 랭킹. 벡터를 먼저 하지 않는다(§10-11).
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
from app.services.territory import expand_territories, to_daterange_literal

router = APIRouter()


def _effective(interp: dict[str, Any], filters) -> dict[str, Any]:
    eff = {
        "legalRights": list(interp.get("legalRights", [])),
        "exploitationModes": list(interp.get("exploitationModes", [])),
        "territories": list(interp.get("territories", [])),
        "territoryGroups": list(interp.get("territoryGroups", [])),
        "exclusivity": interp.get("exclusivity"),
        "period": interp.get("period"),
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
            eff["period"] = filters.period
    return eff


def _vec(v) -> str:
    return "[" + ",".join(str(float(x)) for x in v) + "]"


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    s = get_settings()
    size = body.size or s.page_size_default
    interp = interpret(db, body.query)          # 1
    eff = _effective(interp, body.filters)      # 2

    terrs = list(eff["territories"])
    if eff["territoryGroups"]:
        terrs = expand_territories(db, terrs + eff["territoryGroups"])

    clauses = ["rg.status='active'"]
    params: dict[str, Any] = {}
    if eff["legalRights"]:
        clauses.append("rg.legal_right = ANY(:lr)"); params["lr"] = eff["legalRights"]
    if eff["exploitationModes"]:
        clauses.append("rg.exploitation_mode = ANY(:em)"); params["em"] = eff["exploitationModes"]
    if terrs:
        clauses.append("rg.territory = ANY(:terrs)"); params["terrs"] = terrs
    if eff["exclusivity"]:
        clauses.append("rg.exclusivity = CAST(:excl AS exclusivity_kind)"); params["excl"] = eff["exclusivity"]
    if eff["period"]:
        clauses.append("rg.period && CAST(:period AS daterange)")
        params["period"] = to_daterange_literal(eff["period"]["start"], eff["period"]["end"])

    candidates = [
        int(x) for x in db.execute(
            text("SELECT DISTINCT rg.contract_id FROM rights_grant rg WHERE " + " AND ".join(clauses)),
            params,
        ).scalars().all()
    ]

    scores: dict[int, float] = {}
    vector_ranked = False
    qvec = embed_query(body.query) if candidates else None
    if qvec and candidates:  # 4
        rows = db.execute(
            text(
                "SELECT c.id, min(ch.embedding <=> CAST(:qv AS vector)) dist "
                "FROM contract_chunk ch JOIN contract c ON c.id=ch.contract_id "
                "WHERE c.id = ANY(:cands) GROUP BY c.id ORDER BY dist ASC"
            ),
            {"qv": _vec(qvec), "cands": candidates},
        ).all()
        ranked = [int(r[0]) for r in rows]
        for r in rows:
            scores[int(r[0])] = 1.0 - float(r[1])
        ranked += [c for c in candidates if c not in set(ranked)]
        vector_ranked = True
    else:
        ranked = [
            int(x) for x in db.execute(
                text("SELECT id FROM contract WHERE id = ANY(:ids) ORDER BY created_at DESC"),
                {"ids": candidates},
            ).scalars().all()
        ] if candidates else []

    total = len(ranked)
    window = ranked[(body.page - 1) * size : (body.page - 1) * size + size]
    results: list[SearchResult] = []
    for cid in window:
        c = db.execute(
            text(
                "SELECT c.id, c.counterparty, c.status, "
                "  (SELECT file_name FROM contract_history WHERE contract_id=c.id ORDER BY version DESC LIMIT 1) title "
                "FROM contract c WHERE c.id=:c"
            ),
            {"c": cid},
        ).mappings().first()
        if c:
            results.append(SearchResult(contract_id=c["id"], title=c["title"],
                                        counterparty=c["counterparty"], status=c["status"],
                                        score=scores.get(cid)))
    return SearchResponse(interpreted=interp, results=results, total=total,
                          page=body.page, size=size, vector_ranked=vector_ranked)

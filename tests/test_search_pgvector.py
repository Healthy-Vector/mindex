"""P4 자연어 검색 — pgvector 하이브리드 랭킹 통합 테스트 (Phase 2-3, 팀 명세 정렬).

`embed_query()`가 실제로 `/api/search`의 랭킹 경로를 태우는지, 어휘(pg_trgm) +
벡터(pgvector) 하이브리드 점수가 계약을 올바르게 가르는지, 무관한 결과이 실제로
걸러지는지, snippets(근거 조각 배열)이 채워지는지를 확인한다.

sentence_transformers가 없는 환경(CI)에서는 스킵된다 — `embed_query()`가 `None`을
반환하고 `/search`는 필터만으로 동작하는 게 정상이라 여기서 검증할 게 없다.
"""

from __future__ import annotations

import pytest

from app.pipeline import embed as embed_mod
from tests.conftest import body, requires_db

pytestmark = [
    requires_db,
    pytest.mark.skipif(
        not embed_mod.is_available(),
        reason="sentence_transformers 미설치 — requirements-ml.txt 참조",
    ),
]

RELEVANT_TEXT = (
    "재이용허락은 해당 개별 이용허락에 명시된 범위에서만 허용된다. "
    "계약자는 상대방의 사전 서면 동의 없이 재이용허락을 할 수 없다."
)
OTHER_TEXT = (
    "이용자는 허락자에게 계약대가로 매 분기 정산 금액을 지급한다. "
    "지급 지연 시 연 5%의 지연이자가 발생한다."
)
QUERY = "재허락에 상대방 동의가 필요한 계약"


def _confirm_contract(client, clean_db, **kwargs) -> tuple[int, int]:
    r = client.post("/api/contracts", json=body(clean_db, **kwargs))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["batchResult"] == "APPLIED"
    return j["contractId"], j["contractHistoryId"]


def _insert_chunk(conn, *, contract_id: int, history_id: int, clause_no: str, page: int, text: str) -> None:
    vec = embed_mod.embed_passages([text])[0]
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contract_chunk "
        "(contract_id, contract_history_id, clause_no, page_start, chunk_text, lang, embedding) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (contract_id, history_id, clause_no, page, text, "ko", vec),
    )
    conn.commit()


def test_hybrid_search_returns_snippets_and_drops_irrelevant(client, conn, clean_db):
    """taxonomy 라벨과 안 겹치는 순수 자연어 질의 — 구조화 필터가 하나도 안 걸려서
    전체 confirmed 계약이 후보가 되고, 하이브리드 점수만으로 갈린다.

    실측: relevant 합산점수 0.57 / other 0.019 (MIN_SNIPPET_SCORE=0.15 미만)
    → other는 snippet이 하나도 임계값을 못 넘어 results에서 아예 빠진다.
    """
    relevant_id, relevant_hist = _confirm_contract(clean_db=clean_db, client=client, territory="KR")
    _insert_chunk(conn, contract_id=relevant_id, history_id=relevant_hist, clause_no="제14조", page=3, text=RELEVANT_TEXT)

    other_id, other_hist = _confirm_contract(clean_db=clean_db, client=client, territory="JP")
    _insert_chunk(conn, contract_id=other_id, history_id=other_hist, clause_no="제7조", page=2, text=OTHER_TEXT)

    r = client.post("/api/search", json={"query": QUERY})
    assert r.status_code == 200, r.text
    j = r.json()

    assert "VECTOR_RANK" in j["stages"]
    assert j["results"], "결과가 비어 있으면 필터 단계에서 후보가 안 뽑힌 것"

    ids = [row["contractId"] for row in j["results"]]
    assert relevant_id in ids
    assert other_id not in ids, "무관한 계약은 snippet 임계값 미만이라 걸러져야 한다"

    top = j["results"][0]
    assert top["contractId"] == relevant_id
    assert top["similarity"] is not None
    assert top["grantor"] and top["grantee"]

    # avgConfidence — 반환된 results[]의 similarity 평균 (팀 확인 사항).
    # 이 테스트는 결과가 relevant 1건뿐이라 top의 similarity와 같아야 한다.
    assert j["avgConfidence"] == pytest.approx(top["similarity"])

    # snippets — 근거 조각이 배열로 실려 있어야 한다.
    assert top["snippets"], "snippets가 비어 있으면 근거가 안 실린 것"
    snippet = top["snippets"][0]
    assert snippet["clauseNo"] == "제14조"
    assert snippet["page"] == 3
    assert snippet["similarity"] is not None
    # D-40 — 조항 본문은 응답에 싣지 않는다. 화면에 없는 것은 API도 주지 않는다.
    assert "text" not in snippet
    assert isinstance(snippet["chunkId"], int)


def test_matched_filters_reflect_actual_grant_values(client, conn, clean_db):
    """구조화 필터(territory)가 걸리면 결과에 실제로 매칭된 값이 태그로 실린다.

    임계값 넘는 snippet이 0개인 계약은 필터 통과 여부와 무관하게 빠진다(팀 결정,
    아래 두 번째 테스트에서 확인) — 그래서 이 테스트는 둘 다 관련 텍스트를 넣어
    matchedFilters 태그 자체가 실제 rights_grant 값과 맞는지만 본다.
    """
    relevant_id, relevant_hist = _confirm_contract(clean_db=clean_db, client=client, territory="KR")
    _insert_chunk(conn, contract_id=relevant_id, history_id=relevant_hist, clause_no="제14조", page=3, text=RELEVANT_TEXT)

    r = client.post(
        "/api/search",
        json={"query": QUERY, "filters": {"territories": ["KR"]}},
    )
    assert r.status_code == 200, r.text
    j = r.json()

    ids = [row["contractId"] for row in j["results"]]
    assert relevant_id in ids

    top = next(row for row in j["results"] if row["contractId"] == relevant_id)
    assert "territory:KR" in top["matchedFilters"]


def test_zero_qualifying_snippets_drops_contract_even_when_filtered(client, conn, clean_db):
    """임계값 넘는 snippet이 0개면, 구조화 필터를 통과했어도 결과에서 빠진다
    (팀 결정 — 필터 통과 여부로 예외를 두지 않는다).
    """
    # 같은 territory/legal_right/exploitation_mode로 겹치는 기간을 잡으면
    # EXCLUDE 제약(R7 독점성 충돌)에 걸려 CONFLICTED가 난다 — 기간을 벌려서 회피.
    relevant_id, relevant_hist = _confirm_contract(clean_db=clean_db, client=client, territory="KR")
    _insert_chunk(conn, contract_id=relevant_id, history_id=relevant_hist, clause_no="제14조", page=3, text=RELEVANT_TEXT)

    irrelevant_id, irrelevant_hist = _confirm_contract(
        clean_db=clean_db, client=client, territory="KR", start="2030-01-01", end="2030-12-31"
    )
    _insert_chunk(conn, contract_id=irrelevant_id, history_id=irrelevant_hist, clause_no="제7조", page=2, text=OTHER_TEXT)

    r = client.post(
        "/api/search",
        json={"query": QUERY, "filters": {"territories": ["KR"]}},
    )
    assert r.status_code == 200, r.text
    j = r.json()

    ids = [row["contractId"] for row in j["results"]]
    assert relevant_id in ids
    assert irrelevant_id not in ids, "필터를 통과해도 snippet이 0개면 빠져야 한다"


def test_cross_mode_excludes_contracts_matching_query_language(client, conn, clean_db):
    """mode=cross는 원문 언어(`contract.lang`)가 질의어 언어와 같은 계약을 뺀다.

    질의는 한국어(QUERY)라 lang='ko'인 계약은 cross 모드에서 빠지고 lang='en'인
    계약만 남아야 한다. natural 모드(기본값)는 언어와 무관하게 둘 다 반환한다.
    두 계약 다 같은 근거 텍스트를 넣어 의미 점수를 동일하게 맞추고, lang만
    다르게 해서 cross 필터 하나만 검증한다.
    """
    ko_id, ko_hist = _confirm_contract(clean_db=clean_db, client=client, territory="KR")
    _insert_chunk(conn, contract_id=ko_id, history_id=ko_hist, clause_no="제14조", page=3, text=RELEVANT_TEXT)

    en_id, en_hist = _confirm_contract(
        clean_db=clean_db, client=client, territory="KR", start="2030-01-01", end="2030-12-31"
    )
    _insert_chunk(conn, contract_id=en_id, history_id=en_hist, clause_no="제14조", page=3, text=RELEVANT_TEXT)

    cur = conn.cursor()
    cur.execute("UPDATE contract SET lang='ko' WHERE id=%s", (ko_id,))
    cur.execute("UPDATE contract SET lang='en' WHERE id=%s", (en_id,))
    conn.commit()

    r_natural = client.post("/api/search", json={"query": QUERY})
    assert r_natural.status_code == 200, r_natural.text
    natural_ids = [row["contractId"] for row in r_natural.json()["results"]]
    assert ko_id in natural_ids and en_id in natural_ids, "natural 모드는 언어와 무관하게 둘 다 반환해야 한다"

    r_cross = client.post("/api/search", json={"query": QUERY, "mode": "cross"})
    assert r_cross.status_code == 200, r_cross.text
    cross_ids = [row["contractId"] for row in r_cross.json()["results"]]
    assert en_id in cross_ids
    assert ko_id not in cross_ids, "질의가 한국어면 원문도 한국어(lang=ko)인 계약은 cross 모드에서 빠져야 한다"


def test_superseded_generation_chunks_are_not_searched(client, conn, clean_db):
    """개정판으로 대체된 구세대 조항은 검색되지 않는다.

    `contract_chunk`는 세대마다 쌓이고 구세대 행이 지워지지 않으므로, 계약 id로만
    조회하면 이미 대체된 문구가 근거로 잡힌다. `contract.current_history_id`로
    한 세대만 남기는지 확인한다.
    """
    contract_id, old_history_id = _confirm_contract(client, clean_db)

    # 개정판 세대를 만들고 현재 세대로 올린다.
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contract_history "
        "  (contract_id, version, document_kind, status, file_name, file_path, file_hash) "
        "VALUES (%s, 2, 'final', 'applied', 'v2.pdf', %s, 'h2') RETURNING id",
        (contract_id, f"{contract_id}/2.pdf"),
    )
    new_history_id = cur.fetchone()[0]
    cur.execute(
        "UPDATE contract SET current_history_id=%s WHERE id=%s",
        (new_history_id, contract_id),
    )
    conn.commit()

    # 질의에 딱 맞는 문구는 대체된 구세대에만, 현재 세대에는 무관한 문구만 둔다.
    _insert_chunk(
        conn, contract_id=contract_id, history_id=old_history_id,
        clause_no="제5조", page=5, text=RELEVANT_TEXT,
    )
    _insert_chunk(
        conn, contract_id=contract_id, history_id=new_history_id,
        clause_no="제9조", page=9, text=OTHER_TEXT,
    )

    found = client.post("/api/search", json={"query": QUERY}).json()
    hit = next((r for r in found["results"] if r["contractId"] == contract_id), None)

    assert hit is None, "대체된 구세대 조항이 근거로 잡히면 안 된다"

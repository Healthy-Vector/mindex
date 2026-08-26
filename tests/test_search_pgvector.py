"""P4 자연어 검색 — pgvector 벡터 랭킹 통합 테스트 (Phase 2).

`embed_query()`가 실제로 `/api/search`의 벡터 랭킹 경로를 태우는지 확인한다.
`contract_chunk`에 실제 e5 임베딩을 넣고, 그 청크와 의미상 가까운 자연어 질의를
던져서 해당 계약이 최상위로 올라오는지 검증한다.

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


def _confirm_contract(client, clean_db, **kwargs) -> tuple[int, int]:
    r = client.post("/api/contracts", json=body(clean_db, **kwargs))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["batchResult"] == "APPLIED"
    return j["contractId"], j["contractHistoryId"]


def _insert_chunk(conn, *, contract_id: int, history_id: int, clause_no: str, text: str) -> None:
    vec = embed_mod.embed_passages([text])[0]
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contract_chunk "
        "(contract_id, contract_history_id, clause_no, chunk_text, lang, embedding) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (contract_id, history_id, clause_no, text, "ko", vec),
    )
    conn.commit()


def test_vector_ranking_surfaces_semantically_relevant_contract(client, conn, clean_db):
    # 관련 계약 — 재허락(서브라이선스) 조항
    relevant_id, relevant_hist = _confirm_contract(clean_db=clean_db, client=client, territory="KR")
    _insert_chunk(
        conn,
        contract_id=relevant_id,
        history_id=relevant_hist,
        clause_no="제14조",
        text="재이용허락은 해당 개별 이용허락에 명시된 범위에서만 허용된다. "
        "계약자는 상대방의 사전 서면 동의 없이 재이용허락을 할 수 없다.",
    )

    # 무관 계약 — 지급 조건 조항 (필터에 안 걸리게 다른 지역으로)
    other_id, other_hist = _confirm_contract(clean_db=clean_db, client=client, territory="JP")
    _insert_chunk(
        conn,
        contract_id=other_id,
        history_id=other_hist,
        clause_no="제7조",
        text="이용자는 허락자에게 계약대가로 매 분기 정산 금액을 지급한다. "
        "지급 지연 시 연 5%의 지연이자가 발생한다.",
    )

    # taxonomy 라벨과 안 겹치는 자연어 질의 — interpret()이 구조화 필터를 못 뽑아서
    # candidates가 필터 없이(전체 confirmed 계약) 뽑히고, 벡터 랭킹만으로 갈린다.
    r = client.post("/api/search", json={"query": "재허락에 상대방 동의가 필요한 계약"})
    assert r.status_code == 200, r.text
    j = r.json()

    assert j["vectorRanked"] is True
    assert j["results"], "결과가 비어 있으면 필터 단계에서 후보가 안 뽑힌 것"
    top = j["results"][0]
    assert top["contractId"] == relevant_id
    assert top["score"] is not None

    ids = [r["contractId"] for r in j["results"]]
    assert relevant_id in ids and other_id in ids
    rel_score = next(r["score"] for r in j["results"] if r["contractId"] == relevant_id)
    other_score = next(r["score"] for r in j["results"] if r["contractId"] == other_id)
    assert rel_score > other_score

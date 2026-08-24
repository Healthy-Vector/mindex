"""회수 정답지 가드.

정답지는 `testdata/k-rights/annotations/`에서 파생된 산출물이다. 원본 주석이
바뀌었는데 정답지를 다시 만들지 않으면, 평가가 낡은 기준으로 조용히 통과한다.
여기서 둘이 어긋났는지 본다.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from app.schemas.pipeline import RETRIEVAL_FIELDS

GOLDSET = Path("eval/retrieval_goldset.json")
EVIDENCE = Path("testdata/k-rights/annotations/phase_h_actual_evidence.json")

pytestmark = pytest.mark.skipif(
    not (GOLDSET.exists() and EVIDENCE.exists()),
    reason="정답지 또는 원본 주석이 없는 환경",
)


@pytest.fixture(scope="module")
def gold() -> dict:
    return json.loads(GOLDSET.read_text(encoding="utf-8"))


def test_정답지가_원본_주석과_일치한다(gold):
    """원본이 바뀌면 scripts/build_goldset.py 를 다시 돌려야 한다."""
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))["actual_evidence"]
    assert gold["source_evidence_total"] == len(evidence)

    expected = collections.Counter()
    for e in evidence:
        f = gold["label_to_field"].get(e["label_id"])
        if f:
            expected[f] += 1
    assert gold["answers_per_field"] == dict(sorted(expected.items()))
    assert gold["answer_total"] == sum(expected.values())


def test_모든_회수필드가_평가되거나_불가로_표시된다(gold):
    """조용히 빠진 필드가 있으면 '전부 검증했다'는 착각이 남는다."""
    covered = set(gold["answers_per_field"]) | set(gold["unevaluable_fields"])
    assert covered == set(RETRIEVAL_FIELDS)


def test_parties는_측정_불가로_명시돼_있다(gold):
    """정답 라벨이 없다. 빠뜨린 게 아니라 못 재는 것이라는 표시가 있어야 한다."""
    assert "parties" in gold["unevaluable_fields"]
    assert gold["answers_per_field"].get("parties", 0) == 0


def test_rights_type은_두_축에서_온다(gold):
    """LEGAL_RIGHT 와 EXPLOITATION_MODE 는 절대 합치지 않는 두 축이다.

    회수 질의 이름이 하나인 것은 임시이며, 추출 결과 단계에서는 분리해야 한다.
    정답지가 출처 라벨을 남기는지 확인한다.
    """
    labels = {lb for lb, f in gold["label_to_field"].items() if f == "rights_type"}
    assert labels == {"LEGAL_RIGHT", "EXPLOITATION_MODE"}
    seen = {
        a["label"]
        for c in gold["contracts"]
        for a in c["fields"].get("rights_type", [])
    }
    assert seen == labels


def test_정답은_chunk_id가_아니라_텍스트다(gold):
    """chunk_id 는 청킹을 바꾸면 전부 달라진다. 정답지의 키가 될 수 없다."""
    for c in gold["contracts"]:
        for answers in c["fields"].values():
            for a in answers:
                assert a["text"].strip()
                assert "chunk_id" not in a


def test_모든_계약이_pdf_경로를_가진다(gold):
    assert len(gold["contracts"]) == gold["contract_count"]
    for c in gold["contracts"]:
        assert c["pdf_path"].startswith("testdata/k-rights/")

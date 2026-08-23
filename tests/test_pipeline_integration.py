"""파이프라인 통합 — 실제 PDF 한 건을 끝까지 통과시킨다.

임베딩은 끈다. `sentence_transformers`가 requirements-ml.txt에만 있어서
CI에는 없기 때문이다. **임베딩 없이도 파이프라인이 돌아야 한다**는 것 자체가
설계 요건이라 여기서 함께 검증한다.

정답은 testdata의 Evidence 주석에서 읽어온다. 하드코딩하면 정답이 바뀌었을 때
테스트가 조용히 낡는다.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from app.pipeline import retrieve_contract_chunks

TESTDATA = Path("testdata/k-rights")
EVIDENCE_JSON = TESTDATA / "annotations/phase_h_actual_evidence.json"
# 별지에 권리 명세가 들어가는 T5 재이용허락 계약. 난이도가 높은 축이다.
SAMPLE_ID = "CTR-KO-0015"
SAMPLE_PDF = TESTDATA / "documents/pdf/KO/T5/SUBLICENSE/CTR-KO-0015.pdf"

pytestmark = pytest.mark.skipif(
    not SAMPLE_PDF.exists(), reason="합성데이터 PDF가 없는 환경"
)


def _squash(s: str) -> str:
    """공백과 소프트하이픈을 걷어낸 비교용 형태."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", s).replace("­", ""))


@pytest.fixture(scope="module")
def bundle() -> dict:
    return retrieve_contract_chunks(SAMPLE_PDF.read_bytes(), file_name=SAMPLE_PDF.name, embed=False)


@pytest.fixture(scope="module")
def evidence() -> list[dict]:
    data = json.loads(EVIDENCE_JSON.read_text(encoding="utf-8"))
    return [e for e in data["actual_evidence"] if e["contract_id"] == SAMPLE_ID]


def test_번들_기본구조(bundle):
    assert bundle["schema_version"].startswith("mindex.retrieval-bundle.")
    assert set(bundle) == {"schema_version", "document", "retrieval", "fields", "chunks"}
    doc = bundle["document"]
    assert doc["language"] == "ko"
    assert doc["page_count"] > 1
    assert doc["text_normalization"] == "NFC"


def test_임베딩_없이도_회수가_동작한다(bundle):
    """CI에는 torch가 없다. 이 경로가 깨지면 나머지 검증이 전부 막힌다."""
    assert bundle["document"]["embedded"] is False
    assert bundle["retrieval"]["scorer"] == "lexical-v0"
    assert all(c["embedding"] is None for c in bundle["chunks"])
    # 어휘 신호만으로도 필드가 비지 않아야 한다
    assert bundle["fields"]["territory"], "territory 회수 결과가 비었다"


def test_ML_미설치_환경을_흉내내도_예외가_나지_않는다(monkeypatch):
    from app.pipeline import embed as embed_mod

    monkeypatch.setattr(embed_mod, "is_available", lambda: False)
    out = retrieve_contract_chunks(SAMPLE_PDF.read_bytes(), embed=True)
    assert out["document"]["embedded"] is False


def test_별지가_독립_청크로_잡힌다(bundle):
    """T5는 권리 명세를 전부 별지에 넣는다. 본문 조항에 흡수되면 추출이 어긋난다."""
    kinds = {c["clause_kind"] for c in bundle["chunks"]}
    assert "GRANT_ITEM" in kinds or "SCHEDULE" in kinds


def test_페이지가_범위로_기록된다(bundle):
    for c in bundle["chunks"]:
        assert c["page_start"] <= c["page_end"]
        # DB의 단일 page 컬럼 호환값은 시작 페이지여야 한다
        assert c["page"] == c["page_start"]


def test_청크_offset이_서로_어긋나지_않는다(bundle):
    for c in bundle["chunks"]:
        assert c["char_end"] - c["char_start"] == len(c["text"])


@pytest.mark.parametrize(
    ("label", "field_name"),
    [("TERRITORY", "territory"), ("LICENSE_PERIOD", "period"), ("EXCLUSIVITY", "exclusivity")],
)
def test_정답_근거가_상위_회수결과_안에_있다(bundle, evidence, label, field_name):
    """검색 품질 회귀 가드.

    청킹이나 점수식을 건드렸을 때 조용히 나빠지는 것을 막는다.
    정답 문장이 상위 청크 중 하나에 **온전히** 담겨 있어야 한다.
    """
    answers = [_squash(e["text"]) for e in evidence if e["label_id"] == label]
    if not answers:
        pytest.skip(f"{SAMPLE_ID}에 {label} 정답이 없다")

    by_id = {c["chunk_id"]: c for c in bundle["chunks"]}
    retrieved = [_squash(by_id[h["chunk_id"]]["text"]) for h in bundle["fields"][field_name]]
    assert retrieved, f"{field_name} 회수 결과가 비었다"
    assert any(any(a in r for r in retrieved) for a in answers), (
        f"{field_name}: 정답 근거가 상위 {len(retrieved)}개 안에 없다"
    )

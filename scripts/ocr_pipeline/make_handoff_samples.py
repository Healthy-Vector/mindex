"""Task2 인계용 샘플 재생성.

    python scripts/make_handoff_samples.py

`app.pipeline.retrieve_contract_chunks` 를 그대로 호출한다. 예전에는 샘플 생성기가
따로 있어서 파이프라인과 형식이 갈라질 수 있었다. 이제 샘플은 **실제 코드의
출력 그 자체**다.

## 전부 임베딩을 채운다

한때 크기 때문에 1건만 채웠다. 기본 scorer 가 `hybrid-v1` 이 되면서 그렇게 둘
수 없게 됐다. **점수가 임베딩에 의존하므로, 벡터를 뺀 샘플은 `score` 를 파일
안에서 재현할 수 없다.** 받는 쪽이 형식을 확인하다가 어긋난 값을 보게 된다.

전부 채우면 10건 합쳐 약 2.6MB 다. 사람이 통째로 읽기엔 크지만, 샘플이 실제
출력과 정확히 같은 편이 낫다. 구조를 눈으로 볼 때는 `jq 'del(.chunks[].embedding)'`
로 걷어내면 된다.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.pipeline import retrieve_contract_chunks

OUT = Path("docs/handoff/samples")
MANIFEST = Path("testdata/k-rights/manifests/contract_pdf_manifest.json")
TESTDATA = Path("testdata/k-rights")

# 언어 × 템플릿 × 계약유형이 골고루 덮이도록 고른 10건.
SAMPLE_IDS = [
    "CTR-KO-0001",  # 가장 단순. 여기서 시작
    "CTR-EN-0001",
    "CTR-JP-0001",
    "CTR-EN-0017",  # 재이용허락 — 권한체인(R8)
    "CTR-JP-0002",
    "CTR-EN-0006",
    "CTR-KO-0014",  # 별지 없이 본문에 복수 Grant
    "CTR-KO-0015",  # 별지 3개 + 재이용허락
    "CTR-JP-0015",  # 별지 5개. 최대 난이도
    "CTR-KO-0006",  # OST 음악 권리처리 별지
]

def main() -> int:
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("contracts")
    by_id = {r["contract_id"]: r for r in rows}

    OUT.mkdir(parents=True, exist_ok=True)

    # 예전 중간 산출물. 파이프라인이 더 이상 만들지 않으므로 남겨 두면
    # 코드와 형식이 어긋난 파일이 인계 폴더에 그대로 남는다.
    for stale in OUT.glob("*.parse.json"):
        stale.unlink()
        print(f"제거 {stale.name}")

    for cid in SAMPLE_IDS:
        pdf = TESTDATA / by_id[cid]["pdf_path"]
        bundle = retrieve_contract_chunks(pdf.read_bytes(), file_name=pdf.name)
        dest = OUT / f"{cid}.retrieval.json"
        dest.write_text(
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        r = bundle.retrieval
        mark = "" if bundle.document.embedded else "  [벡터 없음]"
        print(
            f"{cid}  {bundle.document.language}  "
            f"{bundle.document.page_count}p  조항 {r.clause_total}  "
            f"청크 {r.chunk_total}(색인 {r.chunk_indexable}, 참조 {r.chunk_referenced})  "
            f"{dest.stat().st_size / 1024:.0f}KB{mark}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

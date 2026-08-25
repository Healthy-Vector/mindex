"""전건 end-to-end 실행 — 86건을 실제 파이프라인에 통과시킨다.

`eval_retrieval.py`와 목적이 다르다. 그쪽은 **회수 품질**(정답지 대조)을 재고,
이쪽은 **파이프라인이 전건에서 끝까지 도는가**를 본다. 규격 위반·예외·성능이
대상이다. 회수 점수는 여기서 보지 않는다.

    python scripts/ocr_pipeline/run_e2e.py                 # 전건, 임베딩 포함
    python scripts/ocr_pipeline/run_e2e.py --no-embed      # ML 없이 (CI 경로)
    python scripts/ocr_pipeline/run_e2e.py --limit 10      # 앞 10건만
    python scripts/ocr_pipeline/run_e2e.py --json out.json # 건별 통계 저장

`retrieve_contract_chunks`가 pydantic 모델을 돌려주므로 규격 검증은 반환
시점에 이미 끝나 있다. 여기서는 그 위에 **코퍼스 전체에 걸친 불변조건**을
얹는다 — 한 건씩 보면 안 보이고 86건을 모아야 드러나는 것들이다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from app.pipeline.service import retrieve_contract_chunks
from app.schemas.pipeline import SCHEMA_VERSION

MANIFEST = Path("testdata/k-rights/manifests/contract_pdf_manifest.json")
TESTDATA = Path("testdata/k-rights")


def check_corpus_invariants(rows: list[dict]) -> list[str]:
    """건별 검증을 통과해도 코퍼스 단위로 보면 드러나는 문제들."""
    bad: list[str] = []

    # chunk_id는 문서해시 앞 12자 + 순번이다. 서로 다른 계약이 같은 id를 내면
    # contract_chunk에서 조인 키가 겹친다. 86건 × 20청크면 충돌 확률이 낮지만
    # 확률이 낮다는 것과 안 일어난다는 것은 다르다.
    ids = Counter(cid for r in rows for cid in r["chunk_ids"])
    if dup := [i for i, n in ids.items() if n > 1]:
        bad.append(f"chunk_id 충돌 {len(dup)}건: {dup[:5]}")

    # 같은 PDF가 두 번 들어 있으면 평가 수치가 부풀려진다.
    hashes = Counter(r["file_hash"] for r in rows)
    if dup := [h for h, n in hashes.items() if n > 1]:
        bad.append(f"동일 file_hash {len(dup)}건 — 중복 계약서 의심: {dup[:3]}")

    # 조항을 하나도 못 찾으면 통째로 한 덩어리가 된다. 회수가 사실상 불가능하다.
    if uns := [r["contract_id"] for r in rows if r["unsegmented"]]:
        bad.append(f"조항 분해 실패(UNSEGMENTED) {len(uns)}건: {uns[:5]}")

    # 어떤 필드도 못 건진 계약. 추출 단계가 아예 시작을 못 한다.
    if empty := [r["contract_id"] for r in rows if r["fields_hit"] == 0]:
        bad.append(f"회수 결과가 전무한 계약 {len(empty)}건: {empty[:5]}")

    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contracts = manifest["contracts"][: args.limit] if args.limit else manifest["contracts"]
    embed = not args.no_embed

    print(f"{SCHEMA_VERSION}  ·  {len(contracts)}건  ·  embed={embed}\n")

    # 모델 로딩을 첫 계약의 처리 시간에서 떼어낸다. 안 그러면 1건이 90초대,
    # 나머지가 0.6초대로 찍혀 평균이 무의미해진다. 실제 서비스에서도 워커가
    # 상주 싱글턴으로 한 번만 로딩하므로 이렇게 재는 쪽이 현실에 가깝다.
    load_s = 0.0
    if embed:
        from app.pipeline import embed as embed_mod

        if embed_mod.is_available():
            t = time.perf_counter()
            embed_mod.get_model()
            load_s = time.perf_counter() - t
            print(f"모델 로딩 {load_s:.1f}초 (1회, 이후 상주)\n")
        else:
            print("⚠ sentence_transformers 미설치 — 어휘 회수만 수행한다\n")

    rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    t_all = time.perf_counter()

    for i, meta in enumerate(contracts, 1):
        cid = meta["contract_id"]
        pdf = TESTDATA / meta["pdf_path"]
        t0 = time.perf_counter()
        try:
            b = retrieve_contract_chunks(
                pdf.read_bytes(), file_name=pdf.name, embed=embed
            )
        except ValidationError as e:
            failures.append((cid, f"규격 위반: {e.error_count()}건 — {e.errors()[0]['msg']}"))
            continue
        except Exception as e:  # noqa: BLE001 — 어떤 예외든 건별로 기록하고 계속 간다
            failures.append((cid, f"{type(e).__name__}: {e}"))
            continue
        dt = time.perf_counter() - t0

        r = b.retrieval
        rows.append(
            {
                "contract_id": cid,
                "language": meta["language"],
                "template": meta["template_family"],
                "pages": b.document.page_count,
                "clauses": r.clause_total,
                "chunks": r.chunk_total,
                "indexable": r.chunk_indexable,
                "referenced": r.chunk_referenced,
                "embedded": b.document.embedded,
                "fields_hit": sum(1 for hits in b.fields.values() if hits),
                "seconds": round(dt, 2),
                "file_hash": b.document.file_hash,
                "chunk_ids": [c.chunk_id for c in b.chunks],
                "unsegmented": any(c.clause_kind == "UNSEGMENTED" for c in b.chunks),
                "sources": {k.value: v for k, v in b.document.text_source_summary.items()},
            }
        )
        if i % 10 == 0 or i == len(contracts):
            print(f"  {i:>3}/{len(contracts)}  {dt:5.2f}s  {cid}")

    elapsed = time.perf_counter() - t_all
    print()

    if failures:
        print(f"실패 {len(failures)}건")
        for cid, msg in failures:
            print(f"  {cid}  {msg}")
        print()

    if not rows:
        print("성공한 건이 없다.")
        return 1

    n = len(rows)
    tot = lambda k: sum(r[k] for r in rows)  # noqa: E731
    print(
        f"성공 {n}/{len(contracts)}건   처리 {elapsed:.1f}초 "
        f"(건당 평균 {elapsed / n:.2f}초, 모델 로딩 {load_s:.1f}초 별도)"
    )
    print(
        f"페이지 {tot('pages')}   조항 {tot('clauses')}   "
        f"청크 {tot('chunks')}(색인 {tot('indexable')}, 회수 {tot('referenced')})"
    )

    src = Counter()
    for r in rows:
        src.update(r["sources"])
    print(f"텍스트 경로  {dict(src)}")

    not_embedded = [r["contract_id"] for r in rows if not r["embedded"]]
    if embed and not_embedded:
        print(f"⚠ 임베딩이 안 붙은 계약 {len(not_embedded)}건: {not_embedded[:5]}")

    print("\n언어·템플릿별")
    by = Counter((r["language"], r["template"]) for r in rows)
    for (lang, tpl), cnt in sorted(by.items()):
        sel = [r for r in rows if (r["language"], r["template"]) == (lang, tpl)]
        print(
            f"  {lang} {tpl}  {cnt:>2}건   "
            f"청크 평균 {tot_of(sel, 'chunks') / cnt:5.1f}   "
            f"회수 평균 {tot_of(sel, 'referenced') / cnt:5.1f}   "
            f"{tot_of(sel, 'seconds') / cnt:5.2f}s"
        )

    slow = sorted(rows, key=lambda r: -r["seconds"])[:3]
    print(f"\n가장 느린 3건  {[(r['contract_id'], r['seconds']) for r in slow]}")

    print()
    if bad := check_corpus_invariants(rows):
        print("코퍼스 불변조건 위반")
        for msg in bad:
            print(f"  ✗ {msg}")
    else:
        print("코퍼스 불변조건 통과 (chunk_id 유일 · file_hash 유일 · 분해 실패 0 · 빈 회수 0)")

    if args.json:
        args.json.write_text(
            json.dumps({"rows": rows, "failures": failures}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n건별 통계 → {args.json}")

    return 1 if failures or bad else 0


def tot_of(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows)


if __name__ == "__main__":
    sys.exit(main())

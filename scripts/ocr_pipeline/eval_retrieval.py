"""회수 품질 평가 (Phase 3b).

    PYTHONPATH=. python scripts/eval_retrieval.py                    # 어휘 단독
    PYTHONPATH=. python scripts/eval_retrieval.py --sweep 0 .2 .4 .6 # 가중치 비교
    PYTHONPATH=. python scripts/eval_retrieval.py --limit 10         # 빠른 확인

`eval/retrieval_goldset.json`의 정답 556건을 기준으로 Recall@1/@3/@5를 잰다.

## 실패를 네 갈래로 나눈다

합계만 보면 무엇을 고쳐야 할지 알 수 없다. 정답 하나마다 이렇게 판정한다.

| 판정 | 뜻 | 고칠 곳 |
|---|---|---|
| `hit` | 상위 k 안에 있다 | — |
| `rank_miss` | 청크에는 있는데 상위 k에 못 들었다 | **점수식** |
| `chunk_miss` | 어느 청크에도 온전히 안 담겼다 | **청킹** |
| `extract_miss` | 문서 텍스트에서 아예 못 찾는다 | **추출** (또는 정답 쪽 문제) |

`chunk_miss`는 검색 알고리즘을 아무리 고쳐도 회수되지 않는다. 정답이 두 청크에
걸쳐 있기 때문이다. 페이지 분할 방식일 때 781건 중 55건이 여기 해당했다.

## 주의 — 이 숫자는 낙관적 상한이다

어휘 패턴을 바로 이 합성데이터 표현(`이용지역은`, `총 계약대가는`)에 맞춰 썼다.
실제 계약서가 `서비스 대상 지역`처럼 쓰면 떨어진다. **가중치를 이 수치만 보고
정하면 안 된다.** 튜닝하지 않은 의미검색 쪽이 일반화 신호로는 더 정직하다.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline import embed as embed_mod
from app.pipeline.chunk import build_chunks
from app.pipeline.extract import extract_document
from app.pipeline.retrieval import FIELD_QUERIES, retrieve
from app.pipeline.segment import segment
from scripts.ocr_pipeline.paraphrase import count_hits, paraphrase

GOLDSET = Path("eval/retrieval_goldset.json")
KS = (1, 3, 5)


def squash(s: str) -> str:
    """비교용 형태 — 공백과 소프트하이픈을 걷어낸다.

    PDF는 문장 중간에 줄바꿈을 넣고 정답지는 canonical Markdown에서 왔다.
    줄바꿈 위치가 다를 뿐인데 불일치로 세면 지표가 거짓이 된다.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", s).replace("­", ""))


@dataclass
class Doc:
    contract_id: str
    chunks: list
    squashed: list[str]
    full_squashed: str
    answers: dict[str, list[dict]]


@dataclass
class Tally:
    hit: dict[int, int] = field(default_factory=lambda: dict.fromkeys(KS, 0))
    total: int = 0
    rank_miss: int = 0
    chunk_miss: int = 0
    extract_miss: int = 0


def load_docs(
    gold: dict, limit: int | None, do_embed: bool, rewrite: bool = False
) -> tuple[list[Doc], int]:
    """정답지의 계약들을 파싱해 평가 준비 상태로 만든다.

    `rewrite`가 켜지면 라벨 표현을 바꾼 held-out 변형을 만든다. 청크와 정답에
    **같은** 치환을 적용해야 회수 난이도만 달라지고 문자열 대조는 유지된다.
    임베딩은 치환 뒤에 계산해야 벡터가 바뀐 문장을 반영한다.
    """
    docs: list[Doc] = []
    changed = 0
    rows = gold["contracts"][:limit] if limit else gold["contracts"]
    for row in rows:
        pdf = Path(row["pdf_path"])
        d = extract_document(pdf.read_bytes())
        lang, full_text, clauses = segment(d.pages)
        chunks = build_chunks(clauses, lang, d.file_hash)
        answers = row["fields"]

        if rewrite:
            for c in chunks:
                changed += count_hits(c.text)
                # 평가 전용이라 char offset 은 맞추지 않는다. 회수 점수만 본다.
                c.text = paraphrase(c.text)
            full_text = paraphrase(full_text)
            answers = {
                f: [{**a, "text": paraphrase(a["text"])} for a in v]
                for f, v in answers.items()
            }

        if do_embed:
            embed_mod.attach_embeddings(chunks)

        docs.append(
            Doc(
                contract_id=row["contract_id"],
                chunks=chunks,
                squashed=[squash(c.text) for c in chunks],
                full_squashed=squash(full_text),
                answers=answers,
            )
        )
    return docs, changed


def evaluate(docs: list[Doc], semantic_weight: float, query_vectors, min_score: float):
    per_field: dict[str, Tally] = collections.defaultdict(Tally)
    examples: list[tuple[str, str, str, str]] = []

    for doc in docs:
        by_id = {c.chunk_id: i for i, c in enumerate(doc.chunks)}
        fields = retrieve(
            doc.chunks,
            top_k=max(KS),
            min_score=min_score,
            semantic_weight=semantic_weight,
            query_vectors=query_vectors,
        )
        for name, answers in doc.answers.items():
            ranked = [by_id[h.chunk_id] for h in fields.get(name, [])]
            for ans in answers:
                t = per_field[name]
                t.total += 1
                a = squash(ans["text"])

                for k in KS:
                    if any(a in doc.squashed[i] for i in ranked[:k]):
                        t.hit[k] += 1

                if any(a in doc.squashed[i] for i in ranked[: max(KS)]):
                    continue
                # 왜 못 찾았는지 가른다
                if any(a in s for s in doc.squashed):
                    t.rank_miss += 1
                    verdict = "rank_miss"
                elif a in doc.full_squashed:
                    t.chunk_miss += 1
                    verdict = "chunk_miss"
                else:
                    t.extract_miss += 1
                    verdict = "extract_miss"
                if len(examples) < 12:
                    examples.append((verdict, doc.contract_id, name, ans["text"][:60]))

    return per_field, examples


def report(per_field: dict[str, Tally], label: str) -> None:
    print(f"\n=== {label} ===")
    head = f"{'필드':13}{'정답':>5}" + "".join(f"{f'@{k}':>8}" for k in KS)
    print(head + f"{'점수식':>9}{'청킹':>7}{'추출':>7}")
    agg = Tally()
    for name in sorted(per_field):
        t = per_field[name]
        agg.total += t.total
        for k in KS:
            agg.hit[k] += t.hit[k]
        agg.rank_miss += t.rank_miss
        agg.chunk_miss += t.chunk_miss
        agg.extract_miss += t.extract_miss
        cells = "".join(f"{t.hit[k] / t.total * 100:>7.1f}%" for k in KS)
        print(
            f"  {name:11}{t.total:>5}{cells}"
            f"{t.rank_miss:>9}{t.chunk_miss:>7}{t.extract_miss:>7}"
        )
    cells = "".join(f"{agg.hit[k] / agg.total * 100:>7.1f}%" for k in KS)
    print(
        f"  {'전체':11}{agg.total:>4}{cells}"
        f"{agg.rank_miss:>9}{agg.chunk_miss:>7}{agg.extract_miss:>7}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="앞에서 N건만")
    ap.add_argument("--min-score", type=float, default=0.15)
    ap.add_argument(
        "--sweep",
        nargs="+",
        type=float,
        metavar="W",
        help="의미 가중치를 여러 개 비교한다. 임베딩이 필요하다.",
    )
    ap.add_argument(
        "--paraphrase",
        action="store_true",
        help="라벨 표현을 바꾼 held-out 변형으로 평가한다. 어휘 패턴이 이 코퍼스에 "
        "맞춰져 있어서, 표현이 다른 실제 계약서를 흉내내려면 이 모드가 필요하다.",
    )
    args = ap.parse_args()

    if not GOLDSET.exists():
        print(
            "정답지가 없다. 먼저 scripts/build_goldset.py 를 실행한다.", file=sys.stderr
        )
        return 1
    gold = json.loads(GOLDSET.read_text(encoding="utf-8"))

    weights = args.sweep or [0.0]
    need_embed = any(w > 0 for w in weights)
    if need_embed and not embed_mod.is_available():
        print(
            "의미 가중치를 쓰려면 requirements-ml.txt 가 필요하다. 어휘 단독으로 돌린다.",
            file=sys.stderr,
        )
        weights, need_embed = [0.0], False

    t0 = time.perf_counter()
    docs, changed = load_docs(gold, args.limit, need_embed, args.paraphrase)
    print(f"문서 {len(docs)}건 준비 {time.perf_counter() - t0:.0f}s")
    if args.paraphrase:
        print(f"라벨 표현 치환 {changed}곳 — held-out 변형으로 평가한다")

    query_vectors = None
    if need_embed:
        names = list(FIELD_QUERIES)
        vecs = embed_mod.embed_queries([FIELD_QUERIES[n] for n in names])
        query_vectors = dict(zip(names, vecs, strict=True))

    for w in weights:
        per_field, examples = evaluate(docs, w, query_vectors, args.min_score)
        label = "어휘 단독 (lexical-v0)" if w == 0 else f"hybrid  semantic_weight={w}"
        report(per_field, label)

    if examples:
        print("\n실패 예시 (판정 · 계약 · 필드 · 정답 앞부분)")
        for v, cid, name, text in examples:
            print(f"  [{v:12}] {cid} {name:12} {text!r}")

    for f, why in gold["unevaluable_fields"].items():
        print(f"\n[측정 불가] {f} — {why}")

    if args.paraphrase:
        print(
            "\n[held-out] 라벨 표현만 바꾸고 날짜·국가·금액 같은 내용어는 그대로 뒀다."
            "\n           어휘가 흔들릴 때 의미검색이 얼마나 메우는지를 보는 것이 목적이다."
        )
    else:
        print(
            "\n[주의] 어휘 패턴을 이 합성데이터 표현에 맞춰 썼으므로 위 수치는 낙관적 상한이다."
            "\n       실제 계약서가 다른 표현을 쓰면 떨어진다."
            "\n       가중치는 --paraphrase 로 잰 값을 근거로 정한다."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

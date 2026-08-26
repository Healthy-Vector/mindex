"""P4 pgvector 자연어 검색 — 샌드박스 시드/조회 도구.

팀 공용 mindex-db 의 contract_chunk 를 건드리지 않고, 별도 1회용 Postgres
컨테이너에서 pgvector 동작(<=> 연산자, HNSW)을 검증한다.

## 준비

    docker run -d --name mindex-pgvector-sandbox \\
      -e POSTGRES_PASSWORD=sandbox -e POSTGRES_DB=sandbox \\
      -p 5544:5432 pgvector/pgvector:0.8.1-pg17

## 사용

    python scripts/pgvector_sandbox.py setup
    python scripts/pgvector_sandbox.py seed --count 20
    python scripts/pgvector_sandbox.py list
    python scripts/pgvector_sandbox.py query "재허락에 사전 동의가 필요한 계약"
    python scripts/pgvector_sandbox.py explain "일본 독점 배급"

`seed`는 실제 파이프라인(`app.pipeline.retrieve_contract_chunks`)을 그대로 호출한다 —
임베딩을 별도로 다시 만들지 않고, Task1이 실제로 만드는 것과 같은 경로로 생성한다.

## 왜 안전한가

- `docker-compose.yml`·`sql/init/`를 건드리지 않는다. 팀 컨테이너와 무관.
- `pytest.ini`가 `testpaths = tests`로 고정돼 있어 pytest가 이 파일을 수집하지
  않는다 — CI가 이 스크립트를 실행할 일이 없다.
- 무거운 import(`app.pipeline`, `sentence_transformers`)는 실제로 쓰는 명령의
  함수 안에서만 한다. `python scripts/pgvector_sandbox.py --help`만으로는 모델을
  안 띄운다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2
from pgvector.psycopg2 import register_vector

DEFAULT_DSN = "postgresql://postgres:sandbox@localhost:5544/sandbox"
MANIFEST = Path("testdata/k-rights/manifests/contract_pdf_manifest.json")
TESTDATA = Path("testdata/k-rights")

# scripts/ocr_pipeline/make_handoff_samples.py 가 이미 채운 10건 —
# docs/handoff/samples/ 의 공식 인계 샘플과 안 겹치게 피한다.
EXISTING_10 = {
    "CTR-KO-0001", "CTR-EN-0001", "CTR-JP-0001", "CTR-EN-0017", "CTR-JP-0002",
    "CTR-EN-0006", "CTR-KO-0014", "CTR-KO-0015", "CTR-JP-0015", "CTR-KO-0006",
}


def _connect(dsn: str):
    conn = psycopg2.connect(dsn)
    register_vector(conn)
    return conn


def cmd_setup(args: argparse.Namespace) -> None:
    # register_vector()는 vector 타입의 OID를 조회하므로 CREATE EXTENSION 이후에만
    # 쓸 수 있다 — 이 함수만 register 없이 직접 연결한다.
    conn = psycopg2.connect(args.dsn)
    with conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sandbox_chunk (
                id           bigserial PRIMARY KEY,
                contract_id  text NOT NULL,
                clause_no    text,
                label        text NOT NULL,
                chunk_text   text NOT NULL,
                embedding    vector(1024)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS sandbox_chunk_hnsw "
            "ON sandbox_chunk USING hnsw (embedding vector_cosine_ops)"
        )
    conn.close()
    print("setup 완료 — sandbox_chunk 테이블 + HNSW 인덱스")


def _load_manifest_rows() -> list[dict]:
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("contracts")
    return rows


def _pick_contract_ids(count: int) -> list[str]:
    """count 개를 언어별로 고르게 섞어 고른다.

    contract_id 오름차순 정렬만 하면 EN이 알파벳상 먼저 나와 첫 count개가
    EN 일색이 된다. F11(다국어 검색)을 시험하려면 KO/EN/JP가 섞여 있어야
    의미가 있다.
    """
    rows = _load_manifest_rows()
    by_lang: dict[str, list[str]] = {}
    for r in rows:
        cid = r["contract_id"]
        if cid in EXISTING_10:
            continue
        by_lang.setdefault(r["language"], []).append(cid)
    for ids in by_lang.values():
        ids.sort()

    picked: list[str] = []
    langs = sorted(by_lang)  # ["EN", "JP", "KO"] — 결정론적 순서
    i = 0
    while len(picked) < count and any(by_lang.values()):
        lang = langs[i % len(langs)]
        if by_lang[lang]:
            picked.append(by_lang[lang].pop(0))
        i += 1
    return picked


def cmd_seed(args: argparse.Namespace) -> None:
    from app.pipeline import retrieve_contract_chunks  # 무거운 임포트: 여기서만

    by_id = {r["contract_id"]: r for r in _load_manifest_rows()}
    ids = _pick_contract_ids(args.count)

    conn = _connect(args.dsn)
    inserted = 0
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sandbox_chunk")  # 재실행 시 중복 방지
        for cid in ids:
            pdf = TESTDATA / by_id[cid]["pdf_path"]
            bundle = retrieve_contract_chunks(pdf.read_bytes(), file_name=pdf.name)
            n = 0
            with conn.cursor() as cur:
                for c in bundle.chunks:
                    if c.embedding is None:
                        continue
                    label = f"{cid} · {c.clause_no}"
                    if c.clause_title:
                        label += f" ({c.clause_title})"
                    cur.execute(
                        "INSERT INTO sandbox_chunk "
                        "(contract_id, clause_no, label, chunk_text, embedding) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (cid, c.clause_no, label, c.text, c.embedding),
                    )
                    n += 1
            inserted += n
            print(f"  {cid}  {bundle.document.language}  청크 {n}개 적재")
    conn.close()
    print(f"총 {inserted}개 청크 · 계약서 {len(ids)}건 적재 완료")


def _embed_query(text: str) -> list[float]:
    from app.pipeline import embed as embed_mod  # 무거운 임포트: 여기서만

    return embed_mod.embed_queries([text])[0]


def cmd_query(args: argparse.Namespace) -> None:
    qvec = _embed_query(args.text)
    conn = _connect(args.dsn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT label, chunk_text, embedding <=> CAST(%s AS vector) AS dist "
            "FROM sandbox_chunk ORDER BY dist ASC LIMIT %s",
            (qvec, args.top_k),
        )
        rows = cur.fetchall()
    conn.close()
    print(f'질의: "{args.text}"\n')
    for label, text, dist in rows:
        score = 1.0 - dist
        preview = text[:60].replace("\n", " ")
        print(f"  score={score:.3f}  {label}\n    {preview}...")


def cmd_list(args: argparse.Namespace) -> None:
    """계약서별 청크 수 요약 — 지금 뭐가 들어 있는지 빠르게 확인."""
    conn = _connect(args.dsn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT contract_id, count(*) FROM sandbox_chunk "
            "GROUP BY contract_id ORDER BY contract_id"
        )
        rows = cur.fetchall()
    conn.close()
    total = sum(n for _, n in rows)
    for cid, n in rows:
        print(f"  {cid:<14} {n:>3}청크")
    print(f"\n계약서 {len(rows)}건 · 청크 {total}개")


def cmd_explain(args: argparse.Namespace) -> None:
    qvec = _embed_query(args.text)
    conn = _connect(args.dsn)
    with conn.cursor() as cur:
        cur.execute(
            "EXPLAIN ANALYZE "
            "SELECT label FROM sandbox_chunk ORDER BY embedding <=> CAST(%s AS vector) LIMIT %s",
            (qvec, args.top_k),
        )
        for row in cur.fetchall():
            print(row[0])
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup").set_defaults(func=cmd_setup)

    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--count", type=int, default=20)
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("list").set_defaults(func=cmd_list)

    p_query = sub.add_parser("query")
    p_query.add_argument("text")
    p_query.add_argument("--top-k", type=int, default=5)
    p_query.set_defaults(func=cmd_query)

    p_explain = sub.add_parser("explain")
    p_explain.add_argument("text")
    p_explain.add_argument("--top-k", type=int, default=5)
    p_explain.set_defaults(func=cmd_explain)

    args = ap.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

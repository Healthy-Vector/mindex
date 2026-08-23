# ruff: noqa: E402 — 벤치마크 스크립트다. 실행 단계를 나누어 보여주려고
# 무거운 import를 해당 단계 위치에 둔다. 이건 의도된 배치다.
"""
03. 임베딩 + pgvector 적재
실행 위치: [맥]  (모델 ~2.2GB 다운로드, RAM ~3GB — EC2에서 돌리지 말 것)

- OCR 결과(없으면 원문)를 조항 단위로 분할
- multilingual-e5-large 로 1024차원 임베딩 (RFP SFR-005 확정 모델)
- 공유 DB(5432)의 p1_test_ocr_chunk 테이블에 적재 + HNSW 인덱스

⚠️ e5 계열 필수 규칙: 문서는 "passage: ", 질의는 "query: " 접두사를 붙여야
   학습된 벡터 공간과 일치한다. 빼먹으면 검색 품질이 떨어진다.
"""

import os
import re
from pathlib import Path

OUT = Path(__file__).parent / "out"

# ── 입력 선택: OCR 결과 우선, 없으면 원문 ─────────────────────
src = None
for cand in ["ocr_output_PaddleOCR.txt", "ocr_output_Tesseract.txt", "ground_truth.txt"]:
    if (OUT / cand).exists():
        src = OUT / cand
        break
text = src.read_text(encoding="utf-8")
print(f"입력: {src.name}")

# ── 조항 단위 분할 (제N조 기준 — parsing 모듈과 동일 개념) ────
parts = re.split(r"(?=제\s*\d+\s*조)", text)
chunks = [p.strip() for p in parts if p.strip()]
print(f"조항 청크: {len(chunks)}개")

# ── 임베딩 ─────────────────────────────────────────────────
from sentence_transformers import SentenceTransformer

print("모델 로딩 (최초 실행 시 ~2.2GB 다운로드)...")
model = SentenceTransformer("intfloat/multilingual-e5-large")
vecs = model.encode([f"passage: {c}" for c in chunks], normalize_embeddings=True)
print(f"임베딩 완료: {vecs.shape}")  # (N, 1024)

# ── DB 적재 ────────────────────────────────────────────────
import psycopg2

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "15.164.171.220"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "mindex"),
    user=os.getenv("PGUSER", "mindex"),
    # password 생략 → ~/.pgpass 자동 사용
)
conn.autocommit = True
cur = conn.cursor()

# 공유 DB 규칙: 실험 테이블은 p1_ 접두사
cur.execute("""
CREATE TABLE IF NOT EXISTS p1_test_ocr_chunk (
    id         serial PRIMARY KEY,
    source     text,
    clause_no  int,
    chunk_text text,
    embedding  vector(1024)
);
""")
cur.execute("TRUNCATE p1_test_ocr_chunk;")

for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
    cur.execute(
        "INSERT INTO p1_test_ocr_chunk (source, clause_no, chunk_text, embedding) VALUES (%s,%s,%s,%s)",
        (src.name, i, chunk, vec.tolist()),
    )

# HNSW 인덱스 (RFP 확정 방식, 코사인 거리)
cur.execute("""
CREATE INDEX IF NOT EXISTS p1_test_ocr_chunk_hnsw
ON p1_test_ocr_chunk USING hnsw (embedding vector_cosine_ops);
""")

cur.execute("SELECT count(*) FROM p1_test_ocr_chunk;")
print(f"적재 완료: {cur.fetchone()[0]}행 + HNSW 인덱스")
print("다음: python3 04_search_test.py")

"""
04. 유사도 검색 검증
실행 위치: [맥]

세 가지를 확인한다:
1. 의미 검색 — 키워드가 달라도 관련 조항을 찾는가
2. 다국어 공간 — 일본어 질의로 한국어 조항을 찾는가
3. HNSW 인덱스 사용 여부

⚠️ 이 검증의 범위는 SFR-009-C(의미 검색) 다.
   충돌 판정(SFR-007)에는 벡터 유사도를 쓰지 않는다 —
   「정합성 점검 리스트」 E-3 결정: EXCLUDE 판정은 content_id 등 정형값 비교만 사용.
   벡터는 "사람이 관련 조항을 찾아보는" 용도다.
"""

import os
from sentence_transformers import SentenceTransformer
import psycopg2

QUERIES = [
    ("계약 기간이 언제까지야?",           "제3조(계약 기간) 이 나와야 함"),
    ("다른 회사에 다시 빌려줄 수 있어?",   "제5조(재허락 금지) — '재허락' 단어 없이도 찾는지"),
    ("冬のシグナルの日本配信権",           "다국어: 일본어 질의 → 한국어 조항 (SFR-009-C 검색 품질)"),
]

model = SentenceTransformer("intfloat/multilingual-e5-large")

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "15.164.171.220"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "mindex"),
    user=os.getenv("PGUSER", "mindex"),
)
cur = conn.cursor()

for q, expect in QUERIES:
    vec = model.encode(f"query: {q}", normalize_embeddings=True)  # e5: query 접두사
    cur.execute(
        """
        SELECT clause_no, left(chunk_text, 60), 1 - (embedding <=> %s::vector) AS sim
        FROM p1_test_ocr_chunk
        ORDER BY embedding <=> %s::vector
        LIMIT 3
        """,
        (vec.tolist(), vec.tolist()),
    )
    print(f"\n질의: {q}")
    print(f"기대: {expect}")
    for rank, (no, snippet, sim) in enumerate(cur.fetchall(), 1):
        print(f"  {rank}위 [유사도 {sim:.3f}] 청크{no}: {snippet}...")

# HNSW 인덱스가 실제로 쓰이는지
cur.execute("""
EXPLAIN SELECT clause_no FROM p1_test_ocr_chunk
ORDER BY embedding <=> (SELECT embedding FROM p1_test_ocr_chunk LIMIT 1) LIMIT 3;
""")
plan = "\n".join(r[0] for r in cur.fetchall())
print("\n실행 계획:", "HNSW 사용 ✅" if "hnsw" in plan.lower() else "⚠️ 순차 스캔 (데이터가 적으면 정상)")

# 정리 안내
print("""
테스트 후 정리(선택):
  psql -h 15.164.171.220 -p 5432 -U mindex -d mindex -c "DROP TABLE IF EXISTS p1_test_ocr_chunk;"
""")

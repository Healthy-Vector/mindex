-- 00_extensions.sql — 확장 설치 (D-10)
--
-- vector 확장은 여기 두지 않는다. 04_vector.sql로 격리해야
-- pgvector 없는 순수 PostgreSQL 16에서도 충돌 판정(01~03)이 돈다.
-- 검증 환경 선택지를 넓히기 위한 의도적 분리다.

-- EXCLUDE 제약이 스칼라 타입(bigint·char(2)·enum)을 GiST 인덱스에
-- 넣으려면 btree_gist가 opclass를 제공해야 한다.
-- 스파이크 1번에서 bigint·char(2)·text 전부 실측 확인했다.
CREATE EXTENSION IF NOT EXISTS btree_gist;

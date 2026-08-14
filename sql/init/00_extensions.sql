-- 00_extensions.sql — 확장 설치 (D-10)
--
-- vector 확장은 여기 두지 않는다. 04_vector.sql로 격리해야
-- pgvector 없는 순수 PostgreSQL 16에서도 충돌 판정(01~03)이 돈다.
-- 검증 환경 선택지를 넓히기 위한 의도적 분리다.

-- EXCLUDE 제약이 스칼라 타입(uuid·bigint·char(2)·enum)을 GiST 인덱스에
-- 넣으려면 btree_gist가 opclass를 제공해야 한다.
-- 스파이크 1번에서 uuid·bigint·char(2)·text 전부 실측 확인했다.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- D-20 — tenant.access_key_hash를 crypt()/gen_salt('bf')로 해싱하기 위함.
-- 앱이 해싱을 빠뜨려도 DB가 평문 저장을 거부하도록 CHECK로 형식을 강제한다 (P-4).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

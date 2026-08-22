-- mindex_staging — 최소권한 DB 롤 (SER-002, D-32)
--
-- 이 DB를 건드리는 접근 주체는 셋이다: 워커(OCR·LLM 처리, P1), 확정 API
-- 서버(tmpid로 extract_result를 읽어 운영 DB 저장 쿼리를 만드는 쪽, P4),
-- TTL 정리 배치. 하나의 공용 계정으로 다 접근하면 확정 API가 뚫렸을 때
-- pdf_blob의 PDF 원본 바이트까지 노출된다 — P-4(애플리케이션이 침해돼도
-- 데이터 무결성은 유지)를 DB 권한으로 강제한다.
--
-- 여기서는 NOLOGIN 롤로 "권한 경계"만 정의한다. 실제 로그인 계정(비밀번호
-- 포함)은 이 파일에 넣지 않는다 — sql/init은 docker-entrypoint-initdb.d로
-- 실행되어 이미지/저장소에 그대로 남고, .env와 마찬가지로 비밀번호를 커밋할
-- 수 없기 때문이다(CLAUDE.md 절대 규칙). 배포 환경에서 로그인 계정을 만들고
-- 아래 롤에 GRANT ... TO <login_role>로 소속시키는 건 배포(ops/P1) 책임이다.

-- ── 워커 (SKIP LOCKED 폴링 + OCR/LLM 처리 결과 기록) ─────────────
CREATE ROLE staging_worker NOLOGIN;
GRANT SELECT ON pdf_blob TO staging_worker;                 -- 처리 대상 원본 읽기
GRANT SELECT, UPDATE ON extract_job TO staging_worker;      -- 폴링·상태 갱신
GRANT INSERT, UPDATE ON extract_result TO staging_worker;   -- UPSERT

-- ── 확정 API (tmpid로 결과를 읽어 운영 DB 저장 쿼리에 병합) ──────
-- pdf_blob은 의도적으로 권한을 안 준다 — 확정 단계는 추출 결과(jsonb)만
-- 필요하고 PDF 원본 바이트는 필요 없다.
CREATE ROLE staging_confirm_api NOLOGIN;
GRANT SELECT ON extract_result TO staging_confirm_api;
GRANT SELECT ON extract_job TO staging_confirm_api;
GRANT UPDATE (consumed_at) ON extract_job TO staging_confirm_api;  -- 확정 완료 표시만

-- ── TTL 7일 정리 배치 (아직 워커/배치 자체는 미구현, 권한 경계만 선점) ──
CREATE ROLE staging_cleanup NOLOGIN;
GRANT SELECT ON pdf_blob TO staging_cleanup;
GRANT DELETE ON pdf_blob TO staging_cleanup;   -- CASCADE로 extract_job·extract_result 동반 삭제
GRANT SELECT ON extract_job TO staging_cleanup;

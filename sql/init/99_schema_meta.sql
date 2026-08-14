-- 99_schema_meta.sql — 스키마 버전 (D-10)
--
-- alembic을 도입하지 않는다. 3주 일정에 증분 마이그레이션 체계를 세우는 비용이
-- 이득보다 크고, 지금은 영속 데이터가 없어 `docker compose down -v` 손실 위험이 0이다.
--
-- 대신 이 테이블이 낡은 볼륨을 감지한다. docker-entrypoint-initdb.d는 pgdata
-- 볼륨이 비어 있을 때만 실행되므로, 스키마를 바꾸고 `-v` 없이 재기동하면
-- 낡은 스키마가 그대로 남는다. 테스트가 이 버전을 확인해 그 상황을 잡아낸다.
--
-- 부채: 합성 계약이 적재된 뒤에는 `down -v`를 못 쓴다.
-- 그 전에 alembic 베이스라인을 잡는 것이 8/27 일정의 실제 데드라인이다.

CREATE TABLE schema_meta (
    version     text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    note        text
);

INSERT INTO schema_meta (version, note) VALUES
    ('2026-08-12.1',
     'D-13 유통창구 5종 · D-14 암호화 대상 · D-15 국가코드 저장 · D-16 검수 스테이징 반영'),
    ('2026-08-14.1',
     'D-17 rights_grant status 체계(draft/review/provisional/complete/terminated, D-16 대체) · '
     'D-18 rights_grant_history 원장 + conflict_code · D-19 probe_rights_conflict/register_rights_grant 함수'),
    ('2026-08-14.2',
     'D-20 tenant 테이블(팀 공유 API 키, bcrypt 해시만 저장) + 각 테이블 tenant_id FK 추가 · '
     'D-21 rights_grant_history.ai_note → conflict_report jsonb로 교체');

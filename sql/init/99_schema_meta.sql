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
     'D-21 rights_grant_history.ai_note → conflict_report jsonb로 교체'),
    ('2026-08-14.3',
     'D-22 코드리뷰 반영 — contract_version 스냅샷 트리거 연결 · '
     'rights_grant_history.history_seq 제거(id로 전역 순서 보장) · '
     'register_rights_grant()가 parsed 행을 더 이상 UPDATE하지 않음(진짜 append-only) · '
     'change_log에서 rights_grant 트리거 제거(벡터 재생성과 무관)'),
    ('2026-08-18.1',
     'D-23 content → ip 테이블·컬럼 리네임'),
    ('2026-08-19.1',
     'D-24·D-25 리마스터 — rights_grant status 5값 단일 테이블 구조를 폐기하고 '
     'contract_document(PDF 버전) · rights_grant_candidate(AI 후보 staging) · '
     'conflict_result(DB 판정/AI 첨언 분리) · conflict_resolution(WAIVER/AMENDED/REJECTED) '
     '4개 테이블로 분리. rights_grant는 승인된 데이터만 담는 3-status(approved/final/'
     'terminated) 테이블로 축소. probe_rights_conflict/register_rights_grant를 '
     'detect_candidate_conflicts/register_candidate로 교체. WAIVER 승인 시 기존 '
     'rights_grant를 TERMINATED로 정리하는 트리거 신설(EXCLUDE는 절대 우회하지 않음) · '
     'contract.status=final 전환 검증 트리거 신설 · 복합 FK(D-09) 전면 적용 · '
     'Evidence Anchoring을 rights_grant_candidate 단일 출처로(NOT NULL 강제) · '
     'candidate_status 4값 + review_reason_kind 분리 · contract_chunk에 document_id 추가 · '
     'change_log 트리거를 contract에서 contract_document로 이동'),
    ('2026-08-19.2',
     'D-27 판정축 분리 + reason_code 정규화 — rights_type_kind ENUM(유통창구 5종)을 '
     'legal_right(법적 권리) x exploitation_mode(이용형태) 두 참조 테이블로 분리. '
     '둘 다 nested-set 좌표(lft/rgt -> span int4range)를 갖고, EXCLUDE가 등호가 아니라 '
     '&& 로 비교해 상위-하위 포함관계(R3/R4)까지 결정론적으로 차단한다. '
     'rights_grant에 span 2개를 비정규화하고 sync_rights_grant_spans() 트리거가 채운다 · '
     'statutory_right에 legal_right_code 추가(관할별 조문을 관할 중립 판정축에 연결) · '
     'right_mapping을 (legal_right x exploitation_mode x jurisdiction) 자문/검증표로 재정의 · '
     'conflict_code 테이블과 review_reason_kind ENUM을 reason_code 단일 마스터로 통합 '
     '(MISSING vs UNRESOLVED 구분, is_blocking/is_review_trigger/is_decision_reason 플래그) · '
     'conflict_result를 rights_evaluation(결과 1행) + rights_evaluation_reason(사유 N행)으로 분리, '
     'result_kind 4종(NORMAL/CONFLICT/REVIEW_REQUIRED/WARNING) 도입 · '
     'detect_candidate_conflicts를 evaluate_candidate로 교체 · '
     'conflict_resolution이 판정 사유 행을 가리키도록 변경'),
    ('2026-08-19.3',
     'D-28 화면 프로세스와 DB 호출 규약 — probe_rights() 신설. 화면의 `검증` 버튼이 '
     '부모 행(ip/contract/contract_document)과 candidate를 서브트랜잭션에 INSERT하고 '
     'evaluate_candidate()로 판정한 뒤 rights_grant에 직접 INSERT해 EXCLUDE를 실제로 '
     '검증한다. sentinel 예외(SQLSTATE MXP01)로 서브트랜잭션을 되돌려 호출자가 커밋 '
     '여부를 고를 수 없게 한다 — 롤백을 앱 규약이 아니라 구조로 강제한다. '
     'EXCLUDE와 check_exclusivity_conflict()가 모두 23P01+CONSTRAINT를 실어 보내므로 '
     'CONSTRAINT_NAME으로 어느 층이 잡았는지 구분해 반환한다(D-08, RFP 6.3.2) · '
     'LOW_CONFIDENCE의 is_blocking을 true→false로 내림. 사람 확인이 프로세스의 필수 '
     '단계라 등록을 막을 이유가 없고, true면 검수를 마친 후보가 영영 등록되지 못한다'),
    ('2026-08-19.4',
     'D-29 온프레미스 단일 회사 설치 경계 반영 — tenant 테이블, tenant_id 컬럼, '
     'tenant 복합 FK 및 tenant별 충돌 키를 제거. 회사 간 격리는 설치·DB 단위로 '
     '보장하고 사용자 인증/권한은 별도 애플리케이션 관심사로 둔다 · '
     'rights_grant_candidate의 source_page/source_clause/source_quote 단일 근거 컬럼을 '
     'candidate_evidence N행으로 분리(page_start/page_end/source_clause/source_quote). '
     'register_candidate()가 근거 1건 이상을 요구하며 probe_rights()도 후보 생성 뒤 '
     '근거 행을 생성하도록 변경'),
    ('2026-08-19.5',
     'D-28·D-29 프로세스 정합화 — probe_rights()가 단일 source 파라미터 대신 '
     'evidence JSON 배열을 받아 candidate_evidence N행을 검증하도록 변경. 최초 업로드는 '
     '오브젝트 스토리지와 앱 작업 데이터에만 두고, 검증은 전부 롤백하며, 실제 등록에서 '
     'contract → document → candidate → evidence → grant 순으로 ID를 받는 흐름을 문서화');

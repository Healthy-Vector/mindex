# HA 구성도 상세

전체 그림은 `docs/ha-design.md` 2절 참조. 여기서는 노드별 역할과 트래픽 흐름을 상세히 기술한다.

## 노드 구성 (목표, CR-01 발동 시)

| 노드 | 역할 | 스펙(예정) |
|---|---|---|
| Node 1 | Primary — 쓰기·읽기 처리 | OpenSQL, PostgreSQL 16.8 기반 |
| Node 2 | Standby (동기 복제 후보 1순위) | 동일 |
| Node 3 | Standby (동기 복제 후보 2순위) | 동일 |
| etcd ×3 | 클러스터 상태 저장소, 리더 선출 합의 | Patroni가 참조 |

## 지금(단일노드안) 실제 구성
- OpenProxy·Patroni·etcd는 아직 배치하지 않음 (라이선스 1대 제약)
- 이 상태에서도 EXCLUDE 제약조건·백업·PITR은 전부 정상 동작 (실제로 검증 완료 — `tests/test_conflict_constraint.py`)

## TODO — OpenSQL 실물 확인 후 채울 것

- [ ] OpenSQL 공식 매뉴얼 기준 Patroni 권장 배포 방식 확인 (`docs.tibero.com/tmaxopensql`)
- [ ] etcd 최소 노드 수·리소스 요구사항 확인
- [ ] OpenProxy 실제 설정 파라미터(현재 알려진 건 기본 풀 크기 10) 확인

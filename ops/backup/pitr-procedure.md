# 백업·PITR 복구 절차 — ECR-003 · TER-005 · PER-002

**단일노드안에서 무중단(HA)을 대체하는 핵심 실증.** 서버가 1대라 Failover는 못 보여줘도, "장애가 나도 데이터는 안 잃는다"는 이걸로 증명한다.

**2026-08-08 실제 리허설 완료 — 아래 절차 그대로 재현 성공.**

## 방식

OpenBackup이 PITR(Point-In-Time Recovery)을 기본 지원한다 (RFP v1.6 확인). 개발 단계(Docker pgvector 이미지)에서는 표준 PostgreSQL 도구로 동일 절차를 리허설하고, OpenSQL 실물 확보 시 OpenBackup 명령으로 교체한다.

`docker-compose.yml`에 WAL 아카이빙 설정(`archive_mode=on`, `archive_command`, `archive` 볼륨)을 반영해뒀다.

## 개발 환경 리허설 절차 (실제 검증된 순서)

```bash
# 0. archive 볼륨 소유권 맞추기 (필수 — 도커 볼륨 기본 소유자는 root라
#    컨테이너 안 postgres 계정이 쓰기 실패함. 리허설 중 실제로 걸렸던 함정)
docker run --rm -v mindex_archive:/archive postgres:16 chown -R postgres:postgres /archive

# 1. 베이스 백업
docker exec mindex-db pg_basebackup -U mindex -D /tmp/basebackup -Fp -Xs -P
docker cp mindex-db:/tmp/basebackup ./pitr_basebackup

# 2. WAL 아카이빙 확인
docker exec mindex-db psql -U mindex -c "SHOW archive_mode;"

# 3. "복구 목표 시점" 기록
docker exec mindex-db psql -U mindex -d mindex -c "SELECT now();"

# 4. 장애 시뮬레이션 — 데이터 삭제
docker exec mindex-db psql -U mindex -d mindex -c "DELETE FROM rights_grant WHERE id = 1;"

# 5. 진행 중이던 WAL 세그먼트 강제 아카이빙 (작은 트랜잭션은 16MB 세그먼트를
#    안 채워서 자동으로 archive 안 됨 — 강제로 밀어내야 함)
docker exec mindex-db psql -U mindex -c "SELECT pg_switch_wal();"

# 6. 복구용 볼륨 준비 (베이스 백업 복사 + 소유권 맞춤)
docker volume create mindex_restore_data
docker run --rm \
  -v "$(pwd)/pitr_basebackup:/backup:ro" \
  -v mindex_restore_data:/restore \
  postgres:16 \
  bash -c "cp -a /backup/. /restore/ && chown -R postgres:postgres /restore && chmod 700 /restore"

# 7. 복구 목표 시점 설정 (3번에서 기록한 시각으로 교체)
docker run --rm \
  -v mindex_restore_data:/restore \
  postgres:16 \
  bash -c "touch /restore/recovery.signal && cat >> /restore/postgresql.auto.conf << 'EOF'
restore_command = 'cp /archive/%f %p'
recovery_target_time = '<3번에서 기록한 시각>'
recovery_target_action = 'promote'
EOF"

# 8. 복구 컨테이너 기동
docker run -d --name mindex-restore \
  -v mindex_restore_data:/var/lib/postgresql/data \
  -v mindex_archive:/archive:ro \
  -p 5433:5432 \
  postgres:16
docker logs -f mindex-restore   # "database system is ready to accept connections" 확인

# 9. 복구 검증 — 삭제된 데이터 존재 + EXCLUDE 제약조건 재동작 확인
docker exec mindex-restore psql -U mindex -d mindex -c "SELECT * FROM rights_grant WHERE id = 1;"
docker exec mindex-restore psql -U mindex -d mindex -c "
INSERT INTO rights_grant (tenant_id, contract_id, content_id, territory, rights_type, period, is_exclusive)
VALUES ('<복구된 행과 동일 tenant_id>',1,1,'<동일 territory>','STREAMING','<겹치는 기간>',true);
"
# → ERROR: conflicting key value violates exclusion constraint "no_exclusive_overlap" 나와야 정상

# 10. 뒷정리 (테스트 전용 리소스, 개발 DB에는 영향 없음)
docker rm -f mindex-restore
docker volume rm mindex_restore_data
```

## RTO 측정 (PER-002)

| 측정 항목 | 목표 | 실측 (2026-08-08) |
|---|---|---|
| 엔진 자체 WAL 재생(REDO) 시간 | — | **0.04초** (postgres 로그 `redo starts`~`consistent recovery state reached` 구간) |
| 복구 시점 정확도 | 삭제 직전에서 정지 | **통과** — 로그에 `recovery stopping before commit of transaction ..., time <목표 시각>`로 정확히 삭제 트랜잭션 직전 정지 확인 |
| 베이스 백업 + 전체 복구 절차(수동) 소요 시간 | **1시간 이내** | **수 분 이내** (베이스 백업 31MB 기준, 절차 0~10단계 전체) |
| 복구 후 제약조건 정상 동작 확인 | 통과/실패 | **통과** — 신규/기존 데이터 양쪽 다 EXCLUDE 제약조건 재현됨 |

## 알아둘 것 (실제로 겪은 함정)

- **archive 볼륨 권한**: 새로 만든 도커 볼륨은 기본 소유자가 root라, 컨테이너 안 postgres 계정이 쓰기 실패한다. 0단계의 `chown`을 빼먹으면 `archive_command`가 계속 `Permission denied`로 실패하고 복구 시 WAL을 못 찾는다.
- **작은 트랜잭션은 자동 아카이빙 안 됨**: WAL은 16MB 세그먼트 단위로만 아카이빙되므로, 트래픽이 적은 개발/테스트 환경에서는 `pg_switch_wal()`로 강제로 밀어줘야 한다.
- **`pgdata` 볼륨은 `docker compose down/up`으로 안 지워짐**: 이전 테스트 데이터가 남아있을 수 있으니, 복구 검증 시 어떤 행이 실제로 삭제/복구됐는지 매번 재확인해야 한다.

## TODO

- [x] `docker-compose.yml`에 WAL 아카이빙 설정 추가
- [x] 리허설 실제 수행 및 소요 시간 기입 (A3 검수 기준 — 9.3)
- [ ] OpenSQL 실물 확보 시 `pg_basebackup` → OpenBackup 명령으로 교체, 동일 리허설 재수행
- [ ] `docs.tibero.com/tmaxopensql`에서 OpenBackup 실제 명령어 문법 확인

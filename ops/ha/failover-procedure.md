# Failover 절차서

**목표 구성(3노드) 기준. 지금은 단일노드안이라 실제 Failover는 CR-01 발동 후 수행한다.**

## 자동 Failover 시나리오

| 단계 | 동작 | 소요 시간(목표) |
|---|---|---|
| 1 | Primary(Node 1) 장애 발생 (프로세스 kill 또는 네트워크 단절) | — |
| 2 | Patroni가 etcd TTL(기본 30초) 만료로 Primary 응답 없음 감지 | ~30초 |
| 3 | etcd 합의로 Standby 중 가장 최신 데이터를 가진 노드를 새 Primary로 선출 | ~수 초 |
| 4 | 새 Primary가 승격, 나머지 Standby가 새 Primary를 추적하도록 재구성 | ~수 초 |
| 5 | OpenProxy가 새 Primary로 트래픽 전환 | 즉시(헬스체크 주기에 따름) |
| 6 | 애플리케이션은 재연결 시 정상 응답 수신 | — |

**목표 RTO(복구 소요 시간): 1시간 이내** (PER-002, 백업·PITR 기준 실측치는 `ops/backup/pitr-procedure.md` 참조)

## 수동 개입이 필요한 경우

- 두 개 이상 노드 동시 장애 (쿼럼 상실)
- etcd 클러스터 자체 장애
- 이 경우 `patronictl` 로 수동 상태 확인 후 개입:

```bash
patronictl -c ops/ha/patroni.yml list
patronictl -c ops/ha/patroni.yml failover mindex-cluster
```

## 검증 방법 (CR-01 발동 시 실제로 수행할 테스트)

1. Primary 노드에서 `kill -9 <postgres PID>` 실행
2. Failover 완료까지 시간 측정
3. 새 Primary에 접속하여 직전 트랜잭션까지 데이터 유실 없는지 확인
4. `rights_grant`의 EXCLUDE 제약조건이 새 Primary에서도 정상 동작하는지 재검증 (TER-002)

## TODO

- [ ] 실제 3노드 확보 후 위 시나리오 실측, 이 문서에 실측치로 갱신
- [ ] OpenSQL 매뉴얼의 Failover 관련 권장 파라미터 대조

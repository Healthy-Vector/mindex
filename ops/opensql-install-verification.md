# OpenSQL 설치·라이선스 검증 절차

**출처**: docs.tibero.com/tmaxopensql 공식 매뉴얼 (2026-08-08 확인)
**목적**: OpenSQL 실물 설치 완료 후, 팀원들에게 "정상 설치 + 라이선스 유효"를 보여주기 위한 검증 절차. 라이선스 확보 전까지는 미착수 상태.

## 전제

OpenSQL은 Docker 컨테이너가 아니라 **실제 서버(물리 서버 또는 VM)**에 설치한다 (지원 OS: Rocky Linux 8.x/9.x, RHEL 8.x/9.x, Oracle Linux/AlmaLinux 8.x/9.x, Ubuntu 22.04/24.04). `opensql-installer`(Python 기반 인스톨러)로 로컬 또는 원격(SSH 일괄) 설치하며, 라이선스 XML 파일을 `opensql-installer/licenses/`에 배치해야 설치가 진행된다.

## 1. 서비스가 실제로 떠 있는지 확인

```bash
sudo systemctl status opensql-etcd
ps aux | grep patroni
pgrep -f openproxy
patronictl -c /home/opensql/etc/patroni.yml list
```

## 2. 포트가 열려있는지 확인

```bash
ss -tunlp | grep -E "5432|6432|6433|2379|2380|8008"
```

| 포트 | 컴포넌트 |
|---|---|
| 5432 | PostgreSQL |
| 2379/2380 | etcd (client/peer) |
| 8008 | Patroni REST API |
| 6432/6433 | OpenProxy (client/admin) |

## 3. 실제 DB 접속 테스트

```bash
psql -h 127.0.0.1 -p 5432 -U postgres     # 직접 접속
psql -h 127.0.0.1 -p 6432 -U postgres     # OpenProxy 경유 접속
```

## 4. 라이선스 정상 로드 확인 — 핵심

```bash
echo $OPENSQL_LICENSE_PATH
cat $OPENSQL_LICENSE_PATH | grep edition
```

설치 스크립트가 6단계("라이선스 확인")에서 라이선스 파일 존재·경로·signature 일치를 자동 검증한다. 이 단계에서 에러 없이 통과했다는 것 자체가 라이선스 유효성의 1차 증거다. 지원 에디션은 `standard` / `enterprise` / `ai` 3종.

## 5. "이게 진짜 OpenSQL"이라는 시각적 증거 — 팀 공유용으로 제일 설득력 있음

```sql
\dx
```

일반 오픈소스 PostgreSQL에는 없는 OpenSQL 전용 확장이 보이면 확정 증거:

- `o2` (Oracle 호환성)
- `tibero_fdw`
- `opencrypto`
- `pgvectorscale`
- `credcheck`
- `pg_profile`

## 트러블슈팅 참고 (매뉴얼 기준)

| 증상 | 원인 |
|---|---|
| `라이선스 파일/디렉토리를 찾을 수 없습니다` | `opensql-installer/licenses/`에 XML 미배치 또는 파일명 불일치 |
| `라이선스 edition을 확인할 수 없습니다` | XML에 `<edition>` 태그 누락 |
| `라이선스 signature가 중복됩니다` | 여러 노드에 같은 라이선스 XML 사용 (노드마다 달라야 함) |
| `OPENSQL_LICENSE_PATH 미설정/불일치` | 환경 변수 설정 단계(`~/.opensqlrc`) 확인 필요 |

## TODO

- [ ] 라이선스 확보 후 실제 설치 진행 (단일노드안: `--mode single`)
- [ ] 위 1~5번 절차 실제로 수행하고 스크린샷/로그 팀 공유

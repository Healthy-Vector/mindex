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

## 6. IP 유사도 검색용 pg_trgm 확인

OpenSQL 3은 PostgreSQL 기반이고 PostgreSQL Extension Framework를 사용한다. 다만 OpenSQL 매뉴얼은 `pg_trgm`의 패키지 포함 여부를 별도로 보장하지 않으므로, 라이선스 환경에서 다음 순서로 확인한다.

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name = 'pg_trgm';

CREATE EXTENSION IF NOT EXISTS pg_trgm;

SELECT similarity('겨울왕국', '겨울왕국 시즌2') AS title_similarity,
       strict_word_similarity('겨울왕국', '겨울왕국 시즌2') AS word_similarity;

\dx pg_trgm
```

첫 조회 결과가 없으면 해당 OpenSQL PostgreSQL 버전에 맞는 contrib 패키지에 `pg_trgm.control`이 포함되도록 설치 이미지·패키지를 보완한 후 init SQL을 다시 적용한다. HA 구성에서는 모든 DB 노드에 같은 확장 파일 버전이 설치되어 있어야 한다.

신규 DB 컨테이너는 최초 기동 시 `sql/init/08_ip_search.sql`을 자동 실행한다. 이미 생성된 DB에는 DB 확장 생성 권한이 있는 계정으로 다음 파일을 한 번 적용한다.

```bash
psql "postgresql://<admin>:<password>@<host>:<port>/<database>" \
  -v ON_ERROR_STOP=1 -f sql/init/08_ip_search.sql
```

적용 후 API의 `GET /api/ips?q=겨울왕국%20시즌2` 또는 `GET /api/ips/match?q=겨울왕국%20시즌2`로 검색 결과와 `score`를 확인한다. 애플리케이션 계정은 초기 설정이 끝난 뒤 `CREATE EXTENSION` 권한이 필요하지 않다.

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
- [ ] 6번 `pg_trgm` 가용성·유사도 쿼리 확인

# OpenProxy 연결 중계 — ECR-002 (Tier 2)

애플리케이션과 DB 사이에서 연결을 중계해, 장애 시에도 연결을 유지하기 위한 커넥션 프록시.

## 확인된 사실

- 기본 커넥션 풀 크기: **10** (RFP v1.4 매뉴얼 확인 — 초기 추정 50에서 정정)
- 단일노드안에서는 앱이 DB에 직접 접속 (OpenProxy 미사용)
- CR-01 발동(다노드 확보) 시, 앱이 OpenProxy 엔드포인트 하나만 바라보도록 전환 → Failover 시에도 앱 재접속 불필요

## 지금(단일노드안) 상태

`DATABASE_URL`이 DB 컨테이너를 직접 가리킨다 (`.env` 참조). OpenProxy 계층 없음.

## TODO — CR-01 발동 시

- [ ] OpenProxy 실제 설정 파일 문법 확인 (`docs.tibero.com/tmaxopensql`)
- [ ] 커넥션 풀 크기 프로젝트 규모에 맞게 조정 (기본값 10에서 시작)
- [ ] `docker-compose.yml`에 OpenProxy 서비스 추가
- [ ] `.env`의 `DATABASE_URL`을 OpenProxy 엔드포인트로 교체

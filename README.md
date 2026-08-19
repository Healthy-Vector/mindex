# mindex

**OpenSQL 기반 저작권 계약 인텔리전스 플랫폼**
2026 오픈소스 개발자대회 · 티맥스티베로 지정과제 대응 (K-RIGHTS 프로젝트)

계약서를 업로드하면 AI가 구조화하고, **OpenSQL(PostgreSQL) 제약조건이 권리 충돌을 원천 차단**하는 무중단 계약 인텔리전스 플랫폼입니다.

```
계약서 업로드 → AI 구조화 추출 → DB 충돌 판정(EXCLUDE) → 자연어/MCP 검색
```

AI는 추출만 합니다. 최종 판정은 데이터베이스가 합니다.

---

## 빠른 시작

```bash
cp .env.example .env          # 값 채우기
docker compose up -d          # OpenSQL 대신 pgvector/pgvector:pg16 로 개발 (동일 PostgreSQL 16 기반)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

`docker compose up` 이 성공하고 `sql/init/01_schema.sql` 이 자동 실행되면, 아래 스모크 테스트로 충돌 판정이 동작하는지 확인합니다.

```bash
pytest tests/test_conflict_constraint.py -v
```

두 번째 INSERT가 다음 에러로 실패해야 정상입니다.

```
ERROR: conflicting key value violates exclusion constraint "no_exclusive_overlap"
```

### 프론트엔드 (SFR-014, Tier 2)

```bash
cd frontend
npm install
npm run dev              # http://localhost:5173, /api는 백엔드(:8000)로 프록시
```

투입 시간이 부족해지면 이 화면 전체를 드롭하고 백엔드의 `/docs` (Swagger UI)로 시연을 대체합니다.

---

## 디렉터리 구조

```
mindex/
├── app/
│   ├── main.py            FastAPI 엔트리포인트
│   ├── core/               설정 · DB 세션
│   ├── models/              ORM 모델
│   ├── schemas/             Pydantic 스키마
│   ├── pipeline/            업로드 · 파싱 · 추출 · 임베딩      (P3)
│   ├── verification/        Evidence 검증 · 신뢰도 산출        (P4)
│   ├── search/              하이브리드 검색 · MCP API           (P4)
│   ├── api/                 REST API                          (P4)
│   ├── orchestration/       LangGraph 에이전트 오케스트레이션   (P5)
│   ├── security/            RLS · 시크릿 · 암호화 헬퍼          (P2)
│   └── workers/             change_log 동기화 워커              (P1)
├── sql/init/                스키마 (컨테이너 최초 기동 시 자동 실행)
├── scripts/                 합성 계약서 생성 등 운영 스크립트
├── tests/
├── frontend/                웹 대시보드 (React + Vite, Tier 2)      (P5)
│   └── src/{pages,components,api}
└── docs/
```

## 담당 매핑

| 담당 | 디렉터리 |
|---|---|
| P1 인프라/DBA | `app/workers`, `sql/`, `docker-compose.yml` |
| P2 데이터/보안 | `app/security`, `sql/init/01_schema.sql`, `app/models` |
| P3 AI 파이프라인 | `app/pipeline`, `scripts/generate_synthetic_contracts.py` |
| P4 검증/백엔드 | `app/verification`, `app/search`, `app/api`, `tests/` |
| P5 오케스트레이션/FE | `app/orchestration`, `frontend/` |

## 지켜야 하는 것

- **PostgreSQL 16 고정** — OpenSQL이 16.8 기반입니다. 17 사용 금지
- **PyMuPDF 금지** — AGPL 라이선스라 프로젝트 전체 라이선스가 오염됩니다. `pdfplumber` + `pypdfium2` 사용
- **`.env`·라이선스 파일 커밋 금지** — `.gitignore` 참조
- 라이선스: **Apache 2.0**

## 문서

- 데이터 모델 정본: [`docs/mindex_remastered.dbml`](docs/mindex_remastered.dbml)
- DB 구조와 서비스 플로우: [`docs/mindex DB 설명서.md`](docs/mindex%20DB%20설명서.md)
- 문서 목록: [`docs/README.md`](docs/README.md)

프로젝트 요구사항 명세(RFP), 일정, 공수 산정 등 상세 문서는 별도 팀 공유 폴더에서 관리합니다.

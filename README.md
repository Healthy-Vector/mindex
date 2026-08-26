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
docker compose up -d          # OpenSQL 대신 pgvector/pgvector:0.8.1-pg17 로 개발 (동일 PostgreSQL 17 기반)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 전체 구동 순서 (PDF 업로드 → 자동 추출까지)

화면·일반 API만 확인한다면 위 빠른 시작(PostgreSQL → Backend → Frontend)으로
충분합니다. **PDF 업로드부터 자동 추출 결과 확인까지** 하려면 Ollama와 Kubernetes
추출 워커가 추가로 필요합니다.

```text
PostgreSQL
  └─ Backend API
      └─ Frontend

Ollama 서버
  └─ Kubernetes의 추출 워커
      └─ Backend가 만든 staging 작업을 처리
```

**1. PostgreSQL** — DB 기동. 최초 실행 시 `sql/init/*.sql`이 자동 적재됩니다.

| 순서 | 명령어 | 설명 |
|---|---|---|
| ① | `cp .env.example .env` | 환경변수 파일 생성 (DB 접속정보 등 입력) |
| ② | `docker compose up -d` | DB 컨테이너 실행 + 스키마 자동 생성 |

**2. Ollama** — 워커가 LLM 추출에 사용합니다 (호스트에서 실행).

| 순서 | 명령어 | 설명 |
|---|---|---|
| ① | `ollama serve` | Ollama 서버 기동 |
| ② | `ollama pull qwen3:8b` | 추출용 LLM 모델 내려받기 |

**3. 추출 워커 (Kubernetes)** — staging 큐를 폴링해 OCR·LLM 추출을 수행합니다.

| 순서 | 명령어 | 설명 |
|---|---|---|
| ① | `docker build -f Dockerfile.worker -t mindex-contract-extraction-worker:local .` | 워커 이미지 빌드 |
| ② | `kubectl create secret generic mindex-worker-secret --from-literal=DATABASE_URL=<DB주소>` | 워커용 DB 접속정보 등록 |
| ③ | `kubectl apply -f k8s/contract-extraction-worker.yaml` | 워커 배포 |

**4. Backend API** — 업로드 접수·검증·확정·검색 (`:8000`)

| 순서 | 명령어 | 설명 |
|---|---|---|
| ① | `pip install -r requirements.txt` | 백엔드 의존성 설치 |
| ② | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | API 서버 실행 |

**5. Frontend** — 사용자 화면 (`:5173`, `/api`는 `:8000`으로 프록시)

| 순서 | 명령어 | 설명 |
|---|---|---|
| ① | `cd frontend` | 프론트엔드 디렉터리 이동 |
| ② | `npm install` | 프론트엔드 의존성 설치 |
| ③ | `npm run dev` | 개발 서버 실행 → http://localhost:5173 |

> Kubernetes/Docker Desktop이 실행 중인 PC에서 Ollama도 함께 켜야 합니다 — 워커
> 배포 설정이 `host.docker.internal:11434`로 로컬 Ollama를 바라봅니다
> ([k8s/contract-extraction-worker.yaml](k8s/contract-extraction-worker.yaml)).
> `kubectl` 명령은 클러스터 종류(kind/minikube/Docker Desktop)에 따라 이미지 로드
> 단계가 하나 더 필요할 수 있습니다.

### 자연어 검색(벡터 랭킹) — 기본 켜짐

검색 벡터 랭킹은 **기본으로 켜져 있다**(`EMBEDDINGS_ENABLED=true`). 켜져 있으면 ML
의존성이 설치돼 있어야 하고, 서버가 기동 시 임베딩 모델을 미리 데운다(warm-up).

```bash
pip install -r requirements-ml.txt   # torch + sentence-transformers
uvicorn app.main:app --reload
```

- 임베딩 모델(`intfloat/multilingual-e5-large`, ~2.2GB)은 첫 로딩 시 HuggingFace에서
  자동 다운로드된다. warm-up 덕에 첫 검색 사용자가 다운로드·로딩을 기다리지 않는다.
- **폐쇄망**에서는 자동 다운로드가 실패하므로 모델을 미리 받아 HuggingFace 캐시
  (`HF_HOME`)에 심어 두어야 한다.
- GPU가 없으면 임베딩이 크게 느리다(실측 CPU 2.8 chunk/s, CUDA fp16 대비 약 29배).
  검색 질의는 건당이라 체감이 덜하지만, 색인(워커)은 GPU 환경을 권장한다.

**임베딩 없이 돌리려면(opt-out)** `EMBEDDINGS_ENABLED=false`로 끈다. `requirements-ml.txt`
없이 기본 `requirements.txt`만으로 뜨고, 검색은 **어휘(pg_trgm) 폴백**으로 동작한다
(벡터 랭킹만 생략, 오류 없음). CI가 검색 테스트를 이 경로로 스킵한다.

> 런타임에 패키지를 설치하지는 않는다 — 설치는 배포 단계, 플래그는 사용 여부만 정한다.
> 기본이 켜짐이라 `true`인데 패키지가 없으면 기동 시 경고를 남기고 어휘 폴백으로 계속한다.

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

- **PostgreSQL 17 고정** — 실물 OpenSQL이 17.8 + pgvector 0.8.1 기반입니다(RFP v3의 "16.8 기반" 기술은 오기였습니다)
- **PyMuPDF 금지** — AGPL 라이선스라 프로젝트 전체 라이선스가 오염됩니다. `pdfplumber` + `pypdfium2` 사용
- **`.env`·라이선스 파일 커밋 금지** — `.gitignore` 참조
- 라이선스: **Apache 2.0**

## 문서

- 데이터 모델 정본: [`docs/mindex_remastered.dbml`](docs/mindex_remastered.dbml) (운영 `public` 스키마 + 비동기 추출용 `staging` 스키마)
- DB 구조와 서비스 플로우: [`docs/mindex DB 설명서.md`](docs/mindex%20DB%20설명서.md)
- staging 스키마(비동기 OCR/LLM 파이프라인): [`docs/mindex_staging DB 설명서.md`](docs/mindex_staging%20DB%20설명서.md)
- 문서 목록: [`docs/README.md`](docs/README.md)

프로젝트 요구사항 명세(RFP), 일정, 공수 산정 등 상세 문서는 별도 팀 공유 폴더에서 관리합니다.

# Mindex

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**OpenSQL 기반 저작권 계약 인텔리전스 플랫폼**  
2026 오픈소스 개발자대회 티맥스티베로 지정과제 - 벡터근육키우기 프로젝트

계약서를 업로드하면 AI가 내용을 구조화하고, OpenSQL의 PostgreSQL 호환 제약조건이 배타 권리의 계약 충돌을 판정합니다.

```text
계약서 업로드 → OCR·LLM 구조화 → DB 충돌 판정 → 자연어·MCP 검색
```

> AI는 계약 내용을 추출합니다. 최종 권리 충돌 판정은 데이터베이스가 수행합니다.

---

## 핵심 기능

| 기능 | 구현 |
|---|---|
| 계약서 자동 구조화 | PDF 업로드 후 OCR·LLM 비동기 추출 |
| 중복 처리 방지 | `FOR UPDATE SKIP LOCKED` + lease 기반 재수령 |
| 권리 충돌 판정 | PostgreSQL `EXCLUDE` 제약조건 |
| 계약 검색 | `pg_trgm` + `multilingual-e5-large` 하이브리드 검색 |
| 외부 연동 | REST API + MCP |

## 시스템 구성

```mermaid
flowchart LR
    U[Frontend] --> API[Backend API]
    API --> DB[(OpenSQL)]
    DB --> W[Kubernetes Worker]
    W --> AI[OCR · Ollama]
    AI --> DB
```

| 구분 | 기술 |
|---|---|
| Backend | Python 3.12, FastAPI |
| Database | OpenSQL 17.8, PostgreSQL 17, pgvector 0.8.1 |
| AI | Ollama `qwen3:8b`, `multilingual-e5-large` |
| Worker | Kubernetes |
| Frontend | React, Vite |

---

## 빠른 시작

### 1. 환경변수와 DB

```bash
cp .env.example .env          # DB 접속정보 입력
docker compose up -d          # 로컬 PostgreSQL 17 실행
```

최초 실행 시 `sql/init/*.sql`이 자동으로 적재됩니다. 로컬에서는 OpenSQL 대신 동일한 PostgreSQL 17 기반의 `pgvector/pgvector:0.8.1-pg17` 이미지를 사용합니다.

### 2. Backend

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-ml.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

- Frontend: <http://localhost:5173>
- `/api` 요청은 Backend의 `:8000` 포트로 프록시됩니다.

<details>
<summary><strong>PDF 자동 추출 워커까지 실행</strong></summary>

### Ollama

```bash
ollama serve
ollama pull qwen3:8b
```

### Kubernetes Worker

```bash
docker build \
  -f Dockerfile.worker \
  -t mindex-contract-extraction-worker:local \
  .

kubectl create secret generic mindex-worker-secret \
  --from-literal=DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME' \
  --dry-run=client \
  -o yaml | kubectl apply -f -

kubectl apply -f k8s/contract-extraction-worker.yaml
kubectl get pods
```

Docker Desktop Kubernetes의 워커는 호스트 Ollama를 `host.docker.internal:11434`로 조회합니다. kind, minikube, Linux 기반 클러스터는 로컬 이미지 로드와 호스트 주소 설정이 추가로 필요합니다.

</details>

---

## 자연어 검색

벡터 검색은 기본으로 켜져 있습니다.

```dotenv
EMBEDDINGS_ENABLED=true
```

`intfloat/multilingual-e5-large` 모델은 최초 실행 시 Hugging Face에서 자동으로 내려받습니다. 모델 크기는 약 2.2GB입니다.

임베딩을 사용하지 않으려면 다음과 같이 설정합니다.

```dotenv
EMBEDDINGS_ENABLED=false
```

이 경우 `requirements-ml.txt` 설치를 생략할 수 있으며, 검색은 `pg_trgm` 기반 어휘 검색으로 폴백합니다.

<details>
<summary><strong>임베딩 운영 참고</strong></summary>

- 폐쇄망에서는 모델을 미리 내려받아 `HF_HOME` 캐시에 배치해야 합니다.
- CPU 색인 실측치는 약 2.8 chunk/s로 CUDA FP16 대비 약 29배 느렸습니다.
- 대량 색인은 GPU 환경을 권장합니다.
- ML 패키지가 없으면 경고를 남기고 어휘 검색으로 계속 실행합니다.

</details>

## 충돌 판정 테스트

```bash
pytest tests/test_conflict_constraint.py -v
```

충돌하는 두 번째 계약이 아래 오류로 거절되면 정상입니다.

```text
ERROR: conflicting key value violates exclusion constraint "no_exclusive_overlap"
```

---

## 디렉터리 구조

```text
mindex/
├── app/                     Backend API·파이프라인·검색
├── frontend/                React·Vite 웹 대시보드
├── k8s/                     추출 워커 배포 설정
├── sql/init/                DB 초기 스키마
├── scripts/                 운영·데이터 생성 스크립트
├── tests/                   테스트
├── docker-compose.yml
├── Dockerfile.worker
├── requirements.txt
├── requirements-ml.txt
├── LICENSE
└── THIRD_PARTY_NOTICES.md
```

## 개발 원칙

- PostgreSQL 17 고정. 실물 OpenSQL은 PostgreSQL 17.8과 pgvector 0.8.1 기반입니다.
- 프로젝트 정책상 AGPL 계열 라이브러리는 사용하지 않습니다. PDF 처리는 `pdfplumber`, `pypdfium2`를 사용합니다.
- `.env`, 비밀키, 인증정보는 커밋하지 않습니다.
- `LICENSE`, `THIRD_PARTY_NOTICES.md`는 저장소와 배포물에 포함합니다.

## 문서

- [데이터 모델](docs/mindex_remastered.dbml)
- [DB 구조와 서비스 플로우](docs/mindex%20DB%20설명서.md)
- [staging 스키마와 비동기 추출 파이프라인](docs/mindex_staging%20DB%20설명서.md)
- [전체 문서 목록](docs/README.md)
- [Apache License 2.0](LICENSE)
- [외부 오픈소스 고지](THIRD_PARTY_NOTICES.md)

프로젝트 요구사항 명세, 일정, 공수 산정 등 내부 문서는 별도 팀 공유 폴더에서 관리합니다.


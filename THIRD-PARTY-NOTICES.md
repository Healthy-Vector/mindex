# Third-Party Notices

Mindex는 아래의 오픈소스 소프트웨어와 모델을 사용합니다.

Mindex 자체 코드는 [Apache License 2.0](LICENSE)에 따라 배포됩니다. 이 문서는 외부 구성요소의 저작권과 라이선스를 알리기 위한 것이며, 각 구성요소의 원 라이선스를 변경하거나 대체하지 않습니다.

## Backend and Worker

| 구성요소 | 라이선스 |
| :--- | :--- |
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| Pydantic | MIT |
| pydantic-settings | MIT |
| SQLAlchemy | MIT |
| psycopg2-binary | LGPL-3.0-or-later with exceptions |
| pgvector Python client | MIT |
| Alembic | MIT |
| pdfplumber | MIT |
| pypdfium2 | Apache-2.0 OR BSD-3-Clause + PDFium third-party licenses |
| OpenAI Python SDK | Apache-2.0 |
| Anthropic Python SDK | MIT |
| bcrypt | Apache-2.0 |
| PyJWT | MIT |
| python-dotenv | BSD-3-Clause |
| HTTPX | BSD-3-Clause |

## AI and Models

| 구성요소 | 라이선스 |
| :--- | :--- |
| PyTorch | BSD-3-Clause |
| sentence-transformers | Apache-2.0 |
| multilingual-e5-large | MIT |
| Ollama | MIT |
| Qwen3 8B | Apache-2.0 |

## Frontend

| 구성요소 | 라이선스 |
| :--- | :--- |
| @radix-ui/react-select | MIT |
| React | MIT |
| React DOM | MIT |
| react-pdf | MIT |
| react-router-dom | MIT |
| pdfjs-dist | Apache-2.0 |
| tslib | 0BSD |
| Vite | MIT |
| @vitejs/plugin-react | MIT |
| ESLint | MIT |
| @types/react | MIT |
| @types/react-dom | MIT |
| caniuse-lite | CC-BY-4.0 |

## Database and Container Images

| 구성요소 | 라이선스·고지 |
| :--- | :--- |
| PostgreSQL | PostgreSQL License |
| pgvector PostgreSQL extension | PostgreSQL License |
| `pgvector/pgvector` image | PostgreSQL 및 기반 이미지 구성요소별 라이선스 |
| Python slim base image | Python Software Foundation License 및 Debian 패키지별 라이선스 |

## Development Tools

| 구성요소 | 라이선스 |
| :--- | :--- |
| pytest | MIT |
| pytest-asyncio | Apache-2.0 |
| Ruff | MIT |
| pip-audit | Apache-2.0 |

## Additional Notices

### psycopg2-binary

`psycopg2-binary`에는 LGPL-3.0-or-later와 프로젝트 예외 조항이 적용됩니다. 바이너리 wheel에 포함된 `libpq`, OpenSSL 등 구성요소의 원 라이선스 파일을 보존해야 합니다.

### pgvector

Mindex는 서로 다른 라이선스가 적용되는 두 pgvector 구성요소를 사용합니다.

- Python client: MIT
- PostgreSQL extension: PostgreSQL License

### pypdfium2 and PDFium

`pypdfium2` Python 코드에는 `Apache-2.0 OR BSD-3-Clause`가 적용됩니다. wheel에 포함된 PDFium과 제3자 구성요소에는 추가 라이선스가 적용됩니다.

wheel 또는 PDFium 바이너리를 재배포할 때는 함께 제공된 라이선스 파일을 제거하지 않습니다.

### Models

Qwen3 8B에는 Apache-2.0, multilingual-e5-large에는 MIT 라이선스가 적용됩니다. 모델 파일을 저장소나 배포 이미지에 직접 포함할 경우 모델 라이선스와 모델 카드를 함께 제공합니다.

## Distribution

- 외부 구성요소에 포함된 `LICENSE`, `NOTICE` 파일을 제거하지 않습니다.
- Apache-2.0 구성요소에 `NOTICE` 파일이 있으면 필요한 고지를 배포물에 포함합니다.
- Docker 이미지와 모델 파일을 직접 배포할 때는 해당 라이선스 원문을 함께 제공합니다.
- 의존성을 추가하거나 변경하면 이 파일도 함께 갱신합니다.

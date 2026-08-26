# 계약 PDF staging fixture 생성

`C:\mindex\pdf\generated`의 합성 계약 PDF를 `staging.extract_result.payload`에 저장할 수 있는 JSON으로 변환한다. API와 DB는 변경하지 않으며, Ollama·LLM·OCR 모델도 사용하지 않는다. PDF의 텍스트 레이어와 한국어·영어·일본어 계약 문구를 규칙 기반으로 파싱한다.

## 생성

저장소 루트에서 실행한다.

```powershell
.venv\Scripts\python.exe scripts\build_staging_fixtures.py
```

입력·출력 위치를 바꾸려면 다음 옵션을 사용한다.

```powershell
.venv\Scripts\python.exe scripts\build_staging_fixtures.py `
  --input C:\mindex\pdf\generated `
  --output data\generated\staging-fixtures
```

- 기본 입력: `C:\mindex\pdf\generated`
- 기본 출력: `data/generated/staging-fixtures`
- 일부만 확인: `--limit 3`
- 경고가 하나라도 있으면 실패 코드 반환: `--strict`

`data/generated`는 `.gitignore` 대상이다. fixture를 다시 만들 수 있는 생성 스크립트만 Git에서 관리한다.

## staging 적재·Swagger 테스트

`POST /extract`로 PDF를 접수하면 `QUEUED` 작업이 생성되고, `GET /extract/{tmpid}`로 상태·결과를 폴링한다. [seed_staging_fixture.py](../scripts/seed_staging_fixture.py)는 워커 완료 상태를 기다리지 않고 PDF 원본, `DONE` 작업, 추출 결과를 같은 `tmpid`로 한 트랜잭션에 넣어 Swagger 확정 테스트를 바로 시작할 때 사용한다.

먼저 Swagger(`http://127.0.0.1:8000/docs`)의 `POST /api/ips`로 fixture 제목과 연결할 IP를 만든다. 응답의 `ipId` 및 `assets[0].contentAssetId`를 다음 명령에 사용한다.

```powershell
# 기본 fixture: KO/T1/DIRECT_LICENSE/CTR-KO-0011.json
# DB 변경 없이 요청 JSON만 생성
.venv\Scripts\python.exe scripts\seed_staging_fixture.py `
  --ip-id 1 --content-asset-id 1

# 위 출력의 tmpid를 유지한 채 staging에 실제 적재
.venv\Scripts\python.exe scripts\seed_staging_fixture.py `
  --ip-id 1 --content-asset-id 1 `
  --tmpid <dry-run에서_출력된_tmpid> --apply
```

요청 JSON은 `data/generated/staging-fixtures/requests/`에 생성된다.

1. JSON의 `verifyRequest`를 `POST /api/contracts/verify`에 넣어 충돌 여부를 확인한다.
2. 통과하면 `confirmRequest`를 `POST /api/contracts`에 넣어 확정한다.
3. `GET /api/contracts`에서 계약을 확인한다.

`confirmRequest.sourceTmpid`는 한 번 확정에 사용하면 재사용할 수 없다(`409 ALREADY_CONFIRMED`). 다시 확인하려면 seeder를 새 tmpid로 다시 실행한다. 또한 현 단계의 확정 API는 staging payload의 존재·DONE 상태만 검증한다. `raw` fixture를 API의 `rights[]`로 자동 병합하는 서버 기능은 아직 없으며, seeder가 P2 참조 코드로 변환한 요청 JSON을 제공한다.

현재 86건 중 78건은 P2 요청으로 변환할 수 있다. 나머지 8건은 의도적으로 적재·확정을 막는다. 원문이 법적 권리 또는 기간을 특정하지 않은 3건과, P2 `exploitation_mode` 참조 데이터에 아직 없는 `DIGITAL_DISTRIBUTION_UNSPECIFIED`를 사용하는 5건이다. 이 8건은 worker·검수 흐름 시험에는 사용할 수 있지만, P2 확정 테스트에 억지 기본값을 넣으면 안 된다.

## 결과 구조

PDF 한 건마다 원본과 같은 하위 경로에 JSON 한 건을 만든다.

```text
data/generated/staging-fixtures/
├── _manifest.json
├── EN/T1/DIRECT_LICENSE/CTR-EN-0001.json
├── JP/...
└── KO/...
```

개별 JSON은 contract-extraction-worker의 결과와 같은 최상위 구조를 사용한다.

| 키 | 내용 |
|---|---|
| `raw` | worker Rich Extraction 스키마에 맞춘 계약·당사자·`rights_grants`·대가·근거 |
| `validation` | 원문 근거 일치, evidence 참조, 날짜 논리와 worker 기준 confidence/route |
| `normalized` | territory와 날짜를 정규화한 결과 |
| `compact` | 확정 저장 단계에서 사용할 DB projection 형태 |

`staging.extract_result.payload`에 넣을 때는 개별 JSON 전체를 payload로 사용한다. 단, `extract_result.tmpid`는 `extract_job.tmpid`를 참조하므로 실제 DB 테스트에서는 정상 업로드 흐름을 거치거나 `pdf_blob` → `extract_job` → `extract_result` 순서로 같은 `tmpid`를 만들어야 한다. 이 생성기는 DB에 행을 삽입하지 않는다.

## 현재 생성 결과

2026-08-25 기준 전체 생성·검증 결과는 다음과 같다.

| 항목 | 결과 |
|---|---:|
| PDF / JSON | 86건 |
| 페이지 | 446쪽 |
| 언어 | KO 29 / EN 29 / JP 28 |
| 당사자 | 172명 |
| payments | 86건 |
| rights grants | 94건 |
| worker 검증 GREEN | 86건 |
| schema / logic / reference 오류 | 0건 |
| 원문 미일치 필드 | 0건 |

다음 3건은 파싱 실패가 아니라 원문이 값을 확정하지 않은 의도된 검수 사례다. 해당 필드는 `UNRESOLVED`로 두고 `_manifest.json`의 `warnings`에 기록한다.

| PDF | 미확정 필드 |
|---|---|
| `EN/T1/DIRECT_LICENSE/CTR-EN-0019.pdf` | 이용 시작일·종료일(최초 상업 공개일부터 3년이나 공개일 미정) |
| `JP/T1/DIRECT_LICENSE/CTR-JP-0019.pdf` | 법적 권리 |
| `JP/T1/DIRECT_LICENSE/CTR-JP-9004.pdf` | 법적 권리 |

따라서 전체 데이터에 `--strict`를 사용하면 이 3건 때문에 종료 코드 1이 정상적으로 반환된다. 경고 없는 정상 사례만 필요하면 `_manifest.json`에서 `warnings`가 빈 문서를 선택한다.

# OCR/파싱 → LLM 정규화 인계 규격

**P3 파싱 → LLM 추출·정규화 담당자 인계 문서**

status: `DRAFT v0.3`
date: 2026-08-22

`retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle` — PDF를 파싱·분해하고
추출 대상 field별로 관련 청크를 점수와 함께 묶어 넘긴다.
받는 쪽은 이걸로 권리정보를 추출·정규화해 DB 전달 payload를 만든다.

최종 흐름: `Task1 → RetrievalBundle → Task2 → ExtractionResult → K8s Worker → staging 저장`

---

## 1. 지금 바로 볼 것

| | 경로 |
|---|---|
| **Task1 최종 출력** `*.retrieval.json` | [samples/](samples/) |
| **구조·필드 설명** | [samples/README.md](samples/README.md) |
| 규격 정의 | [app/schemas/pipeline.py](../../app/schemas/pipeline.py) |
| 생성 스크립트 | [make_handoff_samples.py](../../scripts/make_handoff_samples.py) |
| DB 전달 규격 | [docs/synthetic_data/interfaces/](../synthetic_data/interfaces/) |
| DB 스키마 | [docs/erd/](../erd/) |

```bash
# 샘플 재생성 (실제 파이프라인을 그대로 호출한다)
PYTHONPATH=. python scripts/make_handoff_samples.py
```

**Task2 담당자는 `*.retrieval.json`만 보면 된다.**

> 전체 구조와 필드 설명은 [samples/README.md](samples/README.md) 에 정리해 두었다.
> `*.parse.json`(중간 산출물)은 더 이상 만들지 않는다.

### 샘플 구성 — 10건

86건 전부가 아니라 **언어 × 템플릿 × 계약유형이 골고루 덮이도록 10건만** 골랐다.
`KO 4 / EN 3 / JP 3`, 템플릿 `T1~T6` 전부, `DIRECT_LICENSE 8 / SUBLICENSE 2`, 3~10페이지.

| 파일 | 언어 | T | 유형 | 페이지 | 조항 | 청크 | 특징 |
|---|---|---|---|---:|---:|---:|---|
| `CTR-KO-0001` | ko | T1 | DIRECT | 3 | 20 | 22 | 가장 단순. 여기서 시작 |
| `CTR-EN-0001` | en | T1 | DIRECT | 3 | 20 | 21 | 영문 기본형 |
| `CTR-JP-0001` | ja | T1 | DIRECT | 3 | 20 | 21 | 일문 기본형 |
| `CTR-EN-0017` | en | T1 | **SUB** | 5 | 20 | 22 | 재이용허락 — 권한체인(R8) |
| `CTR-JP-0002` | ja | T2 | DIRECT | 4 | 20 | 21 | 방송 방영권·배신권 |
| `CTR-EN-0006` | en | T3 | DIRECT | 4 | 20 | 23 | 단일 이용방식 |
| `CTR-KO-0014` | ko | T4 | DIRECT | 7 | 20 | 21 | **별지 없이 본문에 복수 Grant** |
| `CTR-KO-0015` | ko | T5 | **SUB** | 8 | 24 | 26 | **별지 3개 + 재이용허락** |
| `CTR-JP-0015` | ja | T5 | DIRECT | 10 | 25 | 28 | **별지 5개**. 최대 난이도 |
| `CTR-KO-0006` | ko | T6 | DIRECT | 8 | 24 | 26 | **OST 음악 권리처리 별지** |

난이도 순서: `CTR-KO-0001` → `CTR-KO-0014`(별지 없는 복수 Grant) → `CTR-KO-0015`(별지) → `CTR-JP-0015`(별지 5개).

정답(Ground Truth)은 [testdata/k-rights/annotations/](../../testdata/k-rights/annotations/)에 있다.
`ground_truth.json`에서 같은 `contract_id`를 찾으면 추출 결과를 대조할 수 있다.

---

## 2. Task1 최종 출력 — `RetrievalBundle`

스키마 `mindex.retrieval-bundle.v0.2`. 샘플은 `samples/*.retrieval.json`.

**전체 구조와 필드 설명은 [samples/README.md](samples/README.md)에 있다.**
같은 규격을 두 문서에 쓰면 반드시 갈라지므로 그쪽 하나만 유지한다.
규격의 실제 정의는 [app/schemas/pipeline.py](../../app/schemas/pipeline.py)다.

```jsonc
{
  "schema_version": "mindex.retrieval-bundle.v0.2",
  "document":  { ... },   // 이 PDF가 무엇인가
  "retrieval": { ... },   // 어떻게 회수했는가
  "fields":    { ... },   // 필드별로 어디를 봐야 하나  <- 여기서 시작
  "chunks":    [ ... ]    // 본문 조각 (fields가 가리키는 대상)
}
```

`fields`는 색인, `chunks`는 자료다. `fields["territory"][0].chunk_id`로
`chunks[]`를 찾아 `.text`를 읽는다.

### v0.1에서 바뀐 점 (받는 쪽 코드에 영향 있음)

| | v0.1 | v0.2 |
|---|---|---|
| `fields[]` 항목 | `chunk_id` + **본문**(`text`·`page`·`clause`·`location`) + `score` | `chunk_id` + `score`/`lexical`/`semantic` + `matched_field`/`match_reasons` |
| 본문 위치 | `fields[]`와 `chunks[]` 양쪽 | `chunks[]` 한 곳 |
| 페이지 | `chunks[].page` 단일값 | `page_start`/`page_end` 범위 (+ 호환용 `page`) |
| 조항 번호 | `clause` | `clause_no` |
| 추가 필드 | — | `chunk_index` · `clause_title` · `char_start` · `char_end` |

본문을 뺀 이유는 중복이다. 한 청크가 여러 필드에 동시에 잡히는데(지역·기간·
독점성이 한 조항에 같이 있다) v0.1은 그때마다 본문을 복사했다. `CTR-KO-0015`
실측으로 `fields[]` 안 본문이 6977자, `chunks[]`가 2945자 — **2.4배 중복**이었다.
크기보다 나쁜 것은 본문이 두 곳에 있으면 어느 쪽이 진짜인지 애매해진다는 점이다.

### 중간 산출물 `*.parse.json`은 없어졌다

파이프라인이 모듈로 정리되면서 중간 결과를 파일로 내보내지 않는다.
문서 전체 분해 결과가 필요하면 알려주기 바란다. 번들에 담아 보낼 수 있다.


## 4. 넘길 때 권장하는 사용법

**전체 텍스트를 통째로 넣지 말고 `clauses`를 쓰는 편이 낫다.** 계약서가 최대 12페이지라
전문을 넣으면 토큰이 크고, 근거(Evidence)를 `{page, clause, quote}`로 되돌려받아야 하는데
조항 단위로 넣어야 그 매핑이 자연스럽다.

권장 순서:

1. `FRONT_MATTER` → 계약명·당사자·체결일
2. `SCHEDULE` + `GRANT_ITEM` → **권리부여 명세(있으면 여기가 주력)**
3. `ARTICLE` 중 권리 관련 조항 → 이용허락·제한·재이용허락·대가
4. 나머지 `ARTICLE`(비밀유지·불가항력 등)은 DISTRACTOR라 추출 대상이 아니다

`pages[].tables`는 당사자표·별지표가 구조화돼 들어있다. 본문 텍스트로도 같은 내용이
나오지만 표가 더 정확하니 당사자·금액은 표를 우선 보는 걸 권한다.

---

## 5. DB로 보낼 스키마 정보

### 5.1 추출 결과가 최종적으로 들어갈 형태

**DB 전달 payload 규격은 이미 문서화돼 있다.** 새로 만들 필요 없다.

| 문서 | 내용 |
|---|---|
| [db-contract-projection-v0.1.md](../synthetic_data/interfaces/2026-08-19-db-contract-projection-v0.1.md) | 필드 정의 — `subjects` · `legal_rights` · `exploitation_modes` · `territory_scopes` · `license_period` · `exclusivity` · `authority` · `payment` · `evidence` |
| [db-delivery-schema-v0.1.md](../synthetic_data/interfaces/2026-08-19-db-delivery-schema-v0.1.md) | payload 범위, code 유형, Evidence 배치 규칙 |
| [examples/db-contract-projection-v0.1.example.json](../synthetic_data/interfaces/examples/db-contract-projection-v0.1.example.json) | **전체 payload 샘플** |
| [contract-extraction-interface-scope-v0.1.md](../synthetic_data/interfaces/2026-08-19-contract-extraction-interface-scope-v0.1.md) | 추출 단계 내부 표현(Rich Extraction) |

흐름:

```
Rich Extraction  (field_status + raw expression + Evidence + modifier + 복수 payment)
        ↓ validate / normalize / apply modifier / aggregate payment
DB Projection    (유효한 canonical 값 + 단일 payment + compact Evidence)
```

### 5.2 반드시 지킬 규칙

- **`legal_right`와 `exploitation_mode`를 절대 합치지 않는다.** `exclusivity`도 별도 축이다.
- 정보가 없으면 만들어내지 말고 `UNRESOLVED`로 둔다.
- 정의되지 않은 `ASIA` / `APAC`를 임의 국가목록으로 확장하지 않는다.
- Contract Term을 License Period로 대체하지 않는다.
- 영상 · Remake · OST를 자동으로 같은 RightsGrant에 병합하지 않는다.
- Payment는 `amount` / `currency`만 쓴다. 통화가 다르면 환율 없이 합산하지 않고 `null`.
- 언어 코드는 `JA`(ISO 639-1), 국가 코드는 `JP`(ISO 3166-1). **서로 다른 값이다.**
- dataset ID(`CTR-*` · `GRT-*` · `EVS-*` · `scenario_id` · `content_id`)를 payload에 넣지 않는다.

전체 목록은 [testdata/k-rights/README.md](../../testdata/k-rights/README.md)의 "사용 경계" 참조.

### 5.3 실제 DB 테이블

현재 ERD는 **v3**이며 [docs/erd/2026-08-22-v3-remastered.md](../erd/2026-08-22-v3-remastered.md)에 정리해 뒀다.
권리 데이터가 들어가는 `rights_grant`의 주요 컬럼:

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `content_asset_id` | BIGINT FK | 작품·OST·시즌 등 대상 |
| `territory` | CHAR(2) FK | 단일 국가코드. 여러 지역이면 **행을 나눈다** |
| `legal_right` | TEXT FK | 법적 권리 (계층 테이블 참조) |
| `exploitation_mode` | TEXT FK | 이용형태 (계층 테이블 참조) |
| `legal_right_span` | INT4RANGE | 권리 계층 nested set 구간 |
| `exploitation_mode_span` | INT4RANGE | 이용형태 계층 구간 |
| `period` | DATERANGE | 이용기간 |
| `exclusivity` | `exclusivity_kind` | ENUM |
| `evidence` | JSONB | 필드별 근거 |
| `conditions_raw` | JSONB | 조건 원문 |

> ⚠️ **`sql/init/01_schema.sql`은 outdated(v0)다.** `rights_type` 하나로 두 축을 합쳐놓은
> 옛 버전이니 이걸 보고 구현하면 안 된다. v3 마이그레이션은 아직 적용 전이다.
> ERD는 계속 바뀔 수 있으므로 [docs/erd/README.md](../erd/README.md)의 현재 버전 표시를 확인할 것.

---

## 6. 아직 미확정 / 협의 필요

1. **이 payload 규격 자체가 `v0.1` 초안이다.** 받는 쪽에서 필요한 필드가 있으면 알려주면 반영한다.
2. **청크 크기** — 현재 최대 1200자, 겹침 150자. RAG 검색 품질 보고 조정한다.
3. **OCR 경로는 아직 미구현이다.** 지금 샘플은 전부 `TEXT_LAYER`다.
   합성데이터 86건이 전부 digital-born이라 OCR이 돌지 않는다.
   OCR 경로 검증은 86건을 래스터화한 파생 세트로 별도 진행할 예정이다.
4. **`VERIFY` 경로의 교차검증 로직 미구현.** 현재는 라우팅 판정만 한다.

## 7. Python 의존성

Task1이 필요로 하는 것만이다. `requirements.txt` 통합은 Task2 담당자가 한다.

```
# 파싱 (구현 완료 · 현재 샘플이 이걸로 생성됨)
pdfplumber==0.11.*
pypdfium2==4.*

# 임베딩 (구현 완료) — requirements-ml.txt 로 분리돼 있다
--extra-index-url https://download.pytorch.org/whl/cu130
torch==2.13.0+cu130
sentence-transformers==6.0.*

# OCR (구현 예정 · 스캔본 경로에서만 동작)
#   paddlepaddle-gpu 는 PyPI 버전이 2.6.2 에서 멈춰 있어(CUDA 11.8/12.0 세대)
#   최신 GPU 에서 동작하지 않는다. Paddle 공식 인덱스에서 받아야 한다.
#   pip install paddlepaddle-gpu==3.3.1 #       -i https://www.paddlepaddle.org.cn/packages/stable/cu130/
#   pip install paddleocr==3.7.*
```

**ML 의존성은 `requirements.txt` 와 분리했다.** CI(ubuntu-latest)와
Dockerfile(python:3.12-slim)이 `requirements.txt` 를 그대로 설치하는데, torch 를
거기 넣으면 GPU 없는 러너가 매 푸시마다 수 GB를 받고 pip-audit 감사 대상이
수백 개로 늘어난다. 파이프라인을 실제로 돌리는 환경에서만
`pip install -r requirements-ml.txt` 를 한다.

`scripts/check_ml_env.py` 로 설치 상태를 진단할 수 있다. import 통과가 아니라
실제 GPU 연산까지 시켜서 판정한다 — 설치가 됐는데 커널이 없어 첫 연산에서
죽는 경우가 있기 때문이다.

### CUDA 라인 주의

개발 GPU가 **Blackwell(sm_120)** 이면 흔히 쓰는 cu121/cu124 휠은 설치는 되지만
실행 시 `no kernel image is available` 로 죽는다. cu128 이상이 필요하고,
Windows·cp312 기준으로 torch 와 paddlepaddle-gpu 휠이 동시에 존재하는 라인은
cu130 뿐이다.

**PyMuPDF는 쓰지 않는다.** AGPL이라 프로젝트 전체 라이선스가 오염된다.
PDF 파싱은 `pdfplumber`, 래스터화는 `pypdfium2`로 처리한다.

### 모델 로딩

요청마다 재로딩하지 않는다. 프로세스 시작 시 1회 로딩하는 싱글턴으로 잡는다.
K8s 배포 시 고려할 점:

- **콜드스타트가 길다.** e5-large 로딩만 실측 **13.7초**. readiness probe 여유 필요
- **메모리.** e5-large fp16 VRAM peak 실측 3.5GB + PaddleOCR 수백MB. 파드 한도를 넉넉히
- **fp16 을 쓴다.** 실측(RTX 5050, 232청크) fp32 29 chunk/s vs fp16 **80 chunk/s**
- 모델 파일은 이미지에 굽거나 볼륨에 캐시. 매 기동마다 받으면 느리다

---

## 8. 협의가 필요한 것

### 8.1 임베딩을 누가 DB에 넣는가 ⚠️

"Task1 중간 결과는 DB에 저장하지 않고 메모리로 전달"에 동의한다.
`retrieve_contract_chunks(pdf_bytes)`가 `contract_id`·`tenant_id`를 안 받으므로
Task1은 애초에 DB에 쓸 수 없다.

**다만 임베딩 벡터 자체는 버리면 안 된다.** 그래서 `chunks[].embedding`에 실어 보낸다.
Worker가 사용자 저장 확정 시점에 `contract_chunk`로 적재해 주기 바란다.
안 그러면 사용자 검색(하이브리드 검색·MCP)용 벡터가 어디에도 남지 않아,
검색할 때마다 PDF를 다시 파싱해야 한다.

### 8.2 `rights_type` 필드명 ⚠️

retrieval 쿼리 이름으로는 괜찮다. 다만 **추출 결과 필드로 그대로 굳으면 안 된다.**

현재 ERD(v3)에서 `rights_type`은 `legal_right` + `exploitation_mode` 두 컬럼으로 분리됐다.
프로젝트가 "이 두 축을 절대 합치지 않는다"를 반복해서 못박고 있고,
합치면 R3(권리 위계)·R4(이용형태) 판정이 불가능해진다.
Task2 출력 단계에서는 분리해 주기 바란다.

### 8.3 `staging.extract_result` 스키마

이 테이블이 현재 문서화된 ERD(v3)에 없다. 정의를 공유해 주면
[docs/erd/](../erd/)에 함께 관리하겠다.

---

## 부록 — 경로 판정 임계값 근거

합성데이터 86건 446페이지(전부 digital-born) 문자밀도 실측:

```
정상 최소 0.152 (JP) | 중앙 2.327 | 최대 7.583      래스터화 스캔본 0.000

임계 0.30 -> 정상 페이지 오탐 27개 (6.1%)
임계 0.20 -> 정상 페이지 오탐 10개 (2.2%)
임계 0.10 -> 정상 페이지 오탐  0개          <- 채택
```

CJK는 같은 내용을 적은 문자로 표현하고 표가 많은 페이지는 텍스트가 짧게 나온다.
밀도만으로 판정하면 짧은 정상 페이지를 스캔으로 오탐하므로, 밀도 임계는 낮게 두고
이미지 덮개율을 주 신호로 쓴다.

검증 결과: digital 446페이지 → 전부 `TEXT_LAYER`(오탐 0),
래스터화 4페이지 → 전부 `OCR`(미탐 0).

---

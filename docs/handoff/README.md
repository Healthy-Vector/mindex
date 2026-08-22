# OCR/파싱 → LLM 정규화 인계 규격

**P3 파싱 → LLM 추출·정규화 담당자 인계 문서**

status: `DRAFT v0.1`
date: 2026-08-22

화면에서 업로드된 PDF를 파싱해 조항 단위로 분해한 결과를 넘긴다.
받는 쪽은 이걸로 권리정보를 추출·정규화해 DB 전달 payload를 만든다.

---

## 1. 지금 바로 볼 것

| | 경로 |
|---|---|
| 파싱 결과 샘플 6건 | [samples/](samples/) |
| 생성 스크립트 | [scripts/ocr_parse_sample.py](../../scripts/ocr_parse_sample.py) |
| DB 전달 규격 | [docs/synthetic_data/interfaces/](../synthetic_data/interfaces/) |
| DB 스키마 | [docs/erd/](../erd/) |

```bash
python scripts/ocr_parse_sample.py <pdf...> -o <출력폴더>
```

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

## 2. payload 구조 — `mindex.ocr-parse.v0.1`

```jsonc
{
  "schema_version": "mindex.ocr-parse.v0.1",

  "document": {
    "file_name":  "CTR-KO-0001.pdf",
    "file_hash":  "sha256...",          // 동일 파일 재업로드 감지
    "mime_type":  "application/pdf",
    "page_count": 3,
    "language":   "ko",                 // ko | en | ja | unknown
    "text_source_summary": { "TEXT_LAYER": 3 }
  },

  "pages": [{
    "page": 1,
    "text_source": "TEXT_LAYER",        // TEXT_LAYER | OCR | VERIFY
    "signals": { "char_count": 1594, "chars_per_kpx": 3.18,
                 "image_coverage": 0.0, "image_count": 0, "bad_char_count": 0 },
    "tables": [ [["구분","내용"], ["...","..."]] ],   // 페이지 내 표. 당사자표·별지표
    "text": "페이지 원문"
  }],

  "clauses": [{
    "clause_no":  "제3조",
    "kind":       "ARTICLE",            // FRONT_MATTER | ARTICLE | SCHEDULE | GRANT_ITEM
    "title":      "이용허락",
    "page_start": 1,
    "page_end":   1,
    "char_start": 1010,                 // full_text 기준 offset
    "char_end":   1361,
    "text":       "조항 전문",
    "pages":      [1],
    "page_parts": [{ "page": 1, "char_start": 1010, "char_end": 1361, "text": "..." }]
  }],

  "chunks": [{
    "chunk_index": 5,
    "clause_no":   "제3조",
    "clause_title":"이용허락",
    "page":        1,                   // 항상 단일 페이지
    "lang":        "ko",
    "chunk_text":  "...",
    "char_start":  1010,
    "char_end":    1361,
    "clause_page_span": [1, 1]
  }],

  "full_text": "노이즈 제거 후 전체 텍스트"
}
```

### `kind` — 분해 단위 종류

| kind | 의미 |
|---|---|
| `FRONT_MATTER` | 표제·당사자표·전문. **당사자명·체결일·계약명**이 여기 있다 |
| `ARTICLE` | 본문 조항 (`제N조` / `第N条` / `Article N`) |
| `SCHEDULE` | 별지 (`별지N` / `別紙N` / `Schedule N`) |
| `GRANT_ITEM` | 별지 안의 개별 권리부여 (`개별 이용허락 N` / `個別許諾 N`) |

> ⚠️ **별지를 반드시 읽어야 한다.**
> T5/T6 계약서는 본문에 권리 내용이 없고 **별지에 작품명·권리·이용방식·지역·기간·독점성·금액이 전부 들어간다.**
> 초기 구현에서 별지를 직전 조항에 흡수시켰다가 `CTR-KO-0015`의 권리 명세를 통째로 놓쳤다.

### `text_source` — 이 페이지를 어떻게 읽었나

| 값 | 의미 | 추출 신뢰도 |
|---|---|---|
| `TEXT_LAYER` | PDF 텍스트 레이어에서 직접 추출 | 높음 |
| `OCR` | 스캔본이라 OCR로 읽음 | **낮게 잡을 것** |
| `VERIFY` | 텍스트가 의심스러워 교차검증 대상 | 중간 |

추출 결과의 `confidence`를 산정할 때 이 값을 반영해 주기 바란다.
OCR로 읽은 페이지에서 나온 값은 사람 검수 우선순위를 높여야 한다.

---

## 3. 넘길 때 권장하는 사용법

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

## 4. DB로 보낼 스키마 정보

### 4.1 추출 결과가 최종적으로 들어갈 형태

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

### 4.2 반드시 지킬 규칙

- **`legal_right`와 `exploitation_mode`를 절대 합치지 않는다.** `exclusivity`도 별도 축이다.
- 정보가 없으면 만들어내지 말고 `UNRESOLVED`로 둔다.
- 정의되지 않은 `ASIA` / `APAC`를 임의 국가목록으로 확장하지 않는다.
- Contract Term을 License Period로 대체하지 않는다.
- 영상 · Remake · OST를 자동으로 같은 RightsGrant에 병합하지 않는다.
- Payment는 `amount` / `currency`만 쓴다. 통화가 다르면 환율 없이 합산하지 않고 `null`.
- 언어 코드는 `JA`(ISO 639-1), 국가 코드는 `JP`(ISO 3166-1). **서로 다른 값이다.**
- dataset ID(`CTR-*` · `GRT-*` · `EVS-*` · `scenario_id` · `content_id`)를 payload에 넣지 않는다.

전체 목록은 [testdata/k-rights/README.md](../../testdata/k-rights/README.md)의 "사용 경계" 참조.

### 4.3 실제 DB 테이블

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

## 5. 아직 미확정 / 협의 필요

1. **이 payload 규격 자체가 `v0.1` 초안이다.** 받는 쪽에서 필요한 필드가 있으면 알려주면 반영한다.
2. **청크 크기** — 현재 최대 1200자, 겹침 150자. RAG 검색 품질 보고 조정한다.
3. **OCR 경로는 아직 미구현이다.** 지금 샘플은 전부 `TEXT_LAYER`다.
   합성데이터 86건이 전부 digital-born이라 OCR이 돌지 않는다.
   OCR 경로 검증은 86건을 래스터화한 파생 세트로 별도 진행할 예정이다.
4. **`VERIFY` 경로의 교차검증 로직 미구현.** 현재는 라우팅 판정만 한다.

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

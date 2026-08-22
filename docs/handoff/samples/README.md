# 샘플 파일 구조 설명

이 폴더에는 계약서 1건당 파일이 2개씩 있다.

| 파일 | 무엇인가 | 누가 보나 |
|---|---|---|
| `<ID>.retrieval.json` | **Task1 최종 출력.** 필드별로 관련 청크를 점수와 함께 묶은 것 | **Task2 담당자** |
| `<ID>.parse.json` | 중간 산출물. 문서를 통째로 파싱한 결과 | 파싱 디버깅용 |

`retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle` 의 반환값이 `*.retrieval.json` 이다.
`*.parse.json` 은 그 재료이며 함수 밖으로 나가지 않는다.

아래 예시 값은 전부 실제 `CTR-KO-0015`(8페이지, 별지 3개, 재이용허락)에서 뽑았다.

---

# 1. `*.retrieval.json` — Task1 최종 출력

## 1.1 최상위

```
schema_version   "mindex.retrieval-bundle.v0.1"
document         문서 메타 9개 필드
retrieval        검색 메타 6개 필드
fields           필드별 검색 결과 6종
chunks[]         10건 — 참조된 청크의 정본
```

`parse.json` 과 달리 `pages` · `clauses` · `full_text` 가 없다. 검색에 걸린 것만 담는다.

## 1.2 `document`

```json
{
  "file_name": "CTR-KO-0015.pdf",
  "file_hash": "881b4fb90a4d7382fe3c05acd9ef03d0608a5f713b7e6c9cf0bec96ffdab4bfc",
  "mime_type": "application/pdf",
  "page_count": 8,
  "language": "ko",
  "text_source_summary": { "TEXT_LAYER": 8 },
  "embedding_model": "intfloat/multilingual-e5-large",
  "embedding_dim": 1024,
  "embedded": false
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `file_name` | string | 업로드 원본 파일명 |
| `file_hash` | string | SHA-256. **동일 파일 재업로드 감지**와 HTTP `ETag` 에 그대로 쓴다. DB `contract_history.file_hash` 대응 |
| `mime_type` | string | 항상 `application/pdf` |
| `page_count` | int | 총 페이지 수 |
| `language` | string | `ko` / `en` / `ja` / `unknown`. 조항 머리 패턴 빈도로 판별 |
| `text_source_summary` | object | 페이지를 어느 경로로 읽었는지 집계. 예 `{"TEXT_LAYER": 6, "OCR": 2}` |
| `embedding_model` | string | 사용(예정) 모델 |
| `embedding_dim` | int | `1024`. DB `contract_chunk.embedding VECTOR(1024)` 와 일치 |
| `embedded` | bool | `false` 면 `chunks[].embedding` 이 전부 `null` |

## 1.3 `retrieval`

```json
{
  "scorer": "lexical-v0",
  "top_k": 5,
  "min_score": 0.15,
  "field_count": 6,
  "chunk_total": 26,
  "chunk_referenced": 10
}
```

| 필드 | 설명 |
|---|---|
| `scorer` | 점수 산정 방식. 현재 어휘 기반. 임베딩 도입 후 `hybrid-v1` 로 바뀐다 |
| `top_k` | 필드당 최대 반환 건수 |
| `min_score` | 이 값 미만은 버린다 |
| `field_count` | `fields` 키 개수 (6) |
| `chunk_total` | 문서 전체 청크 수 |
| `chunk_referenced` | 그중 어느 필드에든 걸린 수. 위 예에서 **26 → 10** 으로 줄었다 |

## 1.4 `fields`

키 6개가 고정으로 있다. 각 값은 **점수 내림차순 배열**이며, 걸린 게 없으면 빈 배열이다.

```
territory · rights_type · period · exclusivity · payment · parties
```

배열 원소 하나:

```json
{
  "chunk_id": "881b4fb90a4d-0022",
  "text": "개별 이용허락 1\n구독형 주문형 영상(SVOD) 이용을 위한 본 개별 이용허락의 권리대상은 …",
  "page": 5,
  "clause": "개별 이용허락 1",
  "location": {
    "page": 5,
    "clause_no": "개별 이용허락 1",
    "clause_kind": "GRANT_ITEM",
    "char_start": 4031,
    "char_end": 4587,
    "clause_page_span": [5, 5]
  },
  "score": 0.9581,
  "matched_field": "territory",
  "match_reasons": ["+이용지역", "+지역은", "+대한민국"]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `chunk_id` | string | **`chunks[]` 와 잇는 조인 키.** 추출값의 출처를 되짚을 때 이 값을 반환하면 된다 |
| `text` | string | 청크 본문. 편의상 중복해 넣었고 정본은 `chunks[]` 쪽이다 |
| `page` | int | 페이지 번호. 항상 단일 값 |
| `clause` | string | 조항 라벨 |
| `location` | object | Evidence `{page, clause, quote}` 를 만들 재료. 아래 참조 |
| `score` | float | 0~1. 이 필드와의 관련도 |
| `matched_field` | string | 이 배열이 속한 필드명 |
| `match_reasons` | string[] | 어떤 패턴이 걸렸는지. `+` 가점 / `-` 감점. 디버깅·튜닝용 |

### `location`

| 필드 | 설명 |
|---|---|
| `page` | 이 청크가 속한 페이지 |
| `clause_no` | 조항 라벨 |
| `clause_kind` | 조항 종류 (아래 표) |
| `char_start` / `char_end` | 문서 전체 텍스트 기준 문자 offset. `[start, end)` 반열림 |
| `clause_page_span` | **원 조항이 걸친 페이지 범위.** 청크가 p2에 있어도 조항은 `[1,2]` 일 수 있다 |

## 1.5 `chunks[]` — 정본

같은 청크가 여러 필드에 걸리므로 본문을 여기 한 번만 둔다.

```json
{
  "chunk_id": "881b4fb90a4d-0000",
  "text": "『밤을 건너는 도시』 콘텐츠 배급 및 재이용허락 기\n본계약서\n…",
  "page": 1,
  "clause": "__FRONT_MATTER__",
  "clause_kind": "FRONT_MATTER",
  "lang": "ko",
  "location": { "…": "위와 동일" },
  "embedding": null
}
```

| 필드 | 설명 |
|---|---|
| `chunk_id` | `{file_hash 앞 12자}-{순번 4자리}` |
| `lang` | 청크 언어 |
| `embedding` | 1024차원 float 배열. Worker 가 `contract_chunk.embedding` 에 적재할 값 |

---

# 2. `*.parse.json` — 중간 산출물

## 2.1 최상위

```
schema_version   "mindex.ocr-parse.v0.4"
document         문서 메타 10개 필드
pages[]          8건  — 페이지별 1차 결과
clauses[]        24건 — 조항 단위 2차 가공
chunks[]         26건 — 임베딩·검색 단위
full_text        5,141자 — 노이즈 제거 후 전체 텍스트
```

`document` 는 `retrieval.json` 과 같고 `text_normalization` 이 하나 더 있다.

| 필드 | 설명 |
|---|---|
| `text_normalization` | `"NFC"`. 정규화가 적용됐다는 표시 (아래 4절) |

## 2.2 `pages[]` — 1차 파싱

```json
{
  "page": 1,
  "text_source": "TEXT_LAYER",
  "signals": {
    "char_count": 1097,
    "chars_per_kpx": 2.19,
    "image_coverage": 0.0,
    "image_count": 0,
    "bad_char_count": 0
  },
  "tables": [
    [["문서 참조번호\nKO-2027-004-003", "계약 체결일\n2027년 3월 7일", "Status\n정식 Pilot · 검토 전 DRAFT"]]
  ],
  "text": "『밤을 건너는 도시』 콘텐츠 배급 및 재이용허락 기\n본계약서\n…"
}
```

| 필드 | 설명 |
|---|---|
| `page` | 1부터 시작 |
| `text_source` | 이 페이지를 어떻게 읽었나 (아래 표) |
| `signals` | 위 판정의 근거 수치 |
| `tables` | 페이지 내 표를 2차원 배열로. **당사자표·별지표가 여기 정확하게 들어온다** |
| `text` | 페이지 원문. **머리말/꼬리말 제거 전** |

### `signals`

| 필드 | 설명 |
|---|---|
| `char_count` | 추출된 문자 수 |
| `chars_per_kpx` | 페이지 면적 1,000px² 당 문자 수. 정상 0.15~7.6, 스캔본 0.0 |
| `image_coverage` | 이미지가 페이지를 덮은 비율. 스캔본은 1.0 |
| `image_count` | 이미지 객체 수 |
| `bad_char_count` | `U+FFFD` 등 깨진 문자 수 |

`tables` 는 본문 텍스트로도 같은 내용이 나오지만 표 쪽이 더 정확하다.
**당사자·금액은 표를 우선 보는 편이 낫다.**

## 2.3 `clauses[]` — 2차 가공

```json
{
  "clause_no": "개별 이용허락 1",
  "kind": "GRANT_ITEM",
  "title": "",
  "page_start": 5,
  "page_end": 5,
  "char_start": 4031,
  "char_end": 4587,
  "text": "개별 이용허락 1\n구독형 주문형 영상(SVOD) 이용을 위한…",
  "pages": [5],
  "page_parts": [
    { "page": 5, "char_start": 4031, "char_end": 4587, "text": "…" }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `clause_no` | 조항 라벨. `제3조` · `別紙 1` · `Article 5` · `__FRONT_MATTER__` |
| `kind` | 분해 단위 종류 (아래 표) |
| `title` | 괄호 안 제목. `GRANT_ITEM` 은 제목이 없어 `""` |
| `page_start` / `page_end` | 다르면 **조항이 페이지를 넘어간 것** |
| `char_start` / `char_end` | `full_text` 기준 offset |
| `text` | 조항 전문 |
| `pages` | 걸친 페이지 목록 |
| `page_parts[]` | **페이지 경계로 자른 조각.** 청크 생성의 재료 |

`page_parts` 실제 예 — 제3조가 p1에서 시작해 p2로 넘어간 경우:

```
제3조  p1-2, char 1028~1138
  p1  char 1028~1038  "제3조 (이용허락)"
  p2  char 1039~1138  "개별 권리대상과 이용허락 범위는 별지 1에 기재하며…"
```

## 2.4 `chunks[]`

`retrieval.json` 의 `chunks[]` 와 대응하지만 필드명이 조금 다르다.

```json
{
  "chunk_id": "881b4fb90a4d-0022",
  "chunk_index": 22,
  "clause_no": "개별 이용허락 1",
  "clause_title": "",
  "clause_kind": "GRANT_ITEM",
  "page": 5,
  "lang": "ko",
  "chunk_text": "개별 이용허락 1\n구독형 주문형 영상(SVOD) 이용을 위한…",
  "location": { "page": 5, "clause_no": "개별 이용허락 1", "clause_kind": "GRANT_ITEM",
                "char_start": 4031, "char_end": 4587, "clause_page_span": [5, 5] },
  "char_start": 4031,
  "char_end": 4587,
  "clause_page_span": [5, 5],
  "embedding": null
}
```

| `parse.json` | `retrieval.json` | DB 컬럼 |
|---|---|---|
| `chunk_text` | `text` | `contract_chunk.chunk_text` |
| `clause_no` | `clause` | `contract_chunk.clause_no` |
| `page` | `page` | `contract_chunk.page` |
| `lang` | `lang` | `contract_chunk.lang` |
| `embedding` | `embedding` | `contract_chunk.embedding` |

`chunk_index` 는 문서 내 순번(정수)이고 `chunk_id` 는 파일 간 유일한 문자열이다.
**조인에는 `chunk_id` 를 쓴다.**

---

# 3. 열거값

## `kind` / `clause_kind` — 분해 단위 종류

| 값 | 의미 |
|---|---|
| `FRONT_MATTER` | 표제·당사자표·전문. **계약명·당사자명·체결일**이 여기 있다 |
| `ARTICLE` | 본문 조항. `제N조` / `第N条` / `Article N` |
| `SCHEDULE` | 별지. `별지N` / `別紙N` / `Schedule N` |
| `GRANT_ITEM` | 별지 안의 개별 권리부여. `개별 이용허락 N` / `個別許諾 N` |
| `UNSEGMENTED` | 조항 패턴을 하나도 못 찾은 경우. 문서 전체가 한 덩어리 |

> **별지를 반드시 읽어야 한다.** T5/T6 계약서는 본문에 권리 내용이 없고
> 별지에 작품명·권리·이용방식·지역·기간·독점성·금액이 전부 들어간다.
> 개발 중 별지를 직전 조항에 흡수시켰다가 `CTR-KO-0015` 의 권리 명세를 통째로 놓친 적이 있다.

## `text_source` — 페이지를 어떻게 읽었나

| 값 | 의미 | 추출 신뢰도 |
|---|---|---|
| `TEXT_LAYER` | PDF 텍스트 레이어에서 직접 추출 | 높음 |
| `OCR` | 스캔본이라 OCR로 읽음 | **낮게 잡을 것** |
| `VERIFY` | 텍스트가 의심스러워 교차검증 대상 | 중간 |

추출 결과의 `confidence` 를 산정할 때 반영해 주기 바란다.
OCR로 읽은 페이지에서 나온 값은 사람 검수 우선순위를 높여야 한다.

---

# 4. `score` 는 어떻게 계산되나

**현재 임베딩은 사용되지 않는다.** `scorer: "lexical-v0"` 가 그 표시이고
`embedding` 은 전부 `null` 이다. 점수는 정규식 가점/감점으로 낸다.

```
score = sigmoid( ((가점 합계 − 감점 합계) × kind_prior − 4) / 3 )
```

## 실제 계산 — `territory` 필드

**정답 청크 (`개별 이용허락 1`)**

```
+3.00   "이용지역"   1회
+2.00   "지역은"     1회
+1.69   "대한민국"   2회      반복은 w×(1+ln n) 로 체감 적용
──────────────────────────────
가점 6.69 − 감점 0.00 = 6.69
× kind_prior(GRANT_ITEM) 2.0 = raw 13.39
sigmoid((13.39−4)/3) = 0.9581
```

**함정 청크 (`제18조` 준거법)**

```
+1.00   "대한민국"   1회
-4.00   "준거법"
──────────────────────────────
가점 1.00 − 감점 4.00 = −3.00
× kind_prior(ARTICLE) 1.0 = raw −3.00
sigmoid((−3−4)/3) = 0.0884      min_score 0.15 미달 → 배제
```

같은 "대한민국"이 들어 있어도 0.958 대 0.088로 갈린다.

## 구성 요소

| | 역할 |
|---|---|
| **positive** | 필드 고유 표현에 가점. 특이도에 비례 — `이용지역`(3.0) > `지역은`(2.0) > `대한민국`(1.0) |
| **negative** | 함정 제거. `준거법`(−4.0) · `계약기간`(−3.5) · `전속관할`(−4.0) 등 |
| **kind_prior** | 조항 종류 가중. territory 기준 `GRANT_ITEM` ×2.0 / `SCHEDULE` ×1.5 / `ARTICLE` ×1.0 / `FRONT_MATTER` ×0.3 |

`sigmoid` 는 순위 매기기용 눌러담기이며 절대적 의미는 없다.
정의는 [scripts/build_retrieval_bundle.py](../../../scripts/build_retrieval_bundle.py) 의 `FIELD_SPECS` 에 있다.

## 임베딩을 붙이면

```
현재   score = lexical                          scorer: "lexical-v0"
이후   score = α·semantic + β·lexical           scorer: "hybrid-v1"
```

**`fields` · `chunks` 의 구조와 필드는 그대로**이고 `score` 값과 `scorer` 문자열만 바뀐다.
지금 mock 을 만들어도 재작업이 없다.

어휘 점수를 계속 섞는 이유는 감점 때문이다. 의미유사도만으로는
"대한민국 법률에 따라 해석한다"와 "이용지역은 대한민국이고"를 구분하기 어렵다.

## ⚠️ 한계

**패턴이 이 합성데이터 86건의 표현에 맞춰져 있다.**
`이용지역은` · `독점적으로 허락한다` · `총 계약대가는` 같은 정형 표현을 전제로 잡았고,
이 데이터셋은 템플릿 T1~T6에서 생성돼 표현이 일정하다.

실제 사용자가 올리는 계약서가 `서비스 대상 지역` 처럼 다르게 쓰면 회수가 떨어진다.
그 간극을 메우는 것이 임베딩이며, hybrid 로 가는 진짜 이유다.

샘플 10건에서 `territory` · `period` · `exclusivity` top-1 이 전부 정답 조항을 가리키지만
**이 코퍼스 기준의 결과**임을 감안해 주기 바란다.

---

# 5. 알아둘 점

## 5.1 텍스트 정규화가 적용돼 있다

원본 PDF 텍스트를 그대로 쓰지 않는다. 실측으로 확인된 문제 두 가지를 고쳐 넣었다.

| 문제 | 실측 | 처리 |
|---|---|---|
| 일본어 PDF가 정규 한자 대신 **CJK 호환한자**(U+F900~U+FAFF) 출력. 예) `利`(U+5229)가 U+F9DD | JP 28건 전부, 4,865자 | **NFC 정규화** |
| 영문 PDF가 하이픈 자리에 **SOFT HYPHEN**(U+00AD) 사용. 날짜 `2026-01-01` 이 `2026<AD>01<AD>01` | 119자 | 줄끝(2자) 제거 / 문장 내부(117자) 일반 하이픈 치환 |

둘 다 두면 정규식·LLM 추출·임베딩·Evidence 문자열 대조가 모두 어긋난다.
정답지인 canonical Markdown 은 정규형이므로, 정규화 후에야 문자열이 일치한다.

## 5.2 offset 정합성

```
full_text[char_start:char_end] == chunk_text     26/26 일치
full_text[char_start:char_end] == clause.text    24/24 일치
```

`char_start` / `char_end` 는 `full_text` 기준이며 반열림 구간 `[start, end)` 이다.
단위는 **Unicode code point** 이고 줄바꿈은 LF 다.

## 5.3 중복 필드

`parse.json` 의 `chunks[]` 에서 `char_start` · `char_end` · `clause_page_span` 이
최상위와 `location` 안에 **양쪽에 있다. 값은 같다.**
`location` 은 요청 DTO 에 맞춰 추가한 것이고 기존 필드는 하위호환으로 남겼다.
어느 쪽을 봐도 무방하다.

`retrieval.json` 의 `fields[].text` 도 `chunks[].text` 와 중복이다.
`fields` 만 보고 바로 프롬프트를 만들 수 있게 한 의도이며, 정본은 `chunks[]` 다.

## 5.4 `chunk_id` 는 파일이 바뀌면 전부 바뀐다

`{file_hash 앞 12자}-{순번}` 이므로 같은 계약서를 수정해 재업로드하면
완전히 다른 id 세트가 된다. `contract_history` 가 문서 버전별로 행을 나누는 설계와 맞다.

## 5.5 `embedding` 은 현재 전부 `null`

`--embed` 플래그로 채우는데 모델(약 2.2GB)을 아직 받지 않았다.
**형식은 확정**이므로 mock 작성에는 지장이 없다.

---

# 6. 샘플 10건

86건 전부가 아니라 언어 × 템플릿 × 계약유형이 골고루 덮이도록 골랐다.
`KO 4 / EN 3 / JP 3`, 템플릿 `T1~T6` 전부, `DIRECT 8 / SUBLICENSE 2`, 3~10페이지.

| 파일 | 언어 | T | 유형 | 페이지 | 조항 | 청크 | 특징 |
|---|---|---|---|---:|---:|---:|---|
| `CTR-KO-0001` | ko | T1 | DIRECT | 3 | 20 | 22 | 가장 단순. 여기서 시작 |
| `CTR-EN-0001` | en | T1 | DIRECT | 3 | 20 | 21 | 영문 기본형 |
| `CTR-JP-0001` | ja | T1 | DIRECT | 3 | 20 | 21 | 일문 기본형 |
| `CTR-EN-0017` | en | T1 | **SUB** | 5 | 20 | 22 | 재이용허락 — 권한체인 |
| `CTR-JP-0002` | ja | T2 | DIRECT | 4 | 20 | 21 | 방송 방영권·배신권 |
| `CTR-EN-0006` | en | T3 | DIRECT | 4 | 20 | 23 | 단일 이용방식 |
| `CTR-KO-0014` | ko | T4 | DIRECT | 7 | 20 | 21 | **별지 없이 본문에 복수 Grant** |
| `CTR-KO-0015` | ko | T5 | **SUB** | 8 | 24 | 26 | **별지 3개 + 재이용허락** |
| `CTR-JP-0015` | ja | T5 | DIRECT | 10 | 25 | 28 | **별지 5개.** 최대 난이도 |
| `CTR-KO-0006` | ko | T6 | DIRECT | 8 | 24 | 26 | **OST 음악 권리처리 별지** |

난이도 순서: `CTR-KO-0001` → `CTR-KO-0014` → `CTR-KO-0015` → `CTR-JP-0015`

정답(Ground Truth)은 [testdata/k-rights/annotations/](../../../testdata/k-rights/annotations/) 에 있다.
`ground_truth.json` 에서 같은 `contract_id` 를 찾으면 추출 결과를 대조할 수 있다.

---

전체 인계 문서는 [../README.md](../README.md) 를 참조.

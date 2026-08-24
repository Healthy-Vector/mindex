# RetrievalBundle 샘플 — 구조와 필드 설명

`schema_version: mindex.retrieval-bundle.v0.2`

Task1(OCR·파싱·임베딩)이 Task2(LLM 추출·정규화)에 넘기는 형식이다.
이 폴더만 받아도 읽을 수 있게 자기완결적으로 썼다.

```python
from app.pipeline import retrieve_contract_chunks

bundle = retrieve_contract_chunks(pdf_bytes)     # RetrievalBundle (pydantic)
payload = bundle.model_dump(mode="json")         # 여기 있는 .json 과 같은 형태
```

규격 정의는 [`app/schemas/pipeline.py`](../../../app/schemas/pipeline.py)에 있다.
샘플은 [`scripts/make_handoff_samples.py`](../../../scripts/make_handoff_samples.py)로
재생성하며, **실제 파이프라인 출력 그 자체**다(별도 생성기가 아니다).

> **v0.1에서 바뀐 점**
> `fields[]`에서 본문(`text`·`page`·`clause`·`location`)이 빠졌다. `chunk_id`로
> `chunks[]`를 찾아 읽는다. 이유는 아래 2절 참조.
> `chunks[].page`는 `page_start`/`page_end` 범위가 됐고, `clause`는 `clause_no`로
> 이름이 바뀌었다. 중간 산출물 `*.parse.json`은 더 이상 만들지 않는다.

---

## 1. 전체 구조 — 다섯 덩어리

```jsonc
{
  "schema_version": "mindex.retrieval-bundle.v0.2",
  "document":  { ... },   // 이 PDF가 무엇인가
  "retrieval": { ... },   // 어떻게 회수했는가
  "fields":    { ... },   // 필드별로 어디를 봐야 하나  ← 여기서 시작
  "chunks":    [ ... ]    // 본문 조각 (fields가 가리키는 대상)
}
```

**`fields`는 색인, `chunks`는 자료다.** 도서관으로 치면 `fields`가 주제별 색인
카드고 `chunks`가 책이다. 카드에는 청구기호(`chunk_id`)와 관련도(`score`)만
적혀 있고 내용은 책에 있다.

읽는 순서는 이렇다.

```
fields["territory"][0].chunk_id  →  chunks[] 에서 같은 id를 찾는다  →  .text 를 읽는다
```

---

## 2. `fields` — 어디를 봐야 하나

필드 이름 → 점수 높은 순 목록. **본문은 담지 않는다.**

```jsonc
"fields": {
  "territory": [
    {
      "chunk_id": "881b4fb90a4d-0020",
      "score": 0.9581,
      "lexical": 0.9581,
      "semantic": null,
      "matched_field": "territory",
      "match_reasons": ["+이용지역", "+지역은", "+대한민국"]
    },
    ...
  ],
  "rights_type": [...], "period": [...],
  "exclusivity": [...], "payment": [...], "parties": [...]
}
```

| 필드 | 뜻 |
|---|---|
| `chunk_id` | `chunks[]`를 찾는 키 |
| `score` | 최종 점수 0~1. 정렬 기준 |
| `lexical` | 어휘 점수 0~1 — 실제 단어가 있는가 |
| `semantic` | 의미 점수(코사인) −1~1. 임베딩을 안 쓰면 `null` |
| `matched_field` | 어느 필드로 잡혔는지. 항상 바깥 키와 같다 |
| `match_reasons` | 어떤 신호가 걸렸는지. `+`는 가점, `-`는 감점 |

### 왜 본문을 뺐나

**한 청크가 여러 필드에 동시에 잡힌다.** `개별 이용허락 1` 같은 청크에는 지역·
기간·독점성·권리종류가 전부 들어 있어서 4~5개 필드의 상위에 걸린다.
v0.1은 그때마다 본문을 통째로 복사했다. `CTR-KO-0015` 실측:

```
회수 결과 20건  /  실제 참조된 청크 10개
fields[] 안 본문 6977자   chunks[] 본문 2945자   →  중복 4032자 (2.4배)
```

크기 문제만이 아니다. **본문이 두 곳에 있으면 어느 쪽이 진짜인지 애매해진다.**
임베딩까지 채우면 벡터(청크당 약 19.4KB)도 중복될 뻔했다.

### 필드는 항상 6개다

값이 비어도 키는 있다. `"payment": []`는 "지급 관련 청크를 못 찾았다"는 뜻이다.

> ⚠️ **`rights_type`은 회수 질의 이름일 뿐이다.**
> 추출 결과 필드로 그대로 굳으면 안 된다. ERD v3에서 이 축은
> `legal_right`(저작재산권의 지분권)와 `exploitation_mode`(이용형태)로 분리돼
> 있고, 프로젝트가 두 축을 절대 합치지 않는다고 못박았다. 합치면 R3(권리 위계)·
> R4(이용형태) 판정이 불가능해진다. Ground Truth도 `LEGAL_RIGHT` /
> `EXPLOITATION_MODE`로 이미 나뉘어 있다.

---

## 3. `chunks` — 본문 조각

`fields`가 **참조한 청크만** 담는다. 문서 전체 청크가 아니다.
(전체 수는 `retrieval.chunk_total`, 참조된 수는 `retrieval.chunk_referenced`)

```jsonc
{
  "chunk_id":     "881b4fb90a4d-0000",
  "chunk_index":  0,
  "clause_no":    "__FRONT_MATTER__",
  "clause_title": "표제·당사자·전문",
  "clause_kind":  "FRONT_MATTER",
  "lang":         "ko",
  "text":         "『밤을 건너는 도시』 콘텐츠 배급 및 재이용허락 기\n본계약서\n...",
  "page_start":   1,
  "page_end":     1,
  "page":         1,
  "location":     { "page_start": 1, "page_end": 1, "clause_no": "__FRONT_MATTER__",
                    "clause_kind": "FRONT_MATTER", "char_start": 0, "char_end": 581 },
  "char_start":   0,
  "char_end":     581,
  "embedding":    null
}
```

| 필드 | 뜻 |
|---|---|
| `chunk_id` | `{문서해시 앞 12자}-{4자리 순번}`. 문서 안에서 유일 |
| `chunk_index` | 문서 안 순서. 0부터 |
| `clause_no` | `제3조` · `Article 5` · `別紙 1` · `개별 이용허락 2` 등 |
| `clause_title` | 조항 제목. 없으면 빈 문자열 |
| `clause_kind` | 아래 4절 참조 |
| `lang` | `ko` · `ja` · `en` · `unknown` |
| `text` | 조각 본문. **정규화된 텍스트** (7절 참조) |
| `page_start` / `page_end` | 이 조각이 걸친 페이지 범위 |
| `page` | DB의 단일 `page` 컬럼 호환값. 항상 `page_start`와 같다 |
| `location` | 위 값들을 한 덩어리로. Evidence 인용의 좌표 |
| `char_start` / `char_end` | **문서 전체 텍스트 기준** 문자 offset |
| `embedding` | 1024차원 벡터. 임베딩을 안 돌리면 `null` |

### 페이지가 왜 범위인가

**계약서 조항은 페이지를 자주 넘어간다.** 86건 실측에서 1825개 조항 중
**172개(9.4%)** 가 2페이지 이상에 걸쳤고, 문서 기준으로는 **80/86건(93%)** 이다.

예전에는 `page`가 정수 하나여서 페이지 경계에서 청크를 잘랐다. 그런데 페이지
넘김은 종이가 꽉 차서 생기는 사건이라 문장 한가운데 떨어진다(172건 중 130건).
결과로 Evidence 정답 781건 중 **55건(7%)** 이 두 청크에 걸쳐 어떤 검색으로도
회수되지 않았다. 조항 단위로 바꾸고 페이지를 범위로 기록하니
**의미검색 Recall@5가 85.3% → 97.6%** 가 됐다.

`page`(단일값)는 DB 컬럼 분리 협의가 끝날 때까지만 남겨 둔다.

---

## 4. 열거값

**`clause_kind`** — 이 조각이 문서의 어떤 부분인가

| 값 | 뜻 |
|---|---|
| `FRONT_MATTER` | 표제·당사자·전문. 당사자 정보가 여기 있다 |
| `ARTICLE` | 본문 조항 |
| `SCHEDULE` | 별지 |
| `GRANT_ITEM` | 별지 안의 **개별 권리부여 한 건** |
| `UNSEGMENTED` | 조항 머리를 하나도 못 찾은 문서 |

**`document.text_source_summary`의 키 (`TextSource`)** — 텍스트를 어디서 얻었나

| 값 | 뜻 |
|---|---|
| `TEXT_LAYER` | 디지털 PDF. 텍스트가 파일 안에 있다 |
| `OCR` | 스캔본. 이미지를 읽어야 한다 |
| `VERIFY` | 애매함. 텍스트 레이어와 OCR을 대조해야 한다 |

> **T5·T6 템플릿 주의.** 권리 명세(작품·권리·지역·기간·독점성·금액)가 본문이
> 아니라 **별지에 들어간다.** 본문 조항에는 "별지 1에 정한다"만 쓰여 있다.
> 그래서 `GRANT_ITEM` 청크를 놓치면 권리 정보를 통째로 잃는다.
> 개발 중 실제로 `CTR-KO-0015`의 권리 명세가 제18조에 흡수돼 사라진 적이 있다.

---

## 5. `document` · `retrieval`

```jsonc
"document": {
  "file_name": "CTR-KO-0015.pdf",
  "file_hash": "881b4fb90a4d...",        // SHA-256 (64자)
  "mime_type": "application/pdf",
  "page_count": 8,
  "language": "ko",
  "text_source_summary": { "TEXT_LAYER": 8 },
  "text_normalization": "NFC",
  "embedding_model": "intfloat/multilingual-e5-large",
  "embedding_dim": 1024,
  "embedded": false,                     // 벡터가 채워졌는가
  "full_text_length": 5141
}
```

```jsonc
"retrieval": {
  "scorer": "lexical-v0",     // 또는 "hybrid"
  "semantic_weight": 0.0,     // 의미 점수 비중
  "top_k": 5,                 // 필드당 최대 결과 수
  "min_score": 0.15,          // 이 미만은 버린다
  "field_count": 6,
  "clause_total": 24,         // 분해된 조항 수
  "chunk_total": 24,          // 만들어진 청크 수
  "chunk_indexable": 23,      // 검색 색인에 들어간 수
  "chunk_referenced": 10      // fields[]가 참조한 수 = chunks[] 길이
}
```

`chunk_indexable`이 `chunk_total`보다 작은 것은 **내용 없는 별지 제목**을
색인에서 뺐기 때문이다(`별지 1 — 개별 이용허락 명세` 같은 15자짜리).
86건에서 23건 발생하며 전부 별지 제목이다. 이런 조각은 의미검색에서
어떤 질의와도 어중간하게 가까워서 상위를 차지하고 정답을 밀어낸다.

---

## 6. `score`는 어떻게 나오나

### 지금은 임베딩을 쓰지 않는다

기본값 `semantic_weight = 0.0`, 즉 **`score == lexical`** 이다. 벡터는
`chunks[].embedding`에 실어 보내지만 **점수 계산에는 안 쓴다.**

```
score = (1 - semantic_weight) × lexical + semantic_weight × semantic
```

### 어휘 점수 산식

필드마다 **양성 패턴(가점)** 과 **부정 패턴(감점)**, 조항 종류 가중이 있다.

```
가점  = Σ 매칭된 양성패턴 가중치      (반복 등장은 log로 체감)
감점  = Σ 매칭된 부정패턴 가중치
raw   = (가점 - 감점) × 조항종류_가중
score = 1 / (1 + exp(-(raw - 4) / 3))
```

양성 신호가 **하나도 없으면 즉시 0**이다. 조항 종류 가중만으로 점수가 붙으면
무관한 청크가 상위를 채운다.

### 실제 계산 — 같은 "대한민국"이 갈리는 이유

`territory`에서 `CTR-KO-0015`:

```
[개별 이용허락 1]  +이용지역 3.0  +지역은 2.0  +대한민국 1.0(2회 → 1.69)
                   가점 6.69, 감점 0, GRANT_ITEM 가중 2.0
                   raw = 13.39  →  score 0.9581      ← 1위

[제18조 준거법]    +대한민국 1.0
                   -준거법 4.0
                   raw = (1.00 - 4.00) × 1.0 = -3.00  →  score 0.0884
                   min_score 0.15 미만이라 버려짐
```

**"대한민국 법률에 따라 해석한다"는 이용지역이 아니다.** 순수 의미유사도로는
이 구분이 어렵고 명시적 감점이 효과적이다. 이것이 어휘 점수를 먼저 두는 이유다.

### 임베딩을 켜면 왜 그냥 좋아지지 않나

2000청크 실측에서 e5 코사인이 좁은 구간에 눌려 있다.

```
청크 간 코사인:  min 0.681   중앙 0.778   p95 0.855
```

폭이 0.17뿐이라 **절대 임계값을 쓸 수 없고**, argmax가 내용이 아니라 잡음으로
정해진다. `semantic_weight=0.5`로 돌리면 이렇게 된다.

```
1위  0.8957 = 0.5×0.9581 + 0.5×0.8333   [개별 이용허락 1]  ← 정답
2위  0.4294 = 0.5×0.0884 + 0.5×0.7704   [제18조 준거법]    ← 감점당한 게 되살아남
3위  0.4132 = 0.5×0.0000 + 0.5×0.8265   [표제부]
4위  0.4086 = 0.5×0.0000 + 0.5×0.8172   [제4조]
```

2~5위는 어휘가 0인데 의미가 0.81~0.83으로 전부 비슷하다. 그래서
**가중치는 Ground Truth로 측정해서 정한다.** 그전까지 기본값은 0이다.

---

## 7. 알아둘 것

### 어휘 회수율 수치는 낙관적 상한이다

86건 Ground Truth 기준 어휘 단독 Recall@5는 99.8%지만, **패턴을 바로 이
합성데이터 표현(`이용지역은`, `총 계약대가는`)에 맞춰 썼기 때문**이다.
실제 계약서가 `서비스 대상 지역`처럼 쓰면 떨어진다.
튜닝 없이 잰 의미검색 97.6% 쪽이 일반화 신호로는 더 정직하다.

### `text`는 정규화된 값이다

원본 PDF 바이트와 글자가 다를 수 있다. `char_start`/`char_end`는 **정규화 후
텍스트 기준**이다.

- **NFC 정규화** — 일본어 PDF가 정규 한자 대신 CJK 호환한자(U+F900~U+FAFF)를
  내보낸다. JP 28건 전부에서 4,865자 출현했다. 예) `利`(U+5229)가 U+F9DD로.
  정답지인 canonical Markdown은 정규형이라 NFC를 적용해야 대조가 맞는다.
- **소프트하이픈(U+00AD)** — 영문 PDF가 보이는 하이픈 자리에 이 문자를 쓴다.
  날짜 `2026-01-01`이 실제로는 U+00AD를 낀 형태였다. 줄끝이면 지우고
  그 밖에는 일반 하이픈으로 바꾼다.

### offset 정합성은 규격이 강제한다

`char_end - char_start == len(text)`가 스키마 검증 대상이다. 어긋나면 번들 생성
자체가 실패한다. Evidence 인용이 밀리면 사용자 화면에 엉뚱한 구절이 근거로 뜨기
때문이다. 실제 86건이 전부 통과한다.

### `chunk_id`는 문서 안에서만 안정적이다

문서 해시 + 순번이라 **같은 PDF를 같은 코드로 돌리면 항상 같다.** 다만 청킹
방식을 바꾸면 전부 바뀐다. **DB의 영구 키로 쓰지 말 것.**

### `embedding`은 샘플 1건에만 들어 있다

`CTR-KO-0001`만 벡터를 채웠다(212KB). 10건을 다 채우면 5.9배로 불어나 사람이
JSON을 열어볼 수 없다. 형식 확인에는 1건이면 충분하다.

**벡터는 버리면 안 된다.** Task1은 `contract_id`·`tenant_id`를 받지 않아 DB에
쓸 수 없으므로, Worker가 저장 확정 시점에 `contract_chunk.embedding`으로
적재해야 한다. 안 그러면 검색할 때마다 PDF를 다시 파싱하게 된다.

---

## 8. 샘플 10건

언어 × 템플릿 × 계약유형이 골고루 덮이도록 골랐다.
`KO 4 / EN 3 / JP 3`, 템플릿 `T1~T6` 전부, `DIRECT 8 / SUB 2`, 3~10페이지.

| 파일 | 언어 | T | 유형 | 페이지 | 조항 | 청크 | 참조 | 특징 |
|---|---|---|---|---:|---:|---:|---:|---|
| `CTR-KO-0001` | ko | T1 | DIRECT | 3 | 20 | 20 | 10 | 가장 단순. **벡터 포함** |
| `CTR-EN-0001` | en | T1 | DIRECT | 3 | 20 | 20 | 11 | 영문 기본형 |
| `CTR-JP-0001` | ja | T1 | DIRECT | 3 | 20 | 20 | 10 | 일문 기본형 |
| `CTR-EN-0017` | en | T1 | **SUB** | 5 | 20 | 20 | 12 | 재이용허락 — 권한체인(R8) |
| `CTR-JP-0002` | ja | T2 | DIRECT | 4 | 20 | 20 | 9 | 방송 방영권·배신권 |
| `CTR-EN-0006` | en | T3 | DIRECT | 4 | 20 | 20 | 12 | 단일 이용방식 |
| `CTR-KO-0014` | ko | T4 | DIRECT | 7 | 20 | 21 | 11 | **별지 없이 본문에 복수 Grant** |
| `CTR-KO-0015` | ko | T5 | **SUB** | 8 | 24 | 24 | 10 | **별지 3개 + 재이용허락** |
| `CTR-JP-0015` | ja | T5 | DIRECT | 10 | 26 | 26 | 11 | **별지 5개**. 최대 난이도 |
| `CTR-KO-0006` | ko | T6 | DIRECT | 8 | 24 | 24 | 10 | **OST 음악 권리처리 별지** |

권장 순서: `CTR-KO-0001` → `CTR-KO-0014`(별지 없는 복수 Grant) →
`CTR-KO-0015`(별지) → `CTR-JP-0015`(별지 5개).

정답(Ground Truth)은 [`testdata/k-rights/annotations/`](../../../testdata/k-rights/annotations/)에 있다.
`ground_truth.json`에서 같은 `contract_id`를 찾으면 추출 결과를 대조할 수 있다.

# DB 계약 추출값 Projection 제안

status: DRAFT  
version: 0.1  
date: 2026-08-19
updated: 2026-08-22

## 목적

상세 OCR/추출 결과에서 DB가 실제로 사용할 수 있는 canonical 값만 골라 전달한다. 이 schema는 OCR 결과 전체를 보존하는 schema가 아니며 DB 테이블 구조도 규정하지 않는다.

```text
Rich Extraction
  field_status + raw_expression + Evidence + modifier
        ↓ validate / normalize / apply modifier
DB Projection
  유효한 canonical 값 + compact Evidence
```

## Transport envelope

문서 연결정보는 body가 아니라 API transport envelope에 둔다.

```json
{
  "request_id": "caller-request-id",
  "source_document_ref": "caller-owned-opaque-reference",
  "payload": {}
}
```

- `request_id`, `source_document_ref`는 호출자가 제공하고 서비스가 그대로 반환한다.
- 데이터셋 ID 또는 DB business ID가 아니다.
- 실제 계약 추출값은 `payload` 안에만 둔다.

## DB payload

```text
payload
├─ schema_version
├─ document_language
└─ contract
   ├─ title
   ├─ agreement_type
   ├─ agreement_date
   ├─ parties[]
   ├─ rights_grants[]
   ├─ payment
   └─ evidence
      ├─ title / agreement_type / agreement_date / parties[]
      ├─ rights_grants[]
      └─ payment
```

## 필드

| 필드 | 형태 | 설명 |
|---|---|---|
| `schema_version` | string | `k-rights.db-contract-projection.v0.1` |
| `document_language` | enum | `JA | KO | EN` |
| `contract.title` | string/null | 계약서 표제 |
| `contract.agreement_type` | enum/null | `DIRECT_LICENSE | SUBLICENSE` |
| `contract.agreement_date` | date/null | `YYYY-MM-DD` |
| `contract.parties` | array | `role`, `name`만 전달 |
| `contract.rights_grants` | array | 유효한 canonical Grant 값 |
| `contract.payment` | object/null | 계약당 단일 종합 금액·통화 |
| `contract.evidence` | JSONB object | 계약·Grant·Payment의 전체 추출 근거를 묶은 단일 컬럼 |

주소, 등록번호, 대표자와 normalized title은 1차 범위에서 제외한다.

### 공통 code 유형

| 구분 | 허용 code | 기준 |
|---|---|---|
| 문서 언어 | `JA | KO | EN` | ISO 639-1. 일본어는 `JP`가 아니라 `JA` |
| 국가 | `KR | US | JP` | ISO 3166-1 alpha-2 |
| 통화 | `KRW | USD | JPY` | ISO 4217 |

- 언어 코드 `JA`와 국가 코드 `JP`를 구분한다.
- `territory_scopes[].members[]`에는 국가 코드만 넣는다.
- `territory_scopes[].term`에는 국가 코드 또는 계약에서 유효하게 정의된 지역 용어를 넣을 수
  있다. 예를 들어 `ASIA`는 지역 용어이며 국가 코드가 아니다.
- 현재 전송 schema의 국가 member allowlist는 `KR`, `US`, `JP`다. 계약상 정의에 그 밖의
  국가가 포함되면 임의로 버리지 않고 DB projection을 보류하거나 interface 확장이 필요하다.
- 내부 합성데이터의 기존 언어 식별자 `JP`는 변경하지 않으며, DB 전송 경계에서만 `JA`로
  매핑한다.

## RightsGrant

```json
{
  "subjects": [],
  "legal_rights": [],
  "exploitation_modes": [],
  "territory_scopes": [],
  "license_period": null,
  "exclusivity": null,
  "authority": null
}
```

Grant 배열 항목에는 Evidence를 넣지 않는다. Grant의 근거는 최하단
`contract.evidence.rights_grants[]`의 같은 배열 순서에 둔다. `grant_ref`, `target_ref` 같은
임시 연결값은 사용하지 않으며 DB의 영속 ID는 DB가 적재 시 배정한다.

### subjects

- `subject_type`: `CONTENT | RELATED_ASSET`
- `title`: 계약서에 기재된 원문 제목
- `scope_type`: `SERIES | SEASON | EPISODE | EDIT | MANIFESTATION | OST_MASTER | UNSPECIFIED`
- `relationship_type`: `OST_OF | REMAKE_OF | FORMAT_OF | SEQUEL_OF` 또는 null

### legal_rights

유효하게 정규화된 법적 권리 코드 배열이다. Rich Extraction의 `field_status`, `raw_expression`은 보내지 않는다.

### exploitation_modes

유효하게 정규화된 이용형태 코드 배열이다. Legal right와 별도 필드로 유지한다.

### territory_scopes

```json
{
  "term": "ASIA",
  "members": ["JP"]
}
```

- `term`: 계약에 사용된 canonical 국가·지역 용어
- `members`: 정의와 제외조건을 모두 적용한 최종 유효 국가목록
- `excluded_values`, `CARVE_OUT`, generic modifier `values`는 DB payload에 보내지 않는다.
- 예: 계약 정의가 `ASIA=KR,JP`이고 KR 제외이면 `members=[JP]`만 전달한다.
- 근거 없이 전개할 수 없는 ASIA/APAC는 유효값으로 투영하지 않는다.

### license_period

- `start`, `end`: 양 끝 포함 `YYYY-MM-DD`
- 하나의 Grant에는 기간 한 개만 둔다.
- 비연속 기간은 Grant를 분리한다.

### exclusivity

`EXCLUSIVE | NON_EXCLUSIVE | null`

### authority

- `may_sublicense`: boolean/null
- `allowed_recipient_types`: array
- `target_recipient_type`: enum/null
- 유효하게 확정된 authority 값만 전달한다.

## Modifier Projection

DB payload에는 `scope_modifiers`를 그대로 보내지 않는다.

- `DEFINITION`, `CARVE_OUT`: 적용 후 `territory_scopes[].members` 같은 최종값으로 전달
- period modifier: 적용 후 `license_period`로 전달
- authority modifier: 적용 후 `authority`로 전달
- 구조화된 최종값으로 환원할 수 없는 holdback, consent, preferential negotiation 등은 1차 DB payload에서 제외하고 Rich Extraction/판정 입력에 유지

이 선택은 DB payload를 간결하게 하지만, DB가 modifier 원문만으로 직접 판정하는 범위는 줄어든다. modifier 기반 판정이 필요할 때는 별도 판정 Interface를 사용한다.

## 단일 Payment

```json
"payment": {
  "amount": "300000.00",
  "currency": "USD"
}
```

규칙:

1. 계약서가 총 계약금액을 명시하면 그 값을 사용한다.
2. 총액이 없고 구성금액들이 같은 통화이며 중복되지 않으면 합산한다.
3. 서로 다른 통화는 환율 없이 합산하지 않는다.
4. 대체금액, 선택적 금액 또는 중복 여부가 불명확하면 `payment=null`로 두고 Rich Extraction에 원래 금액들을 유지한다.
5. 지급일, 비율, 환율, 세금, 수익배분은 보내지 않는다.

## Compact Evidence

DB에 전달하는 모든 canonical 값의 근거를 `contract` 객체 맨 아래의 단일 `evidence` JSONB
필드에 모은다. canonical 값 객체 안에는 Evidence를 넣지 않는다.

```json
"evidence": {
  "title": [],
  "agreement_type": [],
  "agreement_date": [],
  "parties": [
    {
      "role": [],
      "name": []
    }
  ],
  "rights_grants": [
    {
      "subjects": [
        {
          "subject_type": [],
          "title": [],
          "scope_type": [],
          "relationship_type": []
        }
      ],
      "legal_rights": [],
      "exploitation_modes": [],
      "territory_scopes": [
        {
          "term": [],
          "members": []
        }
      ],
      "license_period": {
        "start": [],
        "end": []
      },
      "exclusivity": [],
      "authority": {
        "may_sublicense": [],
        "allowed_recipient_types": [],
        "target_recipient_type": []
      }
    }
  ],
  "payment": {
    "amount": [],
    "currency": []
  }
}
```

최상위 `evidence`는 DB의 Evidence 컬럼 한 개에 저장한다.

- `contract.evidence.title/agreement_type/agreement_date/parties`: 계약 기본정보 근거
- `contract.evidence.rights_grants[]`: Grant별 근거
- `contract.evidence.payment`: 계약당 단일 종합 Payment 근거

- `evidence.parties[]`는 `contract.parties[]`와 같은 순서다.
- `evidence.rights_grants[]`는 `contract.rights_grants[]`와 같은 순서다.
- 각 Grant Evidence의 `subjects[]`, `territory_scopes[]`도 해당 Grant 값 배열과 같은 순서다.
- 배열 순서를 변경할 때는 canonical 값과 Evidence 배열을 함께 변경한다.

각 배열 원소의 구조는 동일하다.

```json
{
  "page": 7,
  "clause": "별지 1",
  "quote": "아시아란 대한민국 및 일본을 의미한다."
}
```

- `page`: 원문 PDF 페이지 번호
- `clause`: 조항 번호·제목 또는 별지명. 조항을 식별할 수 없으면 null
- `quote`: 해당 필드를 추출한 계약서 원문. 요약하거나 정규화하지 않는다.
- 하나의 필드가 본문, 정의 조항, 별지, 제외 조항 등 여러 문언으로 결정되면 배열에 모두 담는다.
- 실제 DB 전달값이 null이거나 없는 필드의 Evidence 키는 빈 배열로 보내지 않고 생략한다.
- `confidence`는 DB 전달값에서 제외한다. 모델 운영상 필요한 경우 Rich Extraction 내부 metadata로만 유지한다.
- `evidence_ref`, `labels`, `targets`, `target_type`, `target_ref`, `grant_ref`, `payment_ref`는 사용하지 않는다.
- canonical offset은 내부 exact-match 검증에 유지하고 compact Evidence에서는 제외한다.

Payment는 계약당 하나의 종합값이므로 Grant Evidence에 복제하지 않는다.
`contract.evidence.payment`에 합산 근거 문언을 모두 담는다.

```json
{
  "amount": [
    {
      "page": 5,
      "clause": "제8조 이용대가",
      "quote": "영상 이용대가는 미화 250,000달러로 한다."
    },
    {
      "page": 5,
      "clause": "제8조 이용대가",
      "quote": "OST 이용대가는 미화 50,000달러로 한다."
    }
  ],
  "currency": [
    {
      "page": 5,
      "clause": "제8조 이용대가",
      "quote": "영상 및 OST 이용대가의 지급통화는 미화(USD)로 한다."
    }
  ]
}
```

두 원문 금액이 같은 USD이고 중복되지 않아 합산 가능한 경우, DB 전달값은 `300000.00 USD` 하나이며 두 문언을 모두 Evidence로 남긴다.

## DB payload에서 제외

- `field_status`
- `raw_expression`
- canonical offset
- `scope_modifiers`
- `excluded_values`
- DB/content/dataset ID
- normalized title
- 당사자 주소·등록번호·대표자
- Scenario/Finding/reason code
- template 및 생성 metadata
- AI 실행 metadata

## Canonical offset의 위치

Canonical offset은 PDF에서 얻은 문언을 하나의 기준 텍스트로 만든 뒤, Evidence가 그 텍스트의 몇 번째 문자부터 몇 번째 문자까지인지 나타내는 위치값이다.

```text
canonical_text[1250:1294] == evidence.text
```

- `start_char`: 시작 문자 위치, 포함
- `end_char`: 끝 문자 다음 위치, 미포함
- 같은 canonical text를 사용하면 프로그램이 Evidence exact match를 자동 검증할 수 있다.
- PDF page는 사람이 찾기 쉽지만 재렌더링에 따라 바뀔 수 있다.
- canonical offset은 내부 Rich Extraction/GT 검증에 유지하고, 간결한 DB payload에는 보내지 않는다.

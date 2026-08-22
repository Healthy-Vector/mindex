# 계약서 추출 전달 Interface 범위 제안

status: DRAFT  
version: 0.1  
date: 2026-08-19  
owner: K-RIGHTS synthetic-data team

## 1. 목적과 책임 경계

이 문서는 **계약서 parsing 후 우리 팀이 제공할 수 있는 추출 결과의 논리 schema 범위**를 정한다. 특정 DB 테이블, PK/FK, 정규화 방식 또는 현재 ERD에 종속되지 않는다.

> 이 문서는 OCR/추출 및 내부 검증을 위한 Rich Extraction 범위다. 실제 DB에는
> `2026-08-19-db-contract-projection-v0.1.md`에 정의한 유효값 projection만 전달한다.

책임은 다음과 같이 나눈다.

| 주체 | 책임 |
|---|---|
| K-RIGHTS/추출팀 | 추출 필드, 자료형, 다중성, canonical vocabulary, 미확정 표현 방식, Evidence 연결 규칙 제공 |
| DB/서비스팀 | DB ID 발급, 테이블 정규화, 저장·조회·인덱스·이력·tenant 설계, 추출값의 DB 매핑 |
| 판정팀 | 추출 결과를 이용한 충돌 판정 입력/출력과 reason schema 정의 |

따라서 다음 항목은 이 interface의 요구사항이 아니다.

- DB 테이블명과 컬럼명
- DB PK/FK 및 surrogate ID 형태
- 한 Grant를 몇 개 테이블 또는 판정 atom으로 저장할지
- PostgreSQL range, EXCLUDE, trigger 구현 방식
- 시나리오 정답을 서비스 DB에 보관할지 여부

## 2. 1차 전달 범위

계약서 한 건의 추출 출력은 다음 여섯 묶음으로 제한한다.

1. 문서 언어
2. 계약 기본정보
3. 계약 당사자
4. RightsGrant 목록
5. 계약서에 명시된 금액·통화 목록
6. 각 추출값의 Evidence span

Scenario 판정 정답과 DB 저장 설계는 포함하지 않는다.

## 3. 최상위 논리 구조

```text
ContractExtraction
├─ schema_version
├─ request_context                 # 시스템 간 연결용, 추출 의미에는 포함하지 않음
├─ document
│  └─ language
└─ contract
   ├─ contract_title
   ├─ agreement_type
   ├─ agreement_date
   ├─ parties[]
   ├─ rights_grants[]
   ├─ payments[]
   └─ evidence[]
```

`request_context`에는 호출자가 전달한 opaque document reference를 그대로 되돌려줄 수 있다. 이는 `dataset_contract_id`가 아니며 추출 모델이 생성하거나 해석하지 않는다.

### 전체 Multiplicity 요약

| 경로 | 다중성 | Multiple 여부 | 해석 |
|---|---:|---|---|
| `document.language` | 1 | 아니오 | 문서 주언어 한 개 |
| `contract.contract_title` | 1 | 아니오 | 계약 표제 한 개 |
| `contract.agreement_type` | 1 | 아니오 | 계약의 법적 성격 한 개 |
| `contract.agreement_date` | 1 | 아니오 | 정규화된 체결일 한 개 |
| `contract.parties` | 0..N | 예 | 공동 권리자·공동 이용자 등 복수 당사자 가능 |
| `contract.rights_grants` | 0..N | 예 | 한 계약에 서로 다른 권리 묶음 여러 건 가능 |
| `rights_grants[].content.subjects` | 0..N | 예 | 한 Grant가 여러 콘텐츠를 함께 대상으로 할 수 있음 |
| `rights_grants[].legal_right.values` | 0..N | 예 | 한 Grant가 복제권·전송권 등을 함께 부여할 수 있음 |
| `rights_grants[].exploitation_mode.values` | 0..N | 예 | 한 Grant가 SVOD·AVOD 등을 함께 허용할 수 있음 |
| `rights_grants[].territory.values` | 0..N | 예 | 여러 국가·지역을 함께 포함할 수 있음 |
| `rights_grants[].territory.excluded_values` | 0..N | 예 | 여러 국가·지역을 제외할 수 있음 |
| `rights_grants[].territory.definitions` | 0..N | 예 | 계약 정의가 여러 지역 용어를 설명할 수 있음 |
| `territory.definitions[].members` | 0..N | 예 | 한 지역 정의의 구성 국가 목록 |
| `rights_grants[].license_period` | 1 | 아니오 | Grant 한 건당 정규화 기간 한 개 |
| `rights_grants[].exclusivity` | 1 | 아니오 | Grant 한 건당 독점성 한 개 |
| `authority_constraints.may_sublicense` | 1 | 아니오 | true/false/null 한 개 |
| `authority_constraints.allowed_recipient_types` | 0..N | 예 | 복수 수령인 유형 허용 가능 |
| `authority_constraints.target_recipient_type` | 0..1 | 아니오 | 대상 수령인 유형 한 개 또는 미기재 |
| `rights_grants[].scope_modifiers` | 0..N | 예 | carve-out, holdback 등 여러 제한 가능 |
| `contract.payments` | 0..N | 예 | 계약서에 명시된 금액 표현 여러 건 가능 |
| `contract.evidence` | 0..N | 예 | 계약서 한 건에 Evidence span 여러 건 |
| `evidence[].labels` | 1..N | 예 | 한 문언이 여러 clause function을 수행할 수 있음 |
| `evidence[].targets` | 1..N | 예 | 한 Evidence가 여러 추출 필드를 입증할 수 있음 |

Multiplicity 해석 규칙:

- `values` 배열은 **동시에 적용되는 canonical 값의 집합**이다. 불확실한 후보 목록이 아니다.
- 하나로 확정할 수 없으면 후보들을 배열에 넣지 않고 `field_status=UNRESOLVED`, `values=[]`와 원문을 전달한다.
- 배열 순서는 법적 우선순위나 시간 순서를 의미하지 않는다.
- 동일 값은 중복해서 넣지 않는다. 동일한 법적 지급의 반복 기재는 payment를 복제하지 않고 Evidence를 여러 개 연결한다.
- 기간·독점성·대상 자산·authority 또는 중요한 modifier가 달라지면 별도의 RightsGrant로 나눈다.
- 같은 Grant에 비연속 이용기간이 둘 이상 있으면 기간 배열로 만들지 않고 기간별 RightsGrant로 분리한다.
- 영상 콘텐츠와 OST/Remake는 같은 문서에 있더라도 별도 RightsGrant로 분리한다.

## 4. 계약 기본정보

| 필드 | 형태 | 다중성 | 설명 |
|---|---|---:|---|
| `document.language` | enum | 1 | `KO | EN | JP` |
| `contract.contract_title` | FieldResult&lt;string&gt; | 1 | 계약서 표제에서 추출한 계약 명칭 |
| `contract.agreement_type` | FieldResult&lt;enum&gt; | 1 | `DIRECT_LICENSE | SUBLICENSE` |
| `contract.agreement_date` | FieldResult&lt;date&gt; | 1 | 체결일. `YYYY-MM-DD` |
| `contract.parties` | Party[] | 0..N | 계약서에 명시된 당사자 |

### FieldResult

단일 추출값은 공통적으로 다음 모양을 사용한다.

```text
{
  "field_status": "PRESENT_EXPLICIT",
  "value": "2027-03-01",
  "raw_expression": "2027년 3월 1일"
}
```

- 값이 없거나 확정되지 않으면 `value`는 null이다.
- `raw_expression`은 관련 문언이 있는 경우 보존한다.
- 아래에서 사용하는 `SingleValueField`도 같은 구조다.

### Party

| 필드 | 형태 | 필수 | 설명 |
|---|---|---:|---|
| `role` | enum/null | 예 | `GRANTOR | GRANTEE`; 역할을 확정할 수 없으면 null |
| `name` | string | 예 | 계약서 원문에 기재된 법인·개인 명칭 |
| `field_status` | enum | 예 | 역할과 명칭을 포함한 당사자 추출 상태 |
| `raw_expression` | string/null | 예 | 계약서의 당사자 표현 |

주소, 등록번호, 대표자, 서명자, 연락처와 normalized title은 1차 범위에서 제외한다.

## 5. RightsGrant

`rights_grants`는 계약서가 부여하거나 제한하는 **의미상 권리 묶음**의 목록이다. DB가 이를 여러 저장 행으로 분할할지는 DB 팀이 결정한다.

| 필드 | 형태 | 다중성 | 설명 |
|---|---|---:|---|
| `grant_ref` | string | 1 | 한 payload 안에서 Evidence를 연결하기 위한 임시 참조값 |
| `content` | ContentField | 1 | 권리 대상 콘텐츠·관련 자산 |
| `legal_right` | MultiValueField | 1 | 법적 권리. 이용형태와 별도 유지 |
| `exploitation_mode` | MultiValueField | 1 | 실제 이용·서비스 형태 |
| `territory` | TerritoryField | 1 | 국가·지역 표현 및 명시적 정의/제외 |
| `license_period` | PeriodField | 1 | 이용허락 기간. Contract Term과 구별 |
| `exclusivity` | SingleValueField | 1 | `EXCLUSIVE | NON_EXCLUSIVE` 또는 미확정 |
| `authority_constraints` | AuthorityField | 1 | 재허락 가능 여부, 수령인 범위, 동의 상태 |
| `scope_modifiers` | Modifier[] | 0..N | Grant를 제한·확장·순서화하는 조항 |

### ContentField

DB content ID는 계약서 parsing만으로 생성할 수 없으므로 1차 추출값에 넣지 않는다.

```text
content
├─ field_status
├─ subjects[]
│  ├─ subject_type
│  ├─ title
│  ├─ scope_type
│  ├─ relationship_type
│  └─ relationship_type
└─ raw_expression
```

- `subject_type`: `CONTENT | RELATED_ASSET`
- `scope_type`: `SERIES | SEASON | EPISODE | EDIT | MANIFESTATION | OST_MASTER | UNSPECIFIED`
- `relationship_type`: `OST_OF | REMAKE_OF | FORMAT_OF | SEQUEL_OF` 또는 null
- `title`: 계약서에 기재된 제목
- DB의 기존 콘텐츠와 매칭하여 DB ID를 부여하는 일은 적재 단계의 책임이다.
- Remake, OST, 영상 콘텐츠를 자동으로 같은 subject로 합치지 않는다.

### MultiValueField

```text
{
  "field_status": "PRESENT_EXPLICIT",
  "values": ["INTERACTIVE_TRANSMISSION"],
  "raw_expression": "전송권"
}
```

하나의 조항에 값이 여러 개 명시될 수 있으므로 `values`는 배열이다.

### TerritoryField

```text
{
  "field_status": "PRESENT_EXPLICIT",
  "values": ["ASIA"],
  "excluded_values": ["KR"],
  "definitions": [
    {
      "term": "ASIA",
      "members": ["JP", "SG"]
    }
  ],
  "raw_expression": "아시아(일본 및 싱가포르를 의미한다), 단 대한민국 제외"
}
```

- canonical territory vocabulary: `KR | JP | US | SG | TW | ASIA | APAC | WORLDWIDE`
- `ASIA`, `APAC`는 계약서에 정의가 없으면 임의 국가목록으로 확장하지 않는다.
- 정의를 확정할 수 없으면 표현을 보존하고 `field_status=UNRESOLVED`로 전달한다.

### PeriodField

```text
{
  "field_status": "PRESENT_EXPLICIT",
  "start": "2027-07-01",
  "end": "2029-06-30",
  "raw_expression": "2027년 7월 1일부터 2029년 6월 30일까지"
}
```

- `start`와 `end`는 계약 문언상 양 끝을 포함하는 날짜다.
- 상대기간 표현을 확정적으로 계산할 수 없으면 날짜를 임의 생성하지 않는다.
- Contract Term을 License Period로 자동 대체하지 않는다.

### AuthorityField

```text
{
  "field_status": "PRESENT_EXPLICIT",
  "may_sublicense": true,
  "allowed_recipient_types": ["AFFILIATE"],
  "target_recipient_type": null,
  "raw_expression": "계열회사에 한하여 재허락할 수 있다"
}
```

- recipient vocabulary: `AFFILIATE | NON_AFFILIATE | OTT_PLATFORM | PLATFORM`
- 동의 조건과 동의 확인 상태는 `CONSENT_REQUIRED`/`CONSENT_STATUS` modifier로 표현한다.
- consent 문서가 없다는 사실만으로 미승인이라고 추출하지 않는다.

### Modifier

```text
{
  "modifier_type": "CARVE_OUT",
  "dimension": "TERRITORY",
  "field_status": "PRESENT_EXPLICIT",
  "values": ["KR"],
  "raw_expression": "대한민국은 제외한다"
}
```

1차 modifier vocabulary:

- `RESERVED_RIGHTS`
- `CARVE_OUT`
- `HOLDBACK`
- `DEFINITION`
- `CONSENT_REQUIRED`
- `CONSENT_STATUS`
- `IDENTITY_EVIDENCE`
- `PREFERENTIAL_NEGOTIATION`
- `THIRD_PARTY_CLEARANCE`

## 6. Canonical vocabulary

### Field status

| 값 | 의미 |
|---|---|
| `PRESENT_EXPLICIT` | 계약서 또는 편입된 별첨에 값이 직접 명시됨 |
| `PRESENT_DERIVED` | 검토된 규칙으로 명시 문언에서 결정적으로 계산됨 |
| `UNRESOLVED` | 관련 문언은 있으나 canonical 값 하나로 확정할 수 없음 |
| `ABSENT` | 평가 대상 문서에 해당 필드의 근거가 없음 |
| `EXTERNAL_REFERENCE` | 평가 대상에 포함되지 않은 외부 문서로 값이 위임됨 |

`ABSENT`는 부정 사실이 아니다. 예를 들어 consent 근거가 없다는 이유만으로 `consent=false`라고 전달하지 않는다.

### Legal right

- `REPRODUCTION`
- `DISTRIBUTION`
- `PUBLIC_TRANSMISSION`
- `BROADCASTING`
- `INTERACTIVE_TRANSMISSION`
- `DIGITAL_AUDIO_TRANSMISSION`
- `PERFORMANCE`
- `EXHIBITION`
- `RENTAL`
- `DERIVATIVE_WORK_CREATION`
- `ORIGINAL_AUTHOR_DERIVATIVE_EXPLOITATION`

### Exploitation mode

- `SVOD`
- `AVOD`
- `TVOD`
- `TV_LINEAR`
- `THEATRICAL`
- `MUSIC_STREAMING`
- `ON_DEMAND_AUDIOVISUAL`
- `DIGITAL_DISTRIBUTION_UNSPECIFIED`

Legal right와 exploitation mode는 서로 추론하거나 합치지 않는다.

## 7. Payment

계약서에 명시된 각 금액 표현을 목록으로 전달한다.

```text
payments[]
├─ payment_ref
├─ amount
└─ currency
```

- `amount`: 소수점 문자열. 예: `"282000000.00"`
- `currency`: ISO 4217 알파벳 코드. 예: `KRW | USD | JPY`
- 하나의 계약에 금액이 여러 개면 여러 payment item을 생성한다.
- subtype, 지급 milestone, 지급일, 비율, 환율, 세금, 은행비용, revenue share는 추출하지 않는다.
- 계약 생성 metadata에는 위 상세정보가 존재하더라도 전달 projection에는 `amount`, `currency`만 사용한다.

`payment_ref`는 Evidence 연결용 임시 참조값이며 DB ID가 아니다.

## 8. Evidence

모든 추출값은 가능한 한 계약서 원문 span에 연결한다.

| 필드 | 형태 | 설명 |
|---|---|---|
| `evidence_ref` | string | payload 내부 임시 참조값 |
| `labels` | enum[] | `CONTENT`, `LEGAL_RIGHT`, `PAYMENT` 등 clause label. 한 span에 복수 가능 |
| `targets` | array | 이 Evidence가 뒷받침하는 계약 필드·Grant·Payment 참조 |
| `text` | string | 계약서의 exact text |
| `section` | string/null | 조항 번호 또는 제목 |
| `page_start`, `page_end` | integer/null | PDF 렌더링 이후 페이지 |
| `start_char`, `end_char` | integer/null | canonical text 기준 offset |

offset이 제공될 경우 기준은 다음과 같다.

- canonical source: UTF-8 Markdown body
- line ending: LF
- unit: Unicode code point
- start: inclusive
- end: exclusive
- `evidence.text == canonical_body[start_char:end_char]`

페이지와 canonical offset 중 어느 항목을 DB가 저장할지는 DB 팀이 결정할 수 있지만, 추출팀의 결과에는 둘 다 제공할 수 있는 구조를 유지한다.

## 9. 전체 payload 예시

복수 Grant, 복수 이용형태, 지역 정의·제외, 별도 OST Grant, 복수 payment와 다대다 Evidence를 포함한 전체 예시는 다음 파일에 둔다.

- `docs/proposals/examples/contract-extraction-v0.1.example.json`

이 예시는 논리 interface를 설명하기 위한 것으로 DB ID나 dataset ID를 포함하지 않는다.

## 10. ID 원칙

1차 전달 payload에는 다음 dataset authoring ID를 포함하지 않는다.

- `dataset_contract_id` 및 `CTR-*`
- `grant_id` 및 `GRT-*`
- `evidence_id` 및 `EVS-*`
- `scenario_id`
- `finding_id`
- `content_id` 및 `C*`

한 payload 안의 연결만을 위해 다음 임시 참조를 허용한다.

- `grant_ref`
- `payment_ref`
- `evidence_ref`

이 값은 payload 밖에서 영속 식별자로 사용하지 않으며 DB는 자체 ID를 발급한다. 데이터셋 평가용 ID와 DB ID의 관계는 서비스 DB 밖의 로컬 sidecar에서만 관리한다.

## 11. 1차에서 제외하는 필드

- Scenario expected result, Finding, reason code, affected scope
- upstream/existing/target 같은 dataset scenario role
- `value_origin`, authoring `status`, `evidence_requirement_ids`
- template family, variant, clause order, 목표 페이지 수
- 계약 생성용 payment/FX/tax 상세 metadata
- 모델명, prompt, token, confidence 등 실행 metadata
- DB ID, DB 저장 상태, tenant, 승인·검토 workflow

AI 실행 metadata가 필요하면 계약 추출 내용과 섞지 않고 별도 `extraction_run` interface로 정의한다.

## 12. DB 팀에 전달할 요구사항

DB 팀에는 특정 테이블 추가를 먼저 요구하지 않고 다음 수용 조건만 전달한다.

- 위 논리 필드가 정보 손실 없이 저장되거나 재구성될 수 있어야 한다.
- 배열 필드를 DB에서 여러 행으로 분할하더라도 하나의 semantic Grant 관계를 복원할 수 있어야 한다.
- canonical value와 raw expression을 함께 보존할 수 있어야 한다.
- 복수 Evidence를 하나 이상의 추출 필드와 연결할 수 있어야 한다.
- DB가 발급한 ID를 응답하여 로컬 평가 sidecar를 만들 수 있어야 한다.
- `JP` 등 interface vocabulary와 DB 내부 vocabulary가 다르면 mapping 규칙을 문서화해야 한다.
- inclusive license end를 DB range로 바꿀 경우 날짜가 하루 어긋나지 않도록 변환 규칙을 문서화해야 한다.

## 13. 확정 순서

1. 이 문서에서 필드 범위와 canonical vocabulary를 팀 검토한다.
2. 합의한 범위로 정식 JSON Schema를 작성한다.
3. KO/EN/JP Pilot 계약서를 각각 포함한 valid sample과 invalid sample을 만든다.
4. JSON Schema validation을 실행한다.
5. 승인된 interface와 sample을 DB 설계자에게 전달한다.
6. DB 설계자가 mapping 표와 필요한 ERD 수정안을 회신한다.
7. 양 팀이 mapping을 승인한 뒤 DB 전달 schema version을 고정한다.
8. 판정 입력/출력 schema는 별도 문서로 후속 확정한다.

## 14. DB projection 결정사항

- 주소·등록번호·대표자와 normalized title은 제외한다.
- canonical offset은 Rich Extraction/GT 검증에 유지하고 DB projection에서는 제외한다.
- DB에는 generic modifier를 보내지 않고, 적용 후 유효값과 필요한 `{term, members}`만 보낸다.
- request context는 payload body 밖 transport envelope에 둔다.
- DB payment는 단일 `{amount, currency}` 또는 null만 허용한다.
- 상세 규칙은 `2026-08-19-db-contract-projection-v0.1.md`를 따른다.

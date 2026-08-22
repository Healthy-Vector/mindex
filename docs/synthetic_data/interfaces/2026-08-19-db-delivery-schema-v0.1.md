# DB 전달 Schema 1차 제안

status: DRAFT  
version: 0.2  
date: 2026-08-19
updated: 2026-08-22

## 현재 결정

DB 전달 body는 상세 OCR/추출 결과 전체가 아니라 검증·정규화된 canonical 값만 포함한다.

- 상세 OCR/내부 검증: `2026-08-19-contract-extraction-interface-scope-v0.1.md`
- 실제 DB 전달 projection: `2026-08-19-db-contract-projection-v0.1.md`
- 전체 DB 전달 샘플: `examples/db-contract-projection-v0.1.example.json`

```text
Rich Extraction
  field_status + raw expression + Evidence + modifiers + 복수 payment
        ↓ validate / normalize / apply modifier / aggregate payment
DB Projection
  유효한 canonical 값 + 단일 payment + compact Evidence
```

## DB payload 범위

1. 문서 언어
2. 계약명·계약 유형·체결일
3. 계약 당사자의 role·name
4. RightsGrant의 유효값
5. 계약당 단일 종합 payment `{amount, currency}` 또는 null
6. DB 전달값과 연결되는 compact Evidence

## 공통 code 유형

| 구분 | 허용 code | 기준 |
|---|---|---|
| 문서 언어 | `JA | KO | EN` | ISO 639-1. 일본어는 `JA` |
| 국가 | `KR | US | JP` | ISO 3166-1 alpha-2 |
| 통화 | `KRW | USD | JPY` | ISO 4217 |

언어의 `JA`와 국가의 `JP`는 서로 다른 code다. 내부 합성데이터의 기존 언어 식별자 `JP`는
유지하고 DB 전송 경계에서 `JA`로 매핑한다. `territory_scopes[].term`의 `ASIA` 같은 값은
국가 코드가 아니라 계약상 지역 용어이며, `members[]`에는 허용된 국가 코드만 전달한다.
현재 allowlist 밖의 국가를 임의 제거해 전달하지 않는다.

## DB payload 제외

- `field_status`, `raw_expression`, canonical offset
- generic `scope_modifiers`, `excluded_values`
- 주소·등록번호·대표자, normalized title
- dataset/DB/content ID
- Scenario/Finding/reason code
- template·생성 metadata·AI 실행 metadata

## Transport 경계

`request_id`, `source_document_ref`는 payload 내부가 아니라 API transport envelope에 둔다. 추출 body는 `payload` 아래에 둔다.

## 핵심 Projection 규칙

- modifier는 DB에 그대로 보내지 않고 적용 후 유효값만 보낸다.
- 지역은 `{term, members}`로 전달하며 `members`는 정의와 제외조건을 모두 반영한 최종 범위다.
- 미확정값은 임의 보정하지 않는다.
- Payment는 명시된 총액을 우선하고, 없으면 동일 통화의 중복되지 않는 구성금액만 합산한다.
- 서로 다른 통화는 환율 없이 합산하지 않으며 이 경우 payment는 null이다.

## Evidence 배치 규칙

- 계약·Grant·Payment의 모든 근거는 `contract` 맨 아래의 단일 `evidence` JSONB object에 둔다.
- canonical 값 객체인 `rights_grants[]`와 `payment` 안에는 `evidence`를 넣지 않는다.
- `contract.evidence` 아래에 계약 기본 필드의 근거와 `rights_grants[]`, `payment` 근거를 함께 둔다.
- `contract.evidence.rights_grants[]`는 `contract.rights_grants[]`와 배열 순서로 1:1 대응한다.
- Evidence 키는 실제 추출 필드명과 동일하게 쓴다. 객체형 값은 `license_period.start/end`, `authority.may_sublicense`처럼 하위 필드까지 나눈다.
- 각 키의 값은 `{page, clause, quote}` 배열이다. 본문·정의·별지·제외 조항이 함께 값을 결정하면 근거를 모두 배열에 담는다.
- 계약당 단일 종합 `payment`의 근거는 Grant에 복제하지 않고 `contract.evidence.payment.amount/currency`에 나누어 둔다.
- `evidence_ref`, `target_ref`, `grant_ref`, `payment_ref`, `confidence`는 DB payload에 포함하지 않는다.

세부 필드와 전체 JSON은 `2026-08-19-db-contract-projection-v0.1.md` 및 sample 파일을 기준으로 한다.

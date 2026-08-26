# 계약서 상세페이지 압축 포맷 제안

status: DRAFT  
version: 0.1  
date: 2026-08-20

## 1. 목적

DB projection의 canonical 값을 계약서 상세 화면에서 빠르게 읽을 수 있도록 압축한다.
이 포맷은 저장 스키마나 추출 스키마를 대체하지 않는 **표시 전용 View Model**이다.

핵심 원칙은 다음과 같다.

- 계약 기본정보는 화면 상단의 한 개 요약 영역으로 묶는다.
- 권리정보는 계약 전체로 합치지 않고 `RightsGrant`별 카드로 반복한다.
- `legal_rights`, `exploitation_modes`, `exclusivity`를 각각 별도 항목으로 표시한다.
- 재허락 권한은 계약 전체가 아니라 해당 `RightsGrant` 안에 표시한다.
- 영상 Content, Remake, OST 등 related asset을 서로 다른 subject 또는 Grant로 유지한다.
- canonical code와 사용자용 한국어 label을 함께 유지한다.
- 값이 없거나 미확정인 경우 `불가`로 오인시키지 않고 `정보 없음` 또는 `확인 필요`로 표시한다.
- Evidence는 첫 화면에 원문 전체를 노출하지 않고 각 값의 `근거 보기` 동작으로 연결한다.

## 2. 권장 화면 구조

```text
┌─────────────────────────────────────────────────────────────────┐
│ [직접 이용허락] 겨울의 신호 영상 및 OST 이용허락계약서         │
│ 체결일 2027.03.01                                                │
│ 해솔미디어 주식회사 [허락자]  →  웨이브플랫폼 주식회사 [이용자] │
│ 총 계약금액  USD 300,000                                        │
├─────────────────────────────────────────────────────────────────┤
│ 권리 1  [콘텐츠] 겨울의 신호 · 시리즈                           │
│ [독점]  일본·싱가포르  |  2027.07.01–2029.06.30                 │
│ 법적 권리  전송권                                                │
│ 이용 형태  SVOD · AVOD                                          │
│ 재허락     가능 · 관계회사만                                    │
│ 대상 유형  관계회사                                              │
│                                             [필드별 근거 보기]   │
├─────────────────────────────────────────────────────────────────┤
│ 권리 2  [관련 자산·OST] 겨울의 신호 OST · OST 마스터            │
│ 관계     겨울의 신호의 OST                                      │
│ [비독점] 일본·싱가포르  |  2027.07.01–2028.06.30                │
│ 법적 권리  전송권                                                │
│ 이용 형태  음악 스트리밍                                        │
│ 재허락     정보 없음                                             │
│                                             [필드별 근거 보기]   │
└─────────────────────────────────────────────────────────────────┘
```

모바일에서는 상단 당사자 흐름을 세로로 바꾸고, 각 Grant의 `법적 권리`, `이용 형태`,
`지역`, `기간`, `재허락`을 1열로 쌓는다. Grant 간 경계는 유지한다.

## 3. 표시용 View Model

필드명은 화면 역할을 명확히 하기 위한 것이며 확정 DB 컬럼명이 아니다.

```json
{
  "format_version": "k-rights.contract-detail-summary.v0.1",
  "overview": {
    "title": "겨울의 신호 영상 및 OST 이용허락계약서",
    "agreement_type": {
      "code": "DIRECT_LICENSE",
      "label": "직접 이용허락"
    },
    "agreement_date": {
      "value": "2027-03-01",
      "display": "2027.03.01"
    },
    "party_flow": [
      {
        "role": "GRANTOR",
        "role_label": "허락자",
        "name": "해솔미디어 주식회사"
      },
      {
        "role": "GRANTEE",
        "role_label": "이용자",
        "name": "웨이브플랫폼 주식회사"
      }
    ],
    "payment": {
      "amount": "300000.00",
      "currency": "USD",
      "display": "USD 300,000"
    }
  },
  "grant_cards": [
    {
      "grant_order": 1,
      "subjects": [
        {
          "subject_type": "CONTENT",
          "subject_type_label": "콘텐츠",
          "title": "겨울의 신호",
          "scope_type": "SERIES",
          "scope_type_label": "시리즈",
          "relationship_type": null,
          "relationship_type_label": null
        }
      ],
      "legal_rights": [
        {
          "code": "INTERACTIVE_TRANSMISSION",
          "label": "전송권"
        }
      ],
      "exploitation_modes": [
        {
          "code": "SVOD",
          "label": "구독형 VOD"
        },
        {
          "code": "AVOD",
          "label": "광고형 VOD"
        }
      ],
      "exclusivity": {
        "code": "EXCLUSIVE",
        "label": "독점"
      },
      "territory_scopes": [
        {
          "term": "ASIA",
          "term_label": "아시아",
          "members": ["JP", "SG"],
          "member_labels": ["일본", "싱가포르"],
          "display": "아시아 (일본·싱가포르)"
        }
      ],
      "license_period": {
        "start": "2027-07-01",
        "end": "2029-06-30",
        "display": "2027.07.01–2029.06.30"
      },
      "authority": {
        "may_sublicense": true,
        "may_sublicense_label": "가능",
        "allowed_recipient_types": [
          {
            "code": "AFFILIATE",
            "label": "관계회사"
          }
        ],
        "target_recipient_type": {
          "code": "AFFILIATE",
          "label": "관계회사"
        }
      }
    },
    {
      "grant_order": 2,
      "subjects": [
        {
          "subject_type": "RELATED_ASSET",
          "subject_type_label": "관련 자산",
          "title": "겨울의 신호 OST",
          "scope_type": "OST_MASTER",
          "scope_type_label": "OST 마스터",
          "relationship_type": "OST_OF",
          "relationship_type_label": "본편의 OST"
        }
      ],
      "legal_rights": [
        {
          "code": "INTERACTIVE_TRANSMISSION",
          "label": "전송권"
        }
      ],
      "exploitation_modes": [
        {
          "code": "MUSIC_STREAMING",
          "label": "음악 스트리밍"
        }
      ],
      "exclusivity": {
        "code": "NON_EXCLUSIVE",
        "label": "비독점"
      },
      "territory_scopes": [
        {
          "term": "JP",
          "term_label": "일본",
          "members": ["JP"],
          "member_labels": ["일본"],
          "display": "일본"
        },
        {
          "term": "SG",
          "term_label": "싱가포르",
          "members": ["SG"],
          "member_labels": ["싱가포르"],
          "display": "싱가포르"
        }
      ],
      "license_period": {
        "start": "2027-07-01",
        "end": "2028-06-30",
        "display": "2027.07.01–2028.06.30"
      },
      "authority": null
    }
  ]
}
```

`display`, `label`, `*_label`은 locale에 따라 다시 만들 수 있는 파생값이다. 검색·비교·저장에는
반드시 canonical `code`, 날짜, 금액, 통화를 사용한다.

## 4. 원본 필드와 화면 위치

| 원본 canonical 필드 | 화면 위치 | 권장 표시 |
|---|---|---|
| `contract.title` | 상단 제목 | 원문 계약 명칭 |
| `contract.agreement_type` | 제목 앞 badge | 직접 이용허락 / 재허락 |
| `contract.agreement_date` | 상단 보조정보 | `YYYY.MM.DD` |
| `contract.parties[].role` | 당사자 flow badge | 허락자 / 이용자 |
| `contract.parties[].name` | 당사자 flow | 원문 당사자명 |
| `contract.payment.amount`, `currency` | 상단 금액 | `USD 300,000`처럼 통화+금액 |
| `rights_grants[].subjects[]` | Grant 카드 제목 | `[대상유형] 제목 · 범위` |
| `subjects[].relationship_type` | Grant 카드 제목 아래 | `본편의 OST`, `원작의 Remake` 등 |
| `rights_grants[].exclusivity` | Grant 핵심 badge | 독점 / 비독점 |
| `rights_grants[].territory_scopes[]` | Grant 핵심 요약 | 계약 용어와 유효 member를 함께 표시 |
| `rights_grants[].license_period` | Grant 핵심 요약 | 시작일–종료일 |
| `rights_grants[].legal_rights[]` | Grant 상세 1행 | 한국어 label chip |
| `rights_grants[].exploitation_modes[]` | Grant 상세 1행 | 서비스 형태 label chip |
| `rights_grants[].authority` | Grant 하단 | 가능 여부, 허용 상대, target 상대 |

## 5. 압축 및 표시 규칙

### 5.1 계약과 Grant의 반복 단위

- 계약명, 유형, 체결일, 당사자, 종합 payment는 계약당 한 번만 표시한다.
- subject, 법적 권리, 이용형태, 독점성, 지역, 이용기간, authority는 Grant마다 표시한다.
- 서로 다른 Grant의 지역·기간이 같아도 한 줄로 합치지 않는다.
- 한 Grant 안의 여러 subject는 `외 N개`로 접을 수 있지만 펼치면 전부 보여준다.

### 5.2 지역

- `term=ASIA`, `members=[JP, SG]`이면 `아시아 (일본·싱가포르)`로 표시한다.
- 단일 국가의 `term`과 `members`가 같으면 `일본 (일본)`처럼 중복 표시하지 않는다.
- `ASIA`/`APAC`의 member가 확정되지 않았으면 `아시아 · 범위 확인 필요`로 표시한다.
- ontology 또는 계약 정의 없이 국가목록을 화면에서 임의 생성하지 않는다.

### 5.3 기간

- `license_period`만 권리 카드에 표시하며 Contract Term으로 대체하지 않는다.
- 양쪽 날짜가 확정된 경우 `YYYY.MM.DD–YYYY.MM.DD`로 표시한다.
- 날짜가 null 또는 미확정이면 `이용기간 확인 필요`로 표시한다.

### 5.4 재허락

| canonical 값 | 화면 문구 |
|---|---|
| `may_sublicense=true` | `재허락 가능` |
| `may_sublicense=false` | `재허락 불가` |
| `authority=null` 또는 `may_sublicense=null` | `재허락 정보 없음` 또는 `확인 필요` |

- `allowed_recipient_types`는 **허용된 상대방 유형**이다.
- `target_recipient_type`은 **현재 target 계약의 실제 수령자 유형**이다.
- 둘은 의미가 다르므로 하나의 `recipient_types`로 병합하지 않는다.
- target 값은 현재 projection 기준 단일값이므로 `target_recipient_types`가 아니라
  `target_recipient_type`을 사용한다. 향후 실제로 복수 target을 허용할 때만 배열로 변경한다.

### 5.5 Payment

- 종합 payment가 있으면 통화코드와 금액을 함께 표시한다.
- amount만 또는 currency만 단독 표시하지 않는다.
- `payment=null`이면 `계약금액 정보 없음`으로 표시한다.
- 지급일, 세금, 환율, revenue share 등은 현재 상세 요약의 범위 밖이다.

### 5.6 미확정값

Rich Extraction의 상태를 화면까지 전달하는 경우 다음 label을 권장한다.

| 상태 | 화면 문구 |
|---|---|
| `PRESENT_EXPLICIT` | 일반 표시 |
| `PRESENT_DERIVED` | `계산된 값` 보조표시 |
| `UNRESOLVED` | `확인 필요` |
| `ABSENT` | `계약서에 정보 없음` |
| `EXTERNAL_REFERENCE` | `외부 문서 확인 필요` |

DB projection만 사용하는 경우 null의 원인을 구별할 수 없으므로 일반적으로 `정보 없음`으로만
표시한다. `ABSENT`를 `불가`, `미승인`, `비독점` 같은 부정 사실로 변환하지 않는다.

## 6. 한국어 기본 label 사전

### 계약·당사자

| code | label |
|---|---|
| `DIRECT_LICENSE` | 직접 이용허락 |
| `SUBLICENSE` | 재허락 |
| `GRANTOR` | 허락자 |
| `GRANTEE` | 이용자 |

`갑`, `을`은 계약서의 표기 alias일 뿐 권리 역할을 항상 보장하지 않으므로 canonical role label로
사용하지 않는다. 원문 alias를 별도로 추출하는 경우 `허락자(갑)`처럼 보조표시할 수 있다.

### 대상·범위·관계

| code | label |
|---|---|
| `CONTENT` | 콘텐츠 |
| `RELATED_ASSET` | 관련 자산 |
| `SERIES` | 시리즈 |
| `SEASON` | 시즌 |
| `EPISODE` | 에피소드 |
| `EDIT` | 편집본 |
| `MANIFESTATION` | 구현본 |
| `OST_MASTER` | OST 마스터 |
| `UNSPECIFIED` | 범위 미특정 |
| `OST_OF` | 본편의 OST |
| `REMAKE_OF` | 원작의 Remake |
| `FORMAT_OF` | 원작의 Format |
| `SEQUEL_OF` | 원작의 Sequel |

### 독점성·수령자

| code | label |
|---|---|
| `EXCLUSIVE` | 독점 |
| `NON_EXCLUSIVE` | 비독점 |
| `AFFILIATE` | 관계회사 |
| `NON_AFFILIATE` | 비관계회사 |
| `OTT_PLATFORM` | OTT 플랫폼 |
| `PLATFORM` | 플랫폼 |

Legal right와 exploitation mode의 전체 한국어 label 사전은 canonical taxonomy와 함께 별도
상수로 관리한다. View Model 안의 label을 판정 입력값으로 재사용하지 않는다.

## 7. 명칭 정리

- `contract.aggreement_date`의 철자를 `contract.agreement_date`로 정리한다.
- 현재 DB projection의 Grant 배열명은 `contract.rights_grants[]`다.
- subject 정보는 `rights_grants[].subjects[]` 아래에 둔다. 한 Grant가 복수 subject를 가질 수
  있으므로 `rights_grant.title` 같은 단일 필드로 평탄화하지 않는다.
- canonical 필드는 `legal_rights`, `exploitation_modes`, `territory_scopes`처럼 복수형을 사용한다.
- `authority.target_recipient_type`은 현재 단수다.

## 8. 범위 밖

이 1차 상세 요약에는 다음을 넣지 않는다.

- Scenario/Finding/reason code 및 충돌 판정 결과
- DB ID, dataset ID, 임시 extraction reference
- template/variant/generation metadata
- 주소·등록번호·대표자·서명자
- payment의 상세 commercial terms
- Evidence 원문 전체와 canonical offset

충돌 판정 결과가 필요한 화면은 이 계약 상세 요약과 별도로 `권리 검토 결과` 영역을 두고,
Finding 단위의 상대 계약·겹친 scope·reason·Evidence를 표시하는 것이 적절하다.

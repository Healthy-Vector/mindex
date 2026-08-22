# K-RIGHTS 서비스 개요

> `mindex` 저장소에서 서비스를 구현하는 개발자를 위한 배경 문서다.
> 프로젝트가 무엇을 해결하는지, 시스템이 어떻게 동작하는지, 왜 합성데이터가 필요한지를 담는다.
>
> 이 문서는 구현 세부를 새로 정의하는 설계서가 아니다. 데이터셋의 현재 상태와 산출물 수치는
> `docs/synthetic_data/DATASET_STATUS.md`, 서비스 전달 규격은 `docs/synthetic_data/interfaces/`를 우선한다.

---

# 1. 프로젝트 한 줄 정의

**K-RIGHTS는 K-콘텐츠 라이선스·저작권 계약서를 AI로 구조화하고, 기존 계약과 신규 계약 사이의 권리 범위 중복·권한 초과·검수 필요사항을 결정론적 규칙과 OpenSQL 기반 데이터 레이어에서 탐지하는 계약 인텔리전스 플랫폼이다.**

단순한 “PDF 검색 서비스”가 아니다.

핵심은 다음 두 단계의 분리다.

```text
AI / LLM
비정형 계약서 → 구조화 Rights Data + Evidence 추출

                ↓

Rule / DB
구조화 Rights Data → 충돌·정상·검수·경고 판정
```

AI가 계약서를 이해하고 구조화하지만, **AI의 자유로운 추론만으로 최종 권리 충돌 여부를 결정하지 않는 것**이 프로젝트의 핵심 설계 원칙이다.


---

# 2. 프로젝트 배경

## 2.1 해결하려는 문제

콘텐츠 라이선스 계약은 단순히 “이 작품을 사용할 수 있다/없다”로 끝나지 않는다.

하나의 콘텐츠도 다음 조건에 따라 여러 사업자에게 서로 다른 권리가 부여될 수 있다.

- 어느 콘텐츠인가
- 전체 Series인지 특정 Season/Episode/Edit인지
- 어떤 법적 권리인가
- 어떤 사업적 이용방식인가
- 어느 국가 또는 지역인가
- 언제부터 언제까지인가
- Exclusive인지 Non-exclusive인지
- Reserved Rights / Carve-out이 존재하는가
- Holdback이나 Exclusive Window가 존재하는가
- Sublicense가 가능한가
- Remake / Format / OST처럼 파생·관련 권리인가

예를 들어 같은 드라마라도 다음 두 계약은 정상적으로 공존할 수 있다.

```text
Contract A
Japan / SVOD / 2027~2029 / Exclusive

Contract B
Korea / SVOD / 2027~2029 / Exclusive

→ Territory가 겹치지 않으므로 NORMAL
```

반면 다음은 중복될 수 있다.

```text
Contract A
Japan / SVOD / 2027~2029 / Exclusive

Contract B
Japan / SVOD / 2028~2030 / Non-exclusive

→ 기존 Exclusive Scope 침해
→ CONFLICT
```

실무에서는 이런 정보가 PDF 본문, Definitions, 표, Schedule, 각주 등에 흩어져 있을 수 있고 한국어·영어·일본어 표현도 다르다.

K-RIGHTS는 이 문제를 **계약 원문 → 구조화 권리 데이터 → 비교 가능한 권리 Scope**로 바꾸는 것을 목표로 한다.


---

# 3. 대회 / 기술적 배경

K-RIGHTS는 **2026 오픈소스 개발자대회 티맥스티베로 지정과제**의 “OpenSQL 기반 AI 검색 및 벡터 데이터 플랫폼” 요구에 대응하는 프로젝트다.

현재 프로젝트 기준선에서 중요한 요구 방향은 다음과 같다.

- 문서 업로드
- AI 기반 문서 이해 및 구조화
- 임베딩 / 의미 검색
- 문서 및 메타데이터 관리
- 버전 / 변경 이력 관리
- MCP 기반 검색 인터페이스
- OpenSQL 기반 데이터 관리
- 계약 권리 충돌을 데이터 레이어에서 신뢰성 있게 관리

## 현재 인프라 기준

현재 확보된 OpenSQL 라이선스 제약 때문에 **OpenSQL Single Instance를 기본 개발/시연 기준선**으로 본다.

따라서 과거 초기 제안서에 존재하던 “3-node HA Failover를 반드시 시연한다” 같은 가정은 현재 이 저장소의 필수 전제가 아니다.

합성데이터 프로젝트에서 가장 중요한 OpenSQL 연결점은 **권리 데이터의 구조화 저장, 검색, 무결성, 결정론적 충돌 판정**이다.


---

# 4. 핵심 사용자

대표 사용자는 콘텐츠 제작사·배급사·방송사 등의 다음 담당자다.

- 콘텐츠 라이선싱 / 사업개발 담당자
- 저작권 / IP 관리 담당자
- 계약 관리 담당자
- 법무 검토 담당자

이들의 주요 질문은 다음과 같다.

```text
“이 작품의 일본 SVOD 권리는 지금 누구에게 가 있는가?”

“이 신규 계약을 체결하면 기존 독점계약과 겹치는가?”

“미국 Remake권을 우리가 다시 허락할 수 있는가?”

“배급사가 OTT에 이 권리를 재허락할 권한이 실제로 있는가?”

“이 계약에서 실제 권리기간은 언제까지인가?”

“영상 유통권은 정상인데 OST 관련 추가 처리가 필요한가?”
```


---

# 5. 전체 사용자 Flow

K-RIGHTS의 대표적인 End-to-End Flow는 다음과 같다.

```text
[1] 계약서 Upload
        ↓
[2] PDF Text Parsing / OCR
        ↓
[3] 문서 구조 인식
    - 본문
    - 조항
    - Definitions
    - Table
    - Schedule / Annex
    - Footnote
        ↓
[4] AI Rights Extraction
    - Content
    - Legal Right
    - Exploitation Mode
    - Territory
    - Period
    - Exclusivity
    - Modifier
    - Evidence
        ↓
[5] Normalization
    - 작품 Alias 통합
    - 국가/권역 정규화
    - SVOD 등 이용형태 정규화
    - 상대기간 계산
    - Series/Season/Episode/Edit 관계
        ↓
[6] Verification / Review Gate
    - Evidence 존재 확인
    - 추출 불확실성 확인
    - unresolved field 확인
        ↓
[7] Structured Data 저장
    Contract → RightsGrant[]
        ↓
[8] 기존 RightsGrant 조회 및 비교
        ↓
[9] R1~R9 Rule 적용
        ↓
[10] Result / Finding 생성
    NORMAL
    CONFLICT
    REVIEW_REQUIRED
    WARNING
        ↓
[11] UI / Report
    - 충돌 상대 계약
    - 충돌 Scope
    - Reason Code
    - 원문 Evidence
        ↓
[12] 검색 / 재조회
    - 조건 검색
    - 자연어 검색
    - Vector Search
    - MCP
```


---

# 6. 시스템의 가장 중요한 역할 분리

## 6.1 AI가 담당하는 것

AI/LLM은 주로 **비정형 계약서를 구조화 가능한 데이터로 변환하는 역할**을 담당한다.

예:

```text
원문:
"Licensee shall have the sole and exclusive right to exploit
the Program through subscription video-on-demand services
throughout the territory of Japan..."

        ↓

구조화 결과:

territory = JP
exploitation_mode = SVOD
exclusivity = EXCLUSIVE
```

AI가 담당하는 주요 작업:

- 조항 분류
- Rights Field 추출
- Raw Evidence 추출
- 한국어/영어/일본어 표현 해석
- alias / synonym 후보 인식
- Schedule / Table 정보 연결
- 상대기간 표현 추출
- 검색용 embedding 생성
- 사용자에게 결과 설명

## 6.2 AI가 임의로 해서는 안 되는 것

AI는 다음 정보를 근거 없이 만들어내면 안 된다.

```text
"Asia" → 임의로 JP/KR/TW/SG라고 가정

"Consent 문서 없음" → 승인을 받지 않았다고 확정

"계약기간 5년" → RightsGrant 기간도 5년이라고 가정

"영상 스트리밍 권리" → OST standalone streaming 권리도 있다고 가정

"2차 이용권" → 반드시 Remake권이라고 확정
```

이런 경우 실제 정보가 부족하면 `UNRESOLVED` 또는 `REVIEW_REQUIRED`로 남긴다.

## 6.3 Rule / DB가 담당하는 것

정규화된 RightsGrant가 만들어진 뒤에는 가능한 한 결정론적인 비교 규칙을 적용한다.

즉,

```text
“LLM이 보기에 충돌 같음”
```

이 아니라,

```text
Content Scope overlap?
Territory intersection exists?
Mode overlap?
Period overlap?
Exclusivity violated?
Authority exceeded?
```

처럼 명시적인 조건을 이용한다.


---

# 7. 핵심 데이터 모델

K-RIGHTS에서는 다음 객체를 혼동하면 안 된다.

```text
IP
 └─ Content
      └─ Contract
           └─ RightsGrant
                └─ Finding
```

실제 관계는 더 정확히 다음과 같다.

```text
IP
└─ 여러 관련 Content를 가질 수 있음

Contract
└─ 여러 RightsGrant를 포함할 수 있음

RightsGrant
└─ 특정 Content 또는 Related Asset을 대상으로 함

Scenario
└─ Target Contract + Existing/Reference Contract를 조합하여
   시스템 동작을 테스트함

Finding
└─ Scenario 또는 실제 신규 계약 검사 과정에서 발견된
   Conflict / Review / Warning 결과
```

## 주요 ID

| ID | 의미 |
|---|---|
| `ip_id` | 원작·프랜차이즈·상위 IP |
| `content_id` | 실제 권리 대상 콘텐츠 |
| `contract_id` | 계약 문서 |
| `grant_id` | 계약 내부 개별 RightsGrant |
| `finding_id` | 개별 판정 결과 |
| `scenario_id` | 합성데이터 테스트 시나리오 |

### 중요

**72 Scenario = 72 Contract가 아니다.**

한 Scenario는 여러 기존 계약을 참조할 수 있고, 동일 Existing Contract를 여러 Scenario가 공유할 수도 있다.


---

# 8. RightsGrant란 무엇인가

`RightsGrant`는 K-RIGHTS의 가장 핵심적인 데이터 단위다.

RightsGrant는 단순한 “권리 이름”이 아니라:

> **누가 누구에게 어떤 콘텐츠를 어떤 범위에서 이용할 수 있도록 허락했는가**

를 나타내는 한 묶음이다.

예:

```yaml
grant_id: GRT-000001
content_id: CNT001

legal_right:
  - TRANSMISSION

exploitation_mode:
  - SVOD

territory:
  - JP

license_start: 2027-01-01
license_end: 2029-12-31

exclusivity: EXCLUSIVE
```

한 Contract에 여러 RightsGrant가 존재할 수 있다.

```text
Contract A

Grant 1
KR / TV_LINEAR / Exclusive

Grant 2
KR / SVOD / Non-exclusive

Grant 3
JP / SVOD / Exclusive
```

따라서 **계약 전체를 하나의 Rights Type으로 압축하면 안 된다.**


---

# 9. Legal Right와 Exploitation Mode

두 필드는 반드시 분리한다.

## Legal Right

저작권법 및 계약상 **어떤 법적 권능을 사용할 수 있는가**에 가까운 개념이다.

예:

- 복제
- 배포
- 방송
- 전송
- 공중송신 관련 권리
- 공연
- 2차적저작물작성

## Exploitation Mode

실제 산업에서 **어떤 사업 방식으로 콘텐츠를 이용하는가**다.

예:

- SVOD
- AVOD
- TVOD
- Linear TV
- Theatrical
- Music Streaming

예를 들어:

```text
legal_right = transmission-related right
exploitation_mode = SVOD
```

처럼 함께 존재할 수 있다.

`SVOD`를 법적 권리와 동일시해서는 안 된다.


---

# 10. Conflict 판정 R1~R9

현재 K-RIGHTS의 판정 구조는 9개 Rule을 사용한다.

## R1. Content / IP Identity

언어·제목 Alias가 달라도 동일 콘텐츠인지 판정한다.

```text
겨울의 신호
Signal of Winter
冬のシグナル

→ 동일 canonical content
```

단 Remake는 같은 원작 계열일 수 있지만 원 영상과 동일 Content가 아니다.

## R2. Content Scope

Series / Season / Episode / Edit의 포함관계를 판단한다.

```text
Whole Series
    ⊃ Season 2
        ⊃ Episode 3
```

Edit는 계약상 포함 범위가 명확해야 한다.

## R3. Legal Rights Hierarchy

법적 권리 표현의 상·하위 또는 포함관계를 처리한다.

국가별 저작권 표현을 무조건 동일 synonym으로 단순화하지 않는다.

## R4. Exploitation Mode

SVOD / AVOD / TVOD / TV / Theatrical 등의 이용방식을 비교한다.

## R5. Territory Scope

지역은 문자열 비교가 아니라 **집합 Scope**로 비교한다.

```text
{JP, TW}
∩
{JP, SG}

=
{JP}
```

`Worldwide except US`처럼 제외조건도 반영한다.

## R6. License Period / Window

실제 RightsGrant 기간을 비교한다.

Contract 자체의 존속기간과 개별 이용허락기간은 다를 수 있다.

## R7. Exclusivity & Exceptions

Exclusive / Non-exclusive뿐 아니라:

- Reserved Rights
- Carve-out
- Holdback
- Window
- Platform restriction

등을 적용한 최종 Scope를 비교한다.

## R8. Authority / Rights Chain

재허락·양도 시 실제 권한의 출처를 확인한다.

```text
A → B : Japan only
B → C : Asia

→ B가 가진 Scope보다 넓게 허락
→ Authority Scope Exceeded
```

## R9. Derived / Related IP Rights

다음 권리를 원 영상권과 자동 동일시하지 않는다.

- Remake
- Format
- Sequel
- OST
- 기타 Related Asset


---

# 11. 결과 상태

K-RIGHTS는 단순히 `Conflict / No Conflict` 두 개로만 판단하지 않는다.

| Result | 의미 |
|---|---|
| `NORMAL` | 현재 데이터 기준으로 권리범위가 정상적으로 공존 가능 |
| `CONFLICT` | 권리범위가 양립할 수 없거나 명확한 권한 초과 |
| `REVIEW_REQUIRED` | 필요한 정보가 없거나 모호하여 자동 확정 불가능 |
| `WARNING` | 직접적인 Rights Conflict는 아니지만 체결·이용 전 확인할 리스크 |

## 예시

### NORMAL

```text
JP / SVOD / Exclusive
vs
KR / SVOD / Exclusive
```

Territory 비중첩.

### CONFLICT

```text
JP / SVOD / Exclusive
vs
JP / SVOD / Non-exclusive
```

동일 Scope에서 기존 Exclusive 침해.

### REVIEW_REQUIRED

```text
"Asia-Pacific countries listed in Schedule A"

하지만 Schedule A가 없음.
```

국가 Scope를 확정할 수 없음.

### WARNING

Remake권은 제작사가 보유하지만 기존 방송사에게 First Negotiation Right가 존재하고 신규 Remake 계약이 아직 Draft 단계인 경우.

Rights 자체의 중복은 아니지만 체결 전에 기존 절차 확인 필요.


---

# 12. Reason Code와 Conflict Scope

결과만 저장하면 부족하다.

예:

```text
CONFLICT
```

보다 다음 정보를 함께 저장한다.

```yaml
expected_result: CONFLICT

reason_code:
  - EXCLUSIVE_RIGHT_OVERLAP

conflict_scope:
  content: CNT003
  territory:
    - JP
  exploitation_mode:
    - AVOD
  period:
    start: 2027-01-01
    end: 2027-06-30
```

주요 Reason Code 예:

```text
EXCLUSIVE_RIGHT_OVERLAP
CONTENT_SCOPE_OVERLAP
AUTHORITY_SCOPE_EXCEEDED
AUTHORITY_PERIOD_EXCEEDED
UNAUTHORIZED_SUBLICENSE
DERIVATIVE_RIGHT_OVERLAP
HOLDBACK_VIOLATION

TERRITORY_UNRESOLVED
PERIOD_UNRESOLVED
EXCLUSIVITY_UNRESOLVED
CONTENT_IDENTITY_UNRESOLVED
SUBLICENSE_CONSENT_UNVERIFIED
DERIVATIVE_SCOPE_UNRESOLVED

CROSS_BORDER_MUSIC_CLEARANCE
PRIOR_NEGOTIATION_OBLIGATION
```


---

# 13. Evidence Anchoring

K-RIGHTS에서는 구조화 값만 저장하지 않고 **그 값을 판단하게 한 계약 원문 Evidence**를 함께 저장하는 것을 원칙으로 한다.

예:

```yaml
territory:
  normalized:
    - JP

  evidence:
    text: "within the territory of Japan"
    clause: "Article 4 - Territory"
```

이는 다음을 가능하게 한다.

- AI Extraction 검증
- 사용자에게 판정 근거 표시
- 잘못 추출된 필드 수정
- Conflict Report 설명 가능성
- 평가 데이터셋에서 span / evidence accuracy 측정


---

# 14. Evidence가 위치할 수 있는 곳

핵심 정보가 한 조항에 모여 있다고 가정하면 안 된다.

Evidence는 다음 위치에 있을 수 있다.

```text
Main Body
Definitions
Rights Grant Clause
Schedule / Annex / Exhibit
Table
Footnote
Other Clause
```

예:

```text
본문:
"SVOD rights may commence after the Holdback Period."

Schedule:
Theatrical Release: 2027-01-01
Holdback: 180 days
```

이 경우 실제 SVOD 시작 가능일을 판단하려면 두 Evidence를 함께 봐야 한다.


---

# 15. 주요 기능 모듈

## F1. 계약서 Upload / Document Intake

사용자가 PDF 등 계약 문서를 등록한다.

관리 대상 예:

- 원본 파일
- 파일 해시
- Contract ID
- 버전
- 언어
- 업로드 시각
- 처리 상태

---

## F2. Parsing / OCR

문서에서 텍스트와 구조를 추출한다.

대상:

- 일반 텍스트 PDF
- 스캔 PDF
- 표
- Schedule
- 다국어 계약

목적은 OCR 자체가 아니라 이후 Rights Extraction이 사용할 안정적인 문서 표현을 얻는 것이다.

---

## F3. Contract Structure Recognition

문서를 조항 단위로 분리하고 역할을 식별한다.

예:

```text
Definitions
License Grant
Territory
Term
Exclusivity
Reserved Rights
Sublicense
Assignment
Governing Law
Schedule
```

---

## F4. Rights Extraction

AI가 계약에서 RightsGrant를 구성하는 주요 값을 추출한다.

핵심:

```text
Content / IP
Content Scope
Legal Right
Exploitation Mode
Territory
License Period
Exclusivity
Evidence
```

추가 Modifier:

```text
Reserved Rights
Carve-out
Holdback
Sublicense
Assignment
Renewal
Platform
Language
Format / Edit
Derived Rights
OST / Related Asset
ROFR / ROFO / ROFN
```

---

## F5. Normalization

서로 다른 계약 표현을 비교 가능한 값으로 변환한다.

예:

```text
Japan
日本
日本国内
→ JP
```

```text
Subscription Video-on-Demand
subscription-based streaming
定額制動画配信
→ SVOD
```

단, **정규화와 추론을 혼동하지 않는다.**

계약이나 ontology에 없는 정보를 AI가 만들어서는 안 된다.

---

## F6. Verification

추출 결과가 실제 원문에서 지원되는지 확인한다.

검사 예:

- Evidence가 실제 존재하는가
- 필수 Field가 누락되었는가
- raw와 normalized 값이 일치하는가
- 상대기간 계산에 필요한 Anchor Date가 있는가
- 외부 문서 참조가 누락되었는가

필요한 정보가 없으면 `REVIEW_REQUIRED`가 될 수 있다.

---

## F7. Contract / RightsGrant Storage

구조화 결과를 DB에 저장한다.

중요한 것은 **Contract와 RightsGrant를 1:1로 가정하지 않는 것**이다.

```text
Contract
└─ RightsGrant 1
└─ RightsGrant 2
└─ RightsGrant 3
```

---

## F8. Conflict Detection

신규 Target RightsGrant와 기존 Grant를 비교한다.

```text
Target Grant
     ↓
Candidate Existing Grants 조회
     ↓
R1~R9 적용
     ↓
Finding 생성
```

일부 Scenario에서는 하나의 Target에 여러 Finding이 나올 수 있다.

---

## F9. Conflict / Review / Warning Report

사용자는 단순 상태값만 보는 것이 아니라 다음을 확인할 수 있어야 한다.

- 결과
- 상대 Contract
- 상대 RightsGrant
- Reason Code
- Content
- Territory
- Mode
- Period
- Exclusivity
- 겹친 Scope
- Evidence

---

## F10. Contract Search

사용자는 계약을 구조화 필드 기준으로 검색할 수 있다.

예:

```text
Content = Signal of Winter
Territory = JP
Mode = SVOD
```

또는:

```text
2027년에 만료되는 일본 독점 계약
```

같은 자연어 검색을 제공할 수 있다.

---

## F11. Vector / Semantic Search

계약 조항과 문서 내용을 embedding하여 의미적으로 유사한 내용을 찾는다.

예:

```text
"재허락에 사전 동의가 필요한 계약"
```

처럼 정확한 키워드가 없어도 관련 조항을 찾는 것을 목표로 한다.

Vector Search는 **Conflict Rule을 대신하지 않는다.**

검색 후보를 찾는 역할과 권리충돌 판정 역할은 구분한다.

---

## F12. MCP Interface

MCP를 통해 외부 AI Client / Agent가 K-RIGHTS의 검색·조회 기능을 사용할 수 있도록 한다.

MCP 역시 DB의 Ground Truth와 저장된 Evidence를 조회하는 인터페이스로 취급하며, 임의의 권리 판정을 새로 만드는 별도 판단엔진으로 사용하지 않는다.

---

## F13. Metadata / Version Management

계약 문서는 수정·갱신될 수 있으므로 다음 개념을 분리한다.

```text
contract_id
version_id
grant_id
scan_id
finding_id
```

최종 승인 전 Draft 수정과 실제 법적 Amendment / Renewal은 동일 개념이 아니다.

버전 정책은 최종 Backend 구현 정책을 따른다.

---

## F14. Change / Sync Management

문서 또는 구조화 데이터가 변경되면 검색 인덱스·임베딩·관련 metadata가 오래된 상태로 남지 않도록 동기화한다.

이 기능은 지정과제의 변경 로그 기반 동기화 요구와 연결된다.

---

## F15. Security / Audit

계약 데이터는 민감할 수 있으므로 프로젝트 전체에서는 다음을 중요하게 본다.

- 접근 권한
- 민감 정보 보호
- 감사 가능성
- 누가 어떤 문서를 조회·수정했는지 추적
- 데이터베이스 수준 무결성

구체 구현은 전체 Backend / OpenSQL 설계를 따른다.


---

# 16. Agent의 역할

K-RIGHTS의 Agent는 “법률가처럼 모든 계약을 자유롭게 판단하는 AI”로 설계하지 않는다.

Agent는 다음 작업을 조율한다.

```text
Document Parse
     ↓
Rights Extraction
     ↓
Normalization
     ↓
Evidence Verification
     ↓
DB / Rule Query
     ↓
Result Explanation
```

Agent의 핵심 가치는:

- 여러 Tool 호출 오케스트레이션
- 필요한 Evidence 수집
- Missing Field 확인
- 사용자에게 결과 설명

이다.

최종 구조화 Rule과 모순되는 자유 추론은 하지 않는다.


---

# 17. 대표적인 권리체인 Scenario

## Sublicense / Rights Chain

```text
Producer A
    ↓
Distributor B
    ↓
OTT C
```

B가 C에게 권리를 줄 수 있으려면 B가 A에게서 그 Scope를 받아야 한다.

예:

```text
A → B
JP / SVOD / 2027~2028

B → C
Asia / SVOD / 2027~2029
```

B가 Territory와 Period 모두 초과했다면 Authority 문제가 발생한다.


---

# 18. Remake / Derived Rights

원 영상의 방송·스트리밍권과 Remake권은 동일하지 않다.

예:

```text
Existing:
Original drama / JP / SVOD

New:
US Remake

→ 자동 Conflict가 아님
```

반면:

```text
Existing:
US Remake / Exclusive

New:
US Remake / Exclusive

→ DERIVATIVE_RIGHT_OVERLAP
```

First Negotiation Right처럼 권리 자체가 아니라 계약 절차상 우선권인 경우는 별도 Warning으로 처리할 수 있다.


---

# 19. OST / Music Rights

영상과 음악은 특히 자동 병합하면 안 된다.

예:

```text
Asset 1
Drama Video

Asset 2
OST Master

Asset 3
Underlying Musical Composition
```

다음도 구분한다.

```text
영상 내 OST 결합 이용

vs

OST Master standalone streaming
```

영상 SVOD권이 있다고 해서 OST를 독립 음원으로 유통할 권리가 자동으로 생기는 것은 아니다.


---

# 20. 프로젝트에서 하지 않는 것

K-RIGHTS는 다음 시스템을 목표로 하지 않는다.

## 법률 자문 자동화

시스템 결과는 계약 관리 및 검토 지원을 위한 것이며 실제 법률 자문 자체를 대체하지 않는다.

## 불명확한 계약내용 자동 보완

정보가 없으면 `UNRESOLVED`로 남긴다.

## LLM 단독 Conflict 판정

LLM의 자유 추론 결과를 최종 정답으로 사용하지 않는다.

## 실제 회사의 비공개 계약 재현

합성데이터의 회사명·작품명·금액은 가상값을 사용한다.

## 모든 저작권 문제 포괄

MVP는 K-RIGHTS가 정의한 Rights Scope와 Scenario를 중심으로 한다.


---

# 21. 합성데이터가 필요한 이유

실제 기업의 라이선스 계약은 개인정보·영업비밀·거래조건 때문에 대량 확보하기 어렵다.

또 공개 데이터만으로는 다음을 원하는 비율로 확보하기 어렵다.

- 정확히 충돌하는 계약 쌍
- 거의 같지만 정상인 Hard Negative
- Rights Chain
- Holdback
- Relative Period
- Missing Schedule
- Remake
- OST
- 다국어 동일 Content
- Multi-Grant

따라서 K-RIGHTS에서는 **Ground Truth가 명확한 합성 계약 데이터셋**을 구축한다.


---

# 22. 현재 합성데이터 구성

> 확정 산출물 수치와 Phase 진행 상태는 `docs/synthetic_data/DATASET_STATUS.md`가 기준이다.

현재 기준:

```text
Master Scenario    60
Robustness         12
---------------------
Total Scenario     72
```

언어:

```text
KO 24
EN 24
JP 24
```

Scenario는 Contract 수와 동일하지 않다.

하나의 Conflict Scenario에서 여러 Contract가 필요할 수 있다.

```text
Scenario KO-C07

Reference Contract A
Reference Contract B
Target Contract C

→ Scenario = 1
→ Contract = 3
```

반대로 동일 Existing Contract를 여러 Scenario에서 공유할 수 있다.


---

# 23. Master Scenario 역할

60개 Master는 크게 다음 목적을 가진다.

| Group | 역할 |
|---|---|
| Normal | 일반 정상 데이터 |
| Boundary | Conflict와 유사하지만 실제 NORMAL인 Hard Negative |
| Conflict L1 | 직접적으로 명확한 충돌 |
| Conflict L2 | 정규화 / hierarchy 해석이 필요한 충돌 |
| Conflict L3 | Multi-Clause / Multi-Grant / Rights Chain 기반 충돌 |
| Review Required | 정보 부족으로 자동 확정 불가능 |
| Warning | 직접 Rights Conflict는 아니지만 확인할 리스크 |


---

# 24. Robustness Scenario 역할

Robustness는 새로운 법적 유형을 만드는 것이 아니다.

동일한 Ground Truth를 다음처럼 바꿔도 같은 결과가 나오는지 평가한다.

- 언어 표현 변경
- synonym
- clause 위치 변경
- Schedule 분산
- Table
- Footnote
- 상대기간
- Alias
- Episode / Edit 표현

즉:

```text
법률 Rule Robustness
```

보다는:

```text
OCR / Extraction / Normalization Robustness
```

를 검증한다.


---

# 25. 합성계약 Template

현재 6개 Template을 사용한다.

| Template | 역할 |
|---|---|
| T1 | 저작재산권 이용허락형 |
| T2 | 방송프로그램 방영·전송권형 |
| T3 | 단일 RightsGrant 간이형 |
| T4 | 복수 RightsGrant 장문형 |
| T5 | 본문 + Schedule형 |
| T6 | 영상 + OST 결합권리형 |

Template은 단순 디자인 차이가 아니다.

**권리정보가 문서 어디에 어떻게 배치되는지를 다르게 만들어 Extraction 난이도와 계약 현실성을 조절하는 역할**을 한다.


---

# 26. 계약 조항 Label

조항은 목적에 따라 세 종류로 본다.

## CORE

Conflict 판정에 직접 필요한 정보.

```text
Content
License Grant
Legal Right
Exploitation Mode
Territory
Period
Exclusivity
```

## MODIFIER

Rights Scope를 실제로 바꿀 수 있는 조항.

```text
Reserved Rights
Carve-out
Holdback
Sublicense
Assignment
Renewal
Platform
Language
Format
Derived Rights
Related Asset / OST
ROFR / ROFO / ROFN
Exclusive Window
Termination Effect
```

## DISTRACTOR / Boilerplate

문서 현실성 및 Extraction 난이도를 높이지만 기본 충돌식의 핵심은 아닌 조항.

```text
Governing Law
Dispute Resolution
Payment
Audit
Confidentiality
Representations
Indemnification
Notice
Force Majeure
```


---

# 27. 합성데이터 생성의 절대 원칙

반드시 다음 순서를 지킨다.

```text
Scenario
   ↓
Contract Graph
   ↓
Ground Truth / RightsGrant GT
   ↓
Evidence Requirement
   ↓
Template / Clause Outline
   ↓
Contract Body
   ↓
GT ↔ Contract Validation
   ↓
PDF / Evaluation Data
```

**계약서를 먼저 작성하고 나중에 정답을 맞추지 않는다.**


---

# 28. 설계 불변 조건 — 임의로 바꾸지 않는다

다음은 현재 프로젝트 기준선이다.

- 72 Scenario 구성 자체를 임의 재설계하지 않는다.
- R1~R9를 임의 축소하지 않는다.
- `legal_right`와 `exploitation_mode`를 합치지 않는다.
- Scenario / Contract / RightsGrant / Finding ID를 혼용하지 않는다.
- Review 정보를 임의 추론하지 않는다.
- Contract Term을 License Period로 사용하지 않는다.
- Asia / APAC를 정의 없이 국가목록으로 확장하지 않는다.
- Consent 문서 부재를 실제 미승인이라고 판정하지 않는다.
- Remake와 원 영상권을 자동 동일시하지 않는다.
- OST와 영상 Content를 자동 동일 Asset으로 병합하지 않는다.
- 모든 복잡한 계약을 Conflict로 만들지 않는다.
- Boundary Scenario의 Hard Negative 성격을 훼손하지 않는다.


---

# 29. 대표 Demo 관점

## Demo A — OTT 권리체인 / 충돌

신규 OTT 계약을 등록했을 때:

```text
Upstream 권한 확인
+
기존 Exclusive 계약 확인
+
Target Scope 비교
```

를 통해 Authority 및 Exclusive overlap을 탐지한다.

## Demo B — 해외 음악권 Warning

영상 배급 자체는 정상이어도 음악 관련 별도 Clearance 조항을 찾아 `WARNING`을 제공한다.

## Demo C — Remake

동일한 Remake 거래라도:

```text
Reserved Right
Existing Exclusive Remake
First Negotiation Right
```

에 따라 NORMAL / CONFLICT / WARNING이 달라지는 것을 보여준다.


---

# 30. 전체 시스템의 핵심 가치

K-RIGHTS의 핵심은 단순히 “계약서를 AI로 읽는다”가 아니다.

### 1. 계약서의 복잡한 권리 구조를 데이터로 바꾼다.

```text
PDF
→ RightsGrant
```

### 2. 다른 계약끼리 비교 가능한 형태로 정규화한다.

```text
日本
Japan
Japanese territory

→ JP
```

### 3. 근거가 없는 추론을 줄인다.

```text
Structured Field
+
Raw Evidence
```

### 4. Conflict 판정을 재현 가능하게 만든다.

같은 입력이면 같은 Rule 결과가 나와야 한다.

### 5. 단순 Conflict 이외의 상태를 분리한다.

```text
NORMAL
CONFLICT
REVIEW_REQUIRED
WARNING
```

### 6. 사람이 최종 검토할 수 있는 설명 가능한 결과를 제공한다.

```text
무엇이
어느 범위에서
어떤 기존 계약과
왜 충돌하는지
```

를 Evidence와 함께 보여주는 것이 목표다.


---

# 31. 최종 요약

K-RIGHTS를 가장 짧게 이해하면 다음과 같다.

```text
문제:
계약서가 PDF·다국어·복잡한 조항 형태라
기존 권리와 신규 권리의 중복을 사람이 놓칠 수 있다.

해결:
AI가 계약을 RightsGrant로 구조화한다.

검증:
모든 추출값에 원문 Evidence를 연결한다.

판정:
R1~R9에 따라 기존 RightsGrant와 Target Grant를 비교한다.

결과:
NORMAL / CONFLICT / REVIEW_REQUIRED / WARNING

저장·검색:
OpenSQL 기반 구조화 데이터 + 검색/Vector/MCP 인터페이스

합성데이터:
이 전체 Pipeline이 정확한지 검증할 72 Scenario 기반 테스트 데이터셋
```

**핵심 설계 철학:**

> AI에게 계약의 의미를 읽게 하되, 근거 없이 권리를 만들어내게 하지 않는다.  
> 권리충돌은 비교 가능한 구조화 Scope와 명시적인 규칙으로 판단한다.

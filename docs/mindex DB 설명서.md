# Mindex Remastered DB 구조 및 서비스 플로우 설명

> 이 문서는 [`mindex_remastered.dbml`](mindex_remastered.dbml)의 설명본이다.
> 테이블·상태·관계·제약이 다를 경우 DBML을 정본으로 보며, 스키마 변경 시 두 파일을 함께 갱신한다.

## 1. 전체 구조 요약

이 DB는 단순히 계약서를 저장하는 구조가 아니라 다음 전체 흐름을 DB 레벨에서 관리하도록 설계되어 있다.

```text
계약서 업로드
→ AI 권리 추출
→ DB 사전 판정
→ 사용자 검토/승인
→ 실제 권리 등록
→ DB 최종 충돌 방어
→ 계약 최종 확정
```

핵심은 **AI가 추출한 정보와 실제 확정 권리를 분리**한 것이다.

```text
rights_grant_candidate
= AI가 계약서에서 추출한 미확정 권리

rights_grant
= 사람이 확인하고 DB 제약까지 통과한 실제 확정 권리
```

전체 구조는 다음처럼 볼 수 있다.

```text
[기준정보]

country
territory_group
territory_group_member

legal_right
exploitation_mode
statutory_right
right_mapping

reason_code
constraint_reason_map


        ↓


[계약 / 원문]

ip
contract
contract_document
contract_version


        ↓


[AI 추출]

rights_grant_candidate
        │
        └── candidate_evidence


        ↓


[DB 판정]

rights_evaluation
        │
        └── rights_evaluation_reason


        ↓

conflict_resolution


        ↓


[실제 확정 권리]

rights_grant
        │
        └── rights_grant_history


        ↓


[검색 / 운영]

contract_chunk
change_log
schema_meta
```

---

# 2. 테이블별 설명

## 2.1 설치 경계

Mindex는 여러 고객사가 하나의 DB를 공유하는 SaaS가 아니라 회사 서버에 직접 설치되는 단일 회사용 시스템이다. 따라서 `tenant` 테이블과 `tenant_id` 컬럼을 사용하지 않는다.

```text
A사 설치 → A사 전용 애플리케이션과 DB
B사 설치 → B사 전용 애플리케이션과 DB
```

회사 간 데이터 격리는 설치 인스턴스와 DB 경계가 담당한다. 사용자별 인증과 역할 권한은 별도 애플리케이션 관심사이며, IP 행은 해당 설치에서 관리하는 작품이라는 뜻이지 법적 소유권을 의미하지 않는다.

---

## 2.2 `country`

국가 정보를 관리하는 마스터 테이블이다.

```text
KR = 대한민국
JP = 일본
US = 미국
TH = 태국
```

권리 충돌 판정에서는 territory가 중요한 축이기 때문에 국가 값을 정규화해서 관리한다.

예를 들어 동일 작품, 동일 권리, 동일 기간이라도

```text
KR
vs
JP
```

이면 일반적으로 서로 다른 territory이므로 직접 충돌하지 않는다.

---

## 2.3 `territory_group`

여러 국가를 하나의 지역 그룹으로 묶기 위한 테이블이다.

예:

```text
WORLDWIDE
APAC
SEA
EU
NA
```

여기서 중요한 것은 `SEA` 같은 그룹명을 실제 권리 충돌 키로 그대로 저장하지 않는다는 점이다.

예를 들어

```text
기존 권리 = TH
신규 권리 = SEA
```

라고 저장하면 DB 입장에서는 문자열이 서로 다르므로 태국이 실제로 SEA에 포함되어 있어도 충돌을 바로 판단할 수 없다.

따라서 territory group은 실제 권리를 저장하는 값이라기보다 **국가 단위로 확장하기 위한 기준정보**다.

---

## 2.4 `territory_group_member`

지역 그룹에 어떤 국가들이 포함되는지를 저장한다.

예:

```text
SEA → TH
SEA → VN
SEA → SG
SEA → MY
```

계약서에 `Southeast Asia`처럼 지역 단위 표현이 있으면 이 테이블을 통해 실제 국가 단위로 전개할 수 있다.

---

# 3. 권리 기준정보 구조

## 3.1 `legal_right`

법적으로 어떤 행위를 할 수 있는지를 표현하는 테이블이다.

예:

```text
PUBLIC_TRANSMISSION
├── BROADCAST
└── TRANSMISSION

PUBLIC_PERFORMANCE
DISTRIBUTION
REPRODUCTION
DERIVATIVE_WORK_CREATION
```

예를 들어 `TRANSMISSION`은 전송할 권리이고, `DISTRIBUTION`은 배포할 권리다.

이 테이블은 ENUM이 아니라 계층 구조로 관리한다.

그 이유는 상위 권리와 하위 권리 사이에도 충돌이 발생할 수 있기 때문이다.

예:

```text
PUBLIC_TRANSMISSION
└── TRANSMISSION
```

누군가 `PUBLIC_TRANSMISSION`을 독점적으로 가지고 있는데 다른 사람이 `TRANSMISSION`을 독점적으로 다시 받는다면 권리 범위가 겹칠 수 있다.

---

## 3.2 `legal_right`의 `lft`, `rgt`, `span`

계층 관계를 DB에서 범위 연산으로 비교하기 위해 사용한다.

예:

```text
PUBLIC_TRANSMISSION [1,7)
BROADCAST           [2,4)
TRANSMISSION        [4,6)
```

`PUBLIC_TRANSMISSION`과 `TRANSMISSION`은 범위가 겹친다.

```text
[1-------------7)
        [4---6)
```

따라서 PostgreSQL range overlap 연산인 `&&`로 상위-하위 포함관계를 충돌 판정에 사용할 수 있다.

반면

```text
BROADCAST    [2,4)
TRANSMISSION [4,6)
```

은 형제 노드이므로 범위가 겹치지 않는다.

---

## 3.3 `exploitation_mode`

법적 권리를 실제 사업에서 어떤 방식으로 이용하는지를 표현한다.

예:

```text
VOD
├── SVOD
├── AVOD
└── TVOD

TV_LINEAR
THEATRICAL
AUDIO_STREAMING
```

예를 들어

```text
legal_right = TRANSMISSION
exploitation_mode = SVOD
```

라면 법적으로는 전송권이고, 사업적으로는 구독형 VOD 방식으로 이용하는 권리라는 뜻이다.

TVOD 계약이라면

```text
legal_right = TRANSMISSION
exploitation_mode = TVOD
```

가 될 수 있다.

즉 `legal_right`와 `exploitation_mode`는 서로 다른 축이다.

---

## 3.4 `exploitation_mode`가 계층 구조인 이유

계약서에는 다음처럼 상위 개념이 그대로 등장할 수 있다.

```text
All VOD rights
```

이를 억지로 SVOD, AVOD, TVOD 중 하나로 바꾸면 원문 의미가 변한다.

따라서

```text
VOD
├── SVOD
├── AVOD
└── TVOD
```

처럼 상위 개념 자체를 저장할 수 있게 하고, span을 사용해 하위 개념과의 포함관계를 판정한다.

예를 들어 기존에 `VOD` 독점권이 있다면 신규 `SVOD` 독점권은 하위 범위이므로 충돌할 수 있다.

반면 `SVOD`와 `TVOD`는 형제 노드이므로 별도의 권리로 존재할 수 있다.

---

## 3.5 `statutory_right`

각 국가 법체계에서 실제로 사용하는 법정 권리명을 저장하는 테이블이다.

예:

```text
KR_TRANSMISSION
JP_PUBLIC_TRANSMISSION
```

국가마다 권리의 명칭과 법적 분류가 다를 수 있기 때문에 그대로 충돌 키로 사용하지 않고 공통 `legal_right`로 정규화한다.

예:

```text
KR_TRANSMISSION
       ↓
TRANSMISSION

JP_XXX_RIGHT
       ↓
TRANSMISSION
```

따라서 다른 관할에서 다른 이름을 사용하더라도 내부 판정축은 공통화할 수 있다.

---

## 3.6 `right_mapping`

다음 조합이 특정 관할에서 일반적으로 자연스러운지 관리하는 참고 테이블이다.

```text
legal_right
+
exploitation_mode
+
jurisdiction
```

예:

```text
TRANSMISSION + SVOD + KR
```

이 조합이 일반적인지 검토하는 데 사용할 수 있다.

다만 이 테이블은 자동 변환표가 아니다.

예를 들어 계약서에 legal right가 없는데

```text
SVOD → TRANSMISSION
```

이라고 자동 생성하면 실제 계약서에 없는 법적 사실을 시스템이 만들어내게 된다.

따라서 `right_mapping`은 **자동 변환용이 아니라 자문·검토용 기준정보**다.

---

# 4. 판정 코드 구조

## 4.1 `reason_code`

서비스에서 발생할 수 있는 모든 판정 사유를 정규화해서 관리하는 마스터 테이블이다.

예:

```text
EXCLUSIVE_RIGHT_OVERLAP
TERRITORY_MISSING
TERRITORY_UNRESOLVED
LOW_CONFIDENCE
AMBIGUOUS_CLAUSE
```

각 사유는 다음 속성을 가질 수 있다.

```text
category
result_type
severity
is_blocking
is_review_trigger
is_decision_reason
template_ko
```

코드 내부에서 메시지를 직접 하드코딩하는 대신 reason code를 기준으로 판정과 사용자 메시지를 일관되게 관리할 수 있다.

---

## 4.2 `constraint_reason_map`

PostgreSQL의 제약조건 이름과 서비스의 reason code를 연결한다.

예:

```text
DB constraint
no_exclusive_overlap

        ↓

reason_code
EXCLUSIVE_RIGHT_OVERLAP
```

DB가 실제로 반환하는 오류 메시지를 그대로 사용자에게 보여주는 대신 서비스에서 이해 가능한 의미로 변환하기 위한 테이블이다.

즉

```text
DB 오류
→ 서비스 판정 코드
→ 사용자 메시지
```

로 연결하는 번역표 역할을 한다.

---

# 5. 계약 업무 테이블

## 5.1 `ip`

작품 자체를 관리한다.

예:

```text
오징어 게임
기생충
귀멸의 칼날
```

언어마다 제목이 다르더라도 같은 작품은 하나의 IP로 관리해야 한다.

예:

```text
오징어 게임
Squid Game
イカゲーム
```

이 서로 다른 작품으로 저장되면 같은 작품의 권리 충돌을 놓칠 수 있기 때문이다.

---

## 5.2 `contract`

계약 업무 한 건을 나타내는 루트 테이블이다.

즉 PDF 파일 자체가 아니라 하나의 계약 업무다.

예:

```text
오징어게임 일본 SVOD 독점 계약
```

상태는 다음처럼 흐를 수 있다.

```text
draft
review
approved
final
rejected
terminated
```

---

## 5.3 `contract_document`

실제로 업로드한 계약서 파일을 관리한다.

계약 하나에 여러 버전의 PDF가 있을 수 있으므로 `contract`와 `contract_document`를 분리한다.

예:

```text
contract #100

├── document v1 초안.pdf
├── document v2 수정본.pdf
└── document v3 최종본.pdf
```

PDF 바이너리를 DB에 직접 저장하기보다 `storage_key`를 통해 Object Storage 위치를 참조할 수 있다.

또한 `file_hash`를 통해 동일 파일 중복 업로드를 검사할 수 있다.

`raw_text`에는 PDF 파싱 결과를 저장할 수 있다.

상태는 예를 들어 다음처럼 진행된다.

```text
uploaded
→ parsing
→ parsed
→ review
→ approved
→ final

분기: rejected / failed
```

---

## 5.4 `contract_version`

계약 PDF 파일 버전이 아니라 **계약 메타데이터 변경 이력**을 관리한다.

예를 들어 다음 값이 변경되면 이전 상태를 snapshot으로 저장할 수 있다.

```text
counterparty
signed_date
amount
currency
status
```

즉

```text
contract_document
= 문서 파일 버전

contract_version
= 계약 메타데이터 변경 이력
```

이다. 현재 메타데이터 버전은 `contract.version`이 나타내며, 변경 전 상태는 `contract_version.snapshot`에 보존된다. 이 버전은 `contract_document.version`과 별개다.

---

# 6. AI 추출 계층

## 6.1 `rights_grant_candidate`

AI가 계약서를 읽고 추출한 권리 후보를 저장한다.

예:

```text
IP = 오징어게임
territory = JP
legal_right = TRANSMISSION
exploitation_mode = SVOD
period = [2026-01-01, 2028-01-01)
exclusivity = exclusive
confidence = 0.94
```

이 값은 아직 확정 권리가 아니다.

즉

```text
candidate
= 계약서에서 이렇게 읽혔다는 후보
```

다.

후보 상태는 `extracted`, `review`, `approved`, `rejected` 네 가지다. `status = review`이면 `review_reason_code`가 반드시 있어야 한다. 검토를 마친 뒤에도 이 값은 지우지 않아 과거에 왜 검토가 필요했는지 보존한다.

---

## 6.2 candidate에서 NULL을 허용하는 이유

AI가 계약서에서 모든 정보를 항상 찾을 수 있는 것은 아니다.

예:

```text
territory 불명확
법적 권리 표현 애매
기간 미기재
```

따라서 candidate에는 일부 NULL을 허용할 수 있다.

대신 다음과 같은 reason code를 발생시켜 검토 대상으로 보낸다.

```text
TERRITORY_MISSING
LEGAL_RIGHT_MISSING
PERIOD_MISSING
LOW_CONFIDENCE
```

---

## 6.3 `candidate_evidence`

AI가 왜 해당 값을 추출했는지를 사용자에게 증명하기 위한 근거다.

후보 하나의 근거가 여러 페이지와 조항에 흩어질 수 있으므로 candidate의 단일 컬럼이 아니라 1:N 테이블로 저장한다.

예:

```text
page_start = 13
page_end = 14
source_clause = 제8조 이용권
source_quote = "Licensee shall have the exclusive SVOD right..."
```

사용자는 판정 결과뿐 아니라 AI가 어떤 문장을 근거로 해당 값을 추출했는지 확인할 수 있다.

---

# 7. 판정 계층

## 7.1 `rights_evaluation`

하나의 candidate에 대한 **사전 판정 1회분의 결과**를 저장한다. 최종 무결성 판정은 이후 `rights_grant` INSERT 시 EXCLUDE와 trigger가 담당한다.

재판정할 때 기존 행을 덮어쓰지 않고 새 evaluation 행을 추가한다. 따라서 이 테이블은 append-only이며, 현재 판정은 candidate별 가장 큰 `rights_evaluation.id`다.

예:

```text
NORMAL
CONFLICT
REVIEW_REQUIRED
WARNING
```

각 의미는 다음과 같다.

### NORMAL

문제가 없어 등록 가능한 상태.

### CONFLICT

기존 확정 권리와 실제 충돌이 존재하는 상태.

### REVIEW_REQUIRED

DB만으로 확정하기 어렵거나 사람이 확인해야 하는 상태.

예:

```text
territory 없음
confidence 낮음
권리 표현 모호
```

### WARNING

등록을 막지는 않지만 사용자에게 알려야 하는 상태.

---

## 7.2 `rights_evaluation_reason`

evaluation이 왜 그런 결과가 나왔는지를 저장하는 상세 사유 테이블이다.

예:

```text
rights_evaluation
result_type = CONFLICT
```

만 저장하면 사용자는 왜 충돌인지 알 수 없다.

따라서 하위에 여러 개의 reason을 저장한다.

예:

```text
evaluation #50

reason #1
reason_code = EXCLUSIVE_RIGHT_OVERLAP
conflicting_grant_id = 31
overlap_period = [2026-05-01, 2027-01-01)

reason #2
reason_code = EXCLUSIVE_RIGHT_OVERLAP
conflicting_grant_id = 72
overlap_period = [2026-08-01, 2026-12-01)
```

즉 관계는 다음과 같다.

```text
rights_evaluation
      1
      │
      N
rights_evaluation_reason
```

각 사유의 처리 상태는 `detected`, `resolved`, `waived`다. 최신 evaluation에 `detected` 상태의 blocking 사유가 남아 있으면 candidate를 등록할 수 없다.

---

## 7.3 왜 `conflicting_grant_id`가 reason에 있는가

신규 candidate 하나가 기존 권리 여러 개와 동시에 충돌할 수 있기 때문이다.

예:

```text
신규 candidate
→ 기존 grant #31과 충돌
→ 기존 grant #72와 충돌
→ 기존 grant #91과 충돌
```

따라서 evaluation 한 건에 여러 reason이 붙는 구조가 맞다.

---

## 7.4 왜 `overlap_period`가 reason에 있는가

각 기존 권리와 겹치는 기간이 서로 다를 수 있기 때문이다.

예:

```text
신규 권리
2026 ~ 2030

기존 A
2026 ~ 2027

기존 B
2028 ~ 2029
```

A와 겹치는 기간과 B와 겹치는 기간이 다르므로 각각의 reason에 저장하는 것이 맞다.

---

## 7.5 `is_primary`

사유가 여러 개인 경우 UI에서 대표적으로 보여줄 사유를 지정한다. 한 evaluation에는 primary reason을 최대 한 건만 둘 수 있다.

예:

```text
판정 결과: CONFLICT

주요 사유:
기존 독점 권리와 기간 중복

추가 사유:
...
```

---

## 7.6 `deterministic_detail`

DB가 왜 그런 판정을 했는지 재현 가능한 구조적 근거를 저장한다.

예:

```json
{
  "legal_right_relation": "parent_contains_child",
  "candidate_legal_right": "PUBLIC_TRANSMISSION",
  "existing_legal_right": "TRANSMISSION",
  "exploitation_mode_relation": "same",
  "territory": "JP"
}
```

즉 사람이 읽기 위한 메시지뿐 아니라 **판정을 재현할 수 있는 기계적 근거**를 남기는 영역이다.

---

# 8. 충돌 처리

## 8.1 `conflict_resolution`

충돌이 발생했을 때 사용자가 어떻게 처리했는지 기록한다.

이 테이블은 evaluation 전체가 아니라 해결할 `rights_evaluation_reason` 한 건을 `evaluation_reason_id`로 가리킨다. 한 candidate가 여러 기존 권리와 충돌할 수 있으므로 어떤 상대 권리를 처리하는지 사유 단위로 특정해야 한다.

DB trigger는 대상 사유가 실제 `CONFLICT`인지 검증한다. `REVIEW_REQUIRED`나 `WARNING` 사유에는 resolution을 만들 수 없고, 충돌 상대 grant가 없는 사유에는 WAIVER를 적용할 수 없다.

대표적인 처리 방식은 다음과 같다.

```text
WAIVER
AMENDED
REJECTED
```

enum에는 향후 확장 지점으로 `MUTUAL_AGREEMENT`, `MANUAL_OVERRIDE`도 존재하지만 MVP에서는 지원하지 않는다. 두 방식은 충돌 권리를 겹친 채 공존시켜 EXCLUDE의 무조건 차단 원칙을 흔들기 때문이다.

처리 상태는 `pending`, `approved`, `rejected`이며, 사유와 승인자·승인시각 및 선택적인 증빙 문서를 기록한다.

---

## 8.2 `AMENDED`

신규 계약 조건을 수정해서 충돌을 제거하는 방식이다.

예:

```text
기존 권리
JP / SVOD / 2026~2028 / exclusive

신규 권리
JP / SVOD / 2027~2029 / exclusive
```

충돌이 발생하면 신규 계약을

```text
2028~2029
```

로 수정한 뒤 다시 candidate를 판정한다.

즉

```text
수정
→ candidate 업데이트
→ evaluate_candidate() 재실행
```

이다.

---

## 8.3 `REJECTED`

신규 계약 또는 해당 권리 등록을 포기한다.

```text
candidate.status = rejected
```

등으로 종료할 수 있다.

---

## 8.4 `WAIVER`

기존 권리자가 권리를 포기했거나 충돌 권리를 종료시키는 근거가 있는 경우다.

예:

```text
기존 rights_grant #31
→ 신규 candidate와 충돌
```

WAIVER가 승인되면

```text
rights_grant #31
status = terminated
```

처리한 뒤 신규 candidate를 다시 판정한다.

중요한 것은 WAIVER가 EXCLUDE constraint를 무시하는 기능이 아니라는 점이다.

```text
WAIVER
≠
DB 제약 우회
```

실제 흐름은 다음과 같다.

```text
신규 candidate
→ CONFLICT
→ conflicting_grant_id 확인
→ WAIVER 승인
→ 기존 grant 종료
→ 신규 candidate 재판정
→ 충돌 없음
→ 신규 rights_grant INSERT
```

즉 충돌의 원인을 제거한 뒤 정상적으로 다시 INSERT하는 구조다.

---

# 9. 확정 권리 계층

## 9.1 `rights_grant`

현재 시스템이 실제로 인정하는 확정 권리를 저장하는 핵심 테이블이다.

이 테이블이 권리 데이터의 Single Source of Truth 역할을 한다.

각 grant는 unique한 `source_candidate_id`로 승인 원본 candidate를 가리킨다. 근거 페이지와 원문 인용은 grant에 복제하지 않고 `source_candidate_id → candidate_evidence`로 따라가 조회한다.

```text
rights_grant_candidate
= AI가 읽어낸 미확정 정보

rights_grant
= 사용자 검토 + 판정 + DB 제약을 통과한 확정 정보
```

상태는 `approved`, `final`, `terminated`다. candidate 등록 직후에는 `approved`이고 최종 계약에 포함되면 `final`, 권리가 종료되면 `terminated`가 된다. `approved`와 `final`만 충돌 방어 대상이며 `terminated`는 제외된다.

핵심 판정축은 다음과 같다.

```text
ip
territory
legal_right
exploitation_mode
period
exclusivity
```

즉 쉽게 풀면

> 어떤 작품을, 어느 국가에서, 어떤 법적 권리와 이용 방식으로, 언제부터 언제까지, 어떤 독점 조건으로 보유하는가

를 저장한다.

---

## 9.2 `legal_right_span`, `exploitation_mode_span`

EXCLUDE constraint가 계층 포함관계를 직접 판정하기 위한 비정규화 값이다.

원래 `rights_grant.legal_right`를 통해 `legal_right.span`을 조회할 수 있지만 PostgreSQL EXCLUDE constraint 내부에서 다른 테이블을 조인해 사용할 수 없다.

따라서 실제 grant 테이블에도 span을 저장한다.

```text
legal_right_span
exploitation_mode_span
```

다만 애플리케이션이 임의로 값을 넣으면 안 된다.

DB trigger가 기준 테이블을 읽어 자동으로 채워야 한다.

---

# 10. EXCLUDE 기반 최종 충돌 방어

최종 권리 등록 시 DB는 대략 다음 축을 비교한다.

```text
ip_id                  =
legal_right_span       &&
exploitation_mode_span &&
territory              =
period                 &&
```

그리고 일반적으로

```text
exclusivity <> 'non_exclusive'
status IN ('approved', 'final')
```

등의 조건에 적용된다.

쉽게 말하면 아래 조건이 모두 맞으면 충돌 가능성이 높다.

```text
같은 작품
+
법적 권리 범위 겹침
+
이용형태 범위 겹침
+
같은 국가
+
기간 겹침
+
독점권
```

이 경우 DB가 INSERT 자체를 막는다.

---

# 11. EXCLUDE 예시

기존 권리:

```text
IP = A
territory = KR
legal_right = TRANSMISSION
exploitation_mode = SVOD
period = 2026~2028
exclusive
```

신규 권리:

```text
IP = A
territory = KR
legal_right = PUBLIC_TRANSMISSION
exploitation_mode = VOD
period = 2027~2029
exclusive
```

법적 권리는

```text
PUBLIC_TRANSMISSION
└── TRANSMISSION
```

관계이므로 span이 겹친다.

이용형태도

```text
VOD
└── SVOD
```

관계이므로 span이 겹친다.

기간도 2027~2028이 겹친다.

따라서 EXCLUDE가 INSERT를 막을 수 있다.

---

# 12. 반대로 충돌하지 않는 예

```text
기존:
TRANSMISSION + SVOD

신규:
TRANSMISSION + TVOD
```

SVOD와 TVOD는 형제 노드이므로 exploitation mode span이 겹치지 않는다.

따라서 다른 조건이 같더라도 별도 권리로 취급할 수 있다.

---

# 13. non-exclusive 처리

현재 EXCLUDE 조건이

```text
exclusivity <> 'non_exclusive'
```

형태라면 EXCLUDE 자체는 주로 exclusive/sole 등의 독점권 간 구조적 중복을 담당한다.

하지만 정책상

```text
exclusive ↔ non_exclusive
```

조합도 충돌할 수 있다.

이런 XOR 계열 배타성 충돌은 별도의 statement trigger가 확인할 수 있다.

즉 최종 DB 방어는 두 층으로 볼 수 있다.

```text
EXCLUDE
→ 독점권끼리의 구조적 범위 중복 방어

statement trigger
→ exclusive / non-exclusive 등 배타성 정책 방어
```

---

# 14. `rights_grant_history`

확정 권리의 변경 이력을 저장한다.

`rights_grant`가 현재 상태라면 `rights_grant_history`는 과거 상태를 저장한다.

예:

```text
registered
finalized
terminated
status_changed
```

WAIVER 때문에 기존 grant가 종료되었다면 그 사실도 history에 남긴다.

이를 통해 나중에 다음 질문에 답할 수 있다.

```text
왜 이 권리가 종료됐지?
누가 언제 변경했지?
어떤 사유로 상태가 바뀌었지?
```

---

# 15. 검색 및 운영 테이블

## 15.1 `contract_chunk`

RAG 및 벡터 검색을 위해 계약서 원문을 작은 단위로 분리해 저장한다.

예:

```text
제1조 ...
제2조 ...
제8조 독점권 ...
```

주요 정보는 다음과 같다.

```text
chunk_text
embedding
page
clause_no
document_id
```

사용자가

> 이 계약서의 일본 독점 기간이 뭐였지?

같이 질문하면 벡터 검색으로 관련 조항을 찾을 수 있다.

`document_id`가 중요한 이유는 계약서 버전마다 내용이 다를 수 있기 때문이다.

---

## 15.2 `change_log`

변경 감지 및 후처리용 운영 테이블이다.

`contract_document.raw_text`가 INSERT 또는 실제 변경되면

```text
contract_document raw_text INSERT/UPDATE
→ change_log INSERT
→ worker 감지
→ 재청킹 / 재임베딩
```

같은 흐름을 구성할 수 있다.

---

## 15.3 `schema_meta`

현재 DB 스키마 버전을 관리한다.

예:

```text
version = D-27
applied_at = ...
```

운영 환경에서 어떤 스키마 버전이 적용되어 있는지 확인하는 용도다.

---

# 16. 서비스 전체 플로우

상세 실행 규약은 [`contract-registration-flow.md`](contract-registration-flow.md)를 따른다.

## 16.1 1단계: 기존 IP 선택

사용자는 미리 등록된 `ip`를 선택한다. 신규 작품이면 실제 등록 트랜잭션에서 `ip`를 먼저 생성한다. `ip`는 관리 대상 작품이지 법적 소유자를 나타내는 테이블이 아니다.

## 16.2 2단계: PDF 임시 업로드

최초 PDF는 오브젝트 스토리지에만 올리고 `storage_key`, 파일명, 해시를 애플리케이션 작업 데이터로 유지한다. 이 시점에는 `contract`와 `contract_document`를 INSERT하지 않으므로 실제 `contract_id`와 `document_id`가 없다.

## 16.3 3단계: OCR·AI 추출과 사용자 확인

OCR·AI가 정규화 후보와 `evidence[]`를 만들고 사용자가 값과 원문 인용을 확인·수정한다.

```text
candidate
├─ territory / legal_right / exploitation_mode
├─ period / exclusivity / confidence
└─ evidence N건
   ├─ page_start / page_end
   ├─ source_clause
   └─ source_quote
```

등록 전 산출물은 아직 업무 테이블에 커밋하지 않는다.

## 16.4 4단계: 롤백 검증

`probe_rights()`는 후보와 evidence JSON 배열을 받아 검증용 부모·후보·근거·판정 행을 서브트랜잭션에 INSERT한다. 마지막에는 `rights_grant` INSERT까지 실제로 시도해 EXCLUDE와 statement trigger를 확인한다.

```text
contract
→ contract_document
→ rights_grant_candidate
→ candidate_evidence N건
→ rights_evaluation / reason
→ rights_grant INSERT 시도
→ 결과 수집
→ 전체 롤백
```

화면에는 `NORMAL`, `WARNING`, `REVIEW_REQUIRED`, `CONFLICT`와 사유·겹침 기간·실제 제약명을 반환하지만 DB에는 검증용 행을 남기지 않는다.

## 16.5 5단계: 결과별 사용자 결정

```text
NORMAL          → 등록 가능
WARNING         → 경고 확인 후 등록 가능
REVIEW_REQUIRED → 값 또는 근거 수정 후 재검증
CONFLICT        → AMENDED / WAIVER / REJECTED
```

검증 결과만 확인한 시점에는 어떤 경우도 업무 테이블에 커밋되지 않는다.

## 16.6 6단계: 실제 등록

사용자가 등록을 확정하면 한 트랜잭션에서 실제 ID를 순서대로 받는다.

```text
contract INSERT RETURNING id
→ contract_document INSERT RETURNING id
→ candidate INSERT RETURNING id
→ candidate_evidence N건 INSERT
→ evaluate_candidate()
→ blocking 사유가 없는 후보만 register_candidate()
→ COMMIT
```

정상 후보는 `rights_grant`로 승격한다. 충돌 후보는 grant로 만들지 않고 candidate·evaluation·reason을 보존해 후속 AMENDED·WAIVER·REJECTED 처리를 이어간다. 예상하지 못한 DB 제약 위반이나 시스템 오류가 발생하면 트랜잭션 전체를 롤백한다.

## 16.7 7단계: 계약 최종화

모든 후보가 `approved` 또는 `rejected`로 결론나고 최종 문서가 준비되면 문서와 grant 상태를 전환하고 `contract.final_document_id`를 지정한 뒤 `contract.status = final`로 바꾼다.

이미 존재하는 계약에 수정 PDF를 올리는 경우에는 새 `contract_document.version`을 생성한다. 수정 문서의 후보와 evidence는 반드시 새 `document_id`에 연결해 이전 버전의 근거와 섞이지 않게 한다.

---

# 17. UI에서 보여줄 판정 결과 예시

```text
판정 결과
━━━━━━━━━━━━━━━━
CONFLICT

주요 사유
기존 독점 권리와 중복됩니다.

충돌 상대
Contract #17 / Grant #31

권리
TRANSMISSION / SVOD

지역
JP

겹치는 기간
2027.01.01 ~ 2028.01.01

AI 설명
기존 계약에서 동일 작품의 일본 SVOD 독점권이
2028년까지 유효합니다.
```

검증 직후에는 `probe_rights()` 반환값으로 이 화면을 만든다. 실제 등록 단계에서 충돌 처리 대상으로 커밋된 건은 다음 테이블을 조인해 다시 조회할 수 있다.

```text
rights_evaluation
+
rights_evaluation_reason
+
rights_grant
```

---

# 18. 사용자 의사결정

판정 결과를 본 사용자는 다음처럼 처리할 수 있다. 등록 여부는 최신 evaluation의 `detected` 사유 중 `reason_code.is_blocking = true`가 있는지를 기준으로 한다.

```text
NORMAL
→ 승인

WARNING
→ 경고 확인 후 승인 가능

REVIEW_REQUIRED
→ 필드 보완 또는 수동 검토 후 재판정 / 거절

CONFLICT
→ AMENDED
→ WAIVER
→ REJECTED
```

AMENDED 또는 WAIVER가 처리되면 candidate를 다시 평가한다. REJECTED는 신규 candidate를 종료하며 기존 grant를 변경하지 않는다.

검증 단계의 판정 행은 롤백되므로, 장기 후속 처리가 필요한 충돌은 실제 등록 트랜잭션에서 candidate·evaluation·reason을 다시 생성해 보존한다.

---

# 19. 사용자 확인만으로 grant가 되는 것은 아님

사용자가 추출값을 확인했더라도 실제 등록 트랜잭션에서 `register_candidate()`가 `rights_grant INSERT`를 수행해야 한다.

```text
INSERT INTO rights_grant ...
```

이 시점에 DB의 EXCLUDE constraint와 trigger가 다시 최종 검사를 한다.

---

# 20. 왜 사전 판정과 INSERT 검사를 둘 다 하는가

이유는 동시성이다.

예:

```text
11:00:00
사용자 A 사전 판정
→ 충돌 없음

11:00:01
사용자 B가 같은 권리 먼저 저장

11:00:03
사용자 A 저장
```

A의 사전 판정 시점에는 문제가 없었지만 저장 시점에는 이미 B의 권리가 존재한다.

따라서 사전 판정만 믿으면 race condition 때문에 중복 권리가 생길 수 있다.

역할은 다음처럼 나뉜다.

```text
evaluate_candidate()
= 사용자에게 저장 전에 보여주는 사전 판정

EXCLUDE / trigger
= 실제 INSERT 순간의 최종 무결성 방어
```

둘은 중복 구현이 아니라 목적이 다르다.

---

# 21. 최종 권리 등록

등록 시 `contract`, `contract_document`, `rights_grant_candidate`, `candidate_evidence` 순서로 INSERT해 실제 ID를 받고 평가한다. DB의 최종 제약까지 통과한 후보만 `rights_grant`가 생성된다.

```text
rights_grant
status = approved
```

이 시점부터 해당 권리는 다음 candidate들의 충돌 검사 대상이 된다.

등록과 상태 변경은 trigger가 `rights_grant_history`에 자동 기록한다.

계약 최종 확정 과정에서는 애플리케이션이 해당 계약에 포함된 grant 상태도 `final`로 전환한다. 이 상태 변경 역시 history에 `finalized` 이벤트로 기록된다. contract 최종화 검증 trigger가 grant 상태를 대신 변경하지는 않는다.

---

# 22. 계약 최종화

모든 candidate 처리가 끝나고 최종 문서와 권리 등록이 완료되면

```text
contract.status = final
```

로 전환한다.

`contract.status = final`은 계약 업무 전체의 확정이고, `contract_document.status = final`은 여러 PDF 중 실제 체결본 표시다. 서로 의미가 다르므로 DB가 자동 동기화하지 않는다.

이때 확인할 수 있는 조건은 다음과 같다.

```text
final_document_id 존재 여부
final document가 해당 contract 소속인지
document 상태가 approved/final인지
미처리 candidate(`extracted`/`review`)가 남아 있는지
```

권리 충돌 자체는 contract final 단계에서 다시 계산하지 않아도 된다.

이미 `rights_grant INSERT` 시점에서 DB 제약을 통과했기 때문이다.

즉 역할은 다음처럼 분리된다.

```text
권리 생성 시
→ 권리 무결성 검사

계약 final 시
→ 계약 완결성 검사
```

---

# 23. 전체 서비스 플로우 다이어그램

```text
사용자
  │
  ▼
기존 IP 선택
  │
  ▼
PDF 임시 업로드
오브젝트 스토리지
  │
  ▼
OCR / AI 추출
candidate + evidence[] 작업 데이터
  │
  ▼
사용자 확인·수정
  │
  ▼
probe_rights()
검증용 행 INSERT + 실제 제약 확인
  │
  ▼
검증용 행 전체 롤백
  │
  ├──────── NORMAL / WARNING ────────┐
  │                                  │
  ├──────── REVIEW_REQUIRED          │
  │          └─ 수정 후 재검증       │
  │                                  │
  └──────── CONFLICT                 │
             ├─ AMENDED → 재검증     │
             ├─ REJECTED             │
             └─ WAIVER 처리          │
                                     ▼
                            실제 등록 트랜잭션
                                     │
                  contract → contract_document
                                     │
                  candidate → candidate_evidence N건
                                     │
                         evaluate_candidate()
                                     │
                    ┌────────────────┴──────────────┐
                    ▼                               ▼
          blocking 사유 없음                 blocking 사유 있음
                    │                               │
          register_candidate()             처리 대상으로 보존
                    │                    AMENDED / WAIVER / REJECTED
                    ▼
             rights_grant
                    │
        EXCLUDE + statement trigger
                    │
                    ▼
       rights_grant_history 자동 기록
                    │
                    ▼
              contract final
```

---

# 24. 구조를 4계층으로 압축하면

## 1) 원본 계층

```text
contract
contract_document
contract_chunk
```

계약 업무와 원본 문서를 관리한다.

## 2) 추출 계층

```text
rights_grant_candidate
```

AI가 계약서에서 읽어낸 미확정 데이터를 관리한다.

## 3) 판정 계층

```text
rights_evaluation
rights_evaluation_reason
conflict_resolution
```

DB가 판단하고 사용자가 의사결정하는 영역이다.

## 4) 확정 계층

```text
rights_grant
rights_grant_history
```

최종적으로 시스템이 사실로 인정하는 권리 데이터를 관리한다.

---

# 25. 핵심 구조: Candidate → Evaluation → Grant

이 DB 구조를 가장 간단하게 이해하면 다음과 같다.

```text
candidate
"계약서에서 이렇게 읽혔습니다."

        ↓

evaluation
"기존 확정 권리와 비교하면 이런 판정입니다."

        ↓

grant
"사람이 확인했고 DB 최종 제약까지 통과했으므로
실제 권리로 인정합니다."
```

---

# 26. 권리 충돌 판정의 핵심

신규 권리 하나는 대략 다음 6개 축으로 표현된다.

```text
작품
지역
법적 권리
이용형태
기간
독점성
```

기존 권리와 비교할 때는 다음 순서로 보면 이해하기 쉽다.

```text
같은 작품인가?
        ↓
같은 지역인가?
        ↓
법적 권리 범위가 겹치는가?
        ↓
이용형태 범위가 겹치는가?
        ↓
기간이 겹치는가?
        ↓
독점성 정책상 동시에 존재 가능한가?
```

필요한 충돌 조건이 모두 충족되면 충돌로 판단한다.

---

# 27. 설계의 핵심 철학

이 구조의 가장 중요한 부분은 **AI 판단, DB 판정, 사용자 의사결정을 분리했다는 것**이다.

```text
AI
→ 계약서에서 정보 추출
→ 판정 결과 설명

DB
→ 구조적 관계 계산
→ 기존 권리와 충돌 판정
→ 최종 무결성 보장

사용자
→ 승인
→ 수정
→ WAIVER
→ 거절
```

AI가 최종 권리 충돌 여부를 결정하는 구조가 아니다.

최종 권리는 반드시 DB의 constraint와 trigger까지 통과해야 한다.

---

# 28. 최종 관계 요약

```text
contract
  │
  ├──── contract_document
  │          ├──── contract_chunk
  │          └──── rights_grant_candidate ──── ip
  │                        ├──── candidate_evidence
  │                        └──── rights_evaluation
  │                                  │
  │                                  └──── rights_evaluation_reason
  │                                               └──── conflict_resolution
  │
  └──── rights_grant ──── ip
               │
               └──── rights_grant_history


legal_right ───────────────┐
                           ├── candidate / grant 판정축
exploitation_mode ─────────┘

country ───────────────────── territory 기준

reason_code ───────────────── 판정/검토 사유 기준
```

---

# 29. 가장 헷갈리기 쉬운 기준정보 4개 정리

```text
legal_right
= 법적으로 무엇을 할 수 있는 권리인가

exploitation_mode
= 그 권리를 사업적으로 어떤 방식으로 이용하는가

statutory_right
= 각 국가 법에서는 그 권리를 어떤 법정 명칭으로 부르는가

right_mapping
= 특정 국가에서 legal_right + exploitation_mode 조합이 일반적으로 자연스러운지 참고하는 기준
```

---

# 30. 한 문장 정리

이 DB는

> **계약서 원문에서 AI가 권리 후보를 추출하고, DB가 기존 확정 권리와의 충돌을 판정한 뒤, 사용자의 검토와 최종 DB 제약을 통과한 데이터만 실제 권리로 확정하는 구조**

라고 보면 된다.

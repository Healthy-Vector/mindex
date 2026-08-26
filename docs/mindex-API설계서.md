# Mindex API 설계서 v1.2

화면설계서 · 화면 프로세스 문서 · 데이터 파이프라인 설계와 PostgreSQL 17의 P2-DB 계약을 기준으로 작성했습니다.
도메인 테이블은 `public`, 임시 추출 데이터는 `staging` 스키마를 사용합니다. DB 구조는 P2-DB의 `sql/init/*.sql`을 정본으로 봅니다.

---

## 공통 규약

**Base URL** `/api`

**인증** — 계약 상세처럼 민감 정보를 다루는 엔드포인트는 PIN 세션이 필요합니다.
세션 토큰은 `Authorization: Bearer {sessionToken}` 헤더로 보냅니다. 목록·검색·IP 관리는 세션 없이 조회 가능합니다.

**공통 에러 응답**

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "period 형식이 올바르지 않습니다",
    "details": { "field": "rights[0].period" }
  }
}
```

**상태 코드**

|코드|쓰는 경우|
|---|---|
|`200`|조회·처리 성공|
|`201`|생성 성공 (계약 확정, IP 등록)|
|`202`|접수 완료, 처리는 비동기로 진행 (업로드)|
|`400`|요청 형식 오류|
|`401`|PIN 세션 없음 또는 만료|
|`404`|대상 없음|
|`409`|중복 확정 (`source_tmpid` 재사용)|
|`422`|처리 가능하나 업무 규칙 위반|

**충돌은 에러가 아닙니다.** 권리 충돌이 발생해도 `200`/`201`로 응답하고 본문에 충돌 내역을 담습니다. HTTP 오류로 주면 프론트가 "요청이 실패한 건지, 충돌이 난 건지" 구분하지 못합니다.

**상태값 어휘**

|테이블|컬럼|값|
|---|---|---|
|`contract`|`status`|`draft` / `signed` / `cancelled`|
|`contract_history`|`document_kind`|`draft` / `final`|
|`contract_history`|`status`|`applied` / `conflicted`|
|`rights_grant`|`status`|`active` / `terminated`|
|`staging.extract_job`|`status`|`QUEUED` / `RUNNING` / `DONE` / `FAILED`|

---

## API 목록

|#|메서드|경로|이름|담당|프로세스 위치|사용 화면|
|---|---|---|---|---|---|---|
|1|POST|`/auth/pin`|PIN 인증|P4|Ⓑ PIN 인증|계약 상세 진입 시|
|2|POST|`/extract`|업로드 접수|**P1**|① 업로드 접수|`/upload`|
|3|GET|`/extract/{tmpid}`|추출 상태·결과 조회|**P1**|② 추출(비동기)|`/upload`|
|4|GET|`/ips/match`|IP 매칭 후보|P4|③ 결과 확인·수정|`/upload` IP 매칭 패널|
|5|POST|`/contracts/verify`|충돌 검증|P4|④ 검증|`/upload` 충돌검사 실행|
|6|POST|`/contracts`|계약 확정 저장|P4|⑥ 확정 저장|`/upload/conflict` 저장 버튼|
|7|GET|`/contracts`|계약 목록|P4|Ⓐ 진입|`/` 계약 목록|
|8|GET|`/contracts/{id}`|계약 상세|P4|Ⓒ 계약서 상세|`/contracts/:id`|
|9|GET|`/contracts/{id}/file`|원본 PDF 조회|P4|Ⓓ 원문·이력|`/contracts/:id` 미리보기|
|10|GET|`/rights/{lineageId}/history`|권리 이력|P4|Ⓓ 원문·이력|`/contracts/:id` 권리 카드|
|11|POST|`/contracts/{id}/cancel`|계약 종료|P4|상태 변경|계약 상세 종료 버튼|
|12|GET|`/ips`|IP 목록|P4|㉮ IP 목록 조회|`/ips` UI-D-001|
|17|GET|`/ips/{id}`|IP 상세 조회|P4|㉯ IP 상세 조회|`/ips` 상세 패널|
|13|POST|`/ips`|IP 등록|P4|㉰ IP 신규 등록|UI-D-002 · 업로드 중 등록|
|14|PATCH|`/ips/{id}`|IP 수정·활성화|P4|㉯ IP 상세·수정|`/ips` 상세 패널|
|18|POST·PATCH·DELETE|`/ips/{id}/assets[/{assetId}]`|권리 대상 관리|P4|㉯ IP 상세·수정|`/ips` 상세 패널|
|15|POST|`/search`|통합 검색|P4|Ⓐ 진입|`/search`|
|16|GET|`/refs`|참조 코드 목록|P4|전 구간|드롭다운·필터|

**흐름 세 갈래**

|흐름|순서|API|
|---|---|---|
|**계약서 등록** ①~⑥|있음|2 → 3(폴링) → 4 → 5 → 6|
|**계약서 열람** Ⓐ~Ⓓ|있음|7·15 → 1 → 8 → 9·10|
|**IP 관리** ㉮~㉰|없음|12 / 17·14·18 / 13|

**상태를 바꾸는 동작** — 11(계약 종료), 그리고 계약 상세의 "버전·최종 계약 등록" 버튼(2번으로 등록 흐름 재진입). 열람 중 계약 상세에서 갈라져 나갑니다.

---

## 1. PIN 인증 — `POST /auth/pin`

### API 역할 및 사용되는 프로세스 위치

계약 상세 화면은 계약 금액·당사자·근거 원문을 그대로 노출하므로 팀 PIN으로 한 번 잠급니다.
개인 로그인이 아니라 **팀이 공유하는 열람 세션**입니다. 인증에 성공하면 유효시간이 있는 세션 토큰을 발급하고, 화면 우측 상단에 남은 시간을 표시합니다.

열람 흐름의 **Ⓑ 단계**입니다. Ⓐ 목록·검색은 세션 없이 볼 수 있고, Ⓒ 상세부터 세션이 필요합니다.

### payload

|필드|타입|필수|설명|
|---|---|---|---|
|`pin`|string|O|4자리 숫자. `team.pin_hash` 와 bcrypt로 대조|

```json
{ "pin": "1234" }
```

### response

|필드|타입|설명|
|---|---|---|
|`sessionToken`|string|이후 요청의 `Authorization` 헤더에 사용|
|`expiresAt`|string(ISO8601)|만료 시각. 화면 카운트다운의 기준|
|`ttlSeconds`|int|남은 초. 기본 900(15분)|

```json
{
  "sessionToken": "eyJhbGciOi...",
  "expiresAt": "2026-08-22T15:45:00+09:00",
  "ttlSeconds": 900
}
```

PIN이 틀리면 `401` 과 `{"error":{"code":"INVALID_PIN"}}`. 보호 API 8·9·10·11 호출 시 요청 시각+15분으로 연장하며, 재발급은 세션당 1분에 한 번으로 제한합니다. 새 토큰과 만료 시각은 `X-Session-Token`·`X-Session-Expires` 응답 헤더로 보냅니다.

---

## 2. 업로드 접수 — `POST /extract`

### API 역할 및 사용되는 프로세스 위치

**① 업로드 접수 단계. P1 담당.**

PDF를 `staging.pdf_blob` 에 넣고 `staging.extract_job` 에 대기 작업을 하나 등록합니다. **두 INSERT가 한 트랜잭션**이라 "파일은 저장됐는데 큐에 안 들어간" 상태가 생기지 않습니다. 커밋이 끝나야 응답합니다.

OCR·LLM 추출은 건당 50~60초가 걸리므로 이 API는 기다리지 않습니다. `202` 로 `tmpid` 만 즉시 돌려주고, 실제 처리는 쿠버네티스 워커 파드가 뒤에서 가져갑니다.

프론트는 응답을 받는 즉시 주소창을 `/upload/{tmpid}` 로 바꿔야 합니다. 새로고침해도 돌아올 수 있게 하는 가장 싼 방법입니다.

### payload

`multipart/form-data`

|필드|타입|필수|설명|
|---|---|---|---|
|`file`|binary|O|PDF. 최대 100MB. 스캔본 권장 상한은 20MB|
|`mode`|enum|O|`draft` / `final`. 문서 종류만 나타냅니다|
|`contractId`|int·null|X|기존 계약의 새 버전이면 그 id. 신규 계약이면 생략|
|`ipId`|int·null|X|아는 경우에만. 신규 작품이면 생략(추출 후 후보에서 고릅니다)|

**세 값은 `staging.extract_job`에 저장됩니다(D-37).** 화면 상태 없이 `tmpId`만으로
들어와도(목록의 "처리 중" 항목 클릭, 브라우저 재접속) 맥락이 복원됩니다. 5·6번에서
`contractId`·`ipId`·`documentKind`를 생략하면 여기 저장된 값이 쓰입니다.

`mode`는 **문서가 초안인지 최종본인지**만 나타냅니다. "신규냐 개정이냐"는
`contractId`의 유무가 말해주므로 `mode`에 섞지 않습니다.

|`mode`|`contractId`|의미|후속 처리|
|---|---|---|---|
|`draft`|없음|신규 계약의 초안|`contract` 를 새로 만들고 `status='draft'`|
|`draft`|있음|기존 계약의 새 초안|같은 `contract` 에 `contract_history` 추가, `version = v(n+1)`|
|`final`|없음|**신규 계약의 서명본**|`contract` 를 새로 만들고, 충돌이 없으면 `status='signed'`|
|`final`|있음|기존 계약의 서명본|충돌이 없으면 `contract.status='signed'`|

마지막에서 두 번째 줄이 D-37로 새로 가능해진 경로입니다. 예전 3값 체계
(`new`/`revision`/`final`)에서는 `final`이 기존 계약을 전제해서, 이미 서명된
계약서를 처음 등록할 때도 초안으로 한 번 올린 뒤 다시 올려야 했습니다.

### response

`202 Accepted`

|필드|타입|설명|
|---|---|---|
|`tmpid`|uuid|추출 작업 식별자. 이후 모든 단계에서 사용|
|`status`|enum|접수 직후이므로 항상 `QUEUED`|
|`filename`|string|저장된 원본 파일명|
|`byteSize`|int|바이트 크기|

```json
{
  "tmpid": "0a7c3f2e-9b41-4d55-8c10-2f4b7e1d9a33",
  "status": "QUEUED",
  "filename": "겨울의신호_이용허락계약서_v2.pdf",
  "byteSize": 4823910
}
```

---

## 3. 추출 상태·결과 조회 — `GET /extract/{tmpid}`

### API 역할 및 사용되는 프로세스 위치

**② 추출(비동기) 단계. P1 담당.**

프론트가 주기적으로 호출해 진행 상태를 확인합니다. 완료되면 이 응답에 추출 결과가 함께 실려 옵니다.

**브라우저를 닫아도 워커는 계속 돕니다.** 나중에 같은 `tmpid` 로 다시 들어오면 결과를 그대로 받습니다. 폴링이 몇 번 실패해도 에러 화면으로 넘기지 말고 간격을 늘려가며(2s → 4s → 8s → 최대 30s) 계속 재시도해야 합니다.

**실패도 `200` 으로 줍니다.** 조회 요청 자체는 성공했기 때문입니다. `5xx` 로 주면 프론트가 조회 실패와 처리 실패를 구분하지 못합니다.

### payload

없음. 경로 파라미터만 사용합니다.

|파라미터|타입|설명|
|---|---|---|
|`tmpid`|uuid|접수 시 받은 값|

### response

|필드|타입|설명|
|---|---|---|
|`tmpid`|uuid||
|`status`|enum|`QUEUED` / `RUNNING` / `DONE` / `FAILED`|
|`stage`|enum·null|`RUNNING` 일 때만. `OCR` / `LLM`|
|`queuePosition`|int·null|`QUEUED` 일 때 앞에 몇 건 있는지|
|`reason`|string·null|`FAILED` 일 때 사유 코드|
|`mode`|enum·null|업로드 시 받은 `draft` / `final` (D-37)|
|`contractId`|int·null|업로드 시 받은 값. 없으면 신규 계약|
|`ipId`|int·null|업로드 시 받은 값. 없으면 추출 후 후보에서 고름|
|`result`|object·null|`DONE` 일 때만 채워짐|

`mode`·`contractId`·`ipId`는 **업로드 시점에 저장해 둔 맥락**입니다(D-37). 화면이
아무 상태도 안 들고 있어도(목록의 "처리 중" 항목에서 진입, 브라우저 재접속) 이
값으로 이어서 진행할 수 있습니다. 5·6번에 다시 보내지 않아도 서버가 같은 값을 씁니다.

**화면 상태 매핑**

|status / stage|화면 표시|
|---|---|
|`QUEUED`|대기 중 (앞에 N건)|
|`RUNNING` / `OCR`|문자 인식 중|
|`RUNNING` / `LLM`|조건 추출 중|
|`DONE`|검증 표 렌더|
|`FAILED`|사유 + 다시 시도 버튼|

**처리 중**

```json
{ "tmpid": "0a7c...", "status": "RUNNING", "stage": "LLM", "result": null }
```

**완료**

```json
{
  "tmpid": "0a7c...",
  "status": "DONE",
  "stage": null,
  "result": {
    "contractInfo": {
      "title": "겨울의 신호 영상 및 OST 이용허락계약서",
      "grantor": "해솔미디어 주식회사",
      "grantee": "웨이브플랫폼 주식회사",
      "signedDate": "2027-03-01",
      "lang": "ko",
      "amount": 300000,
      "currency": "USD"
    },
    "ipCandidates": [
      { "ipId": 12, "title": "겨울의 신호", "score": 0.94, "matchedBy": "alias" }
    ],
    "rights": [
      {
        "seq": 1,
        "contentAsset": { "scopeType": "SERIES_ALL", "title": "겨울의 신호 · 시리즈" },
        "territories": ["JP", "SG"],
        "legalRight": "TRANSMISSION",
        "exploitationMode": "SVOD",
        "period": { "start": "2027-07-01", "end": "2029-06-30" },
        "exclusivity": "exclusive",
        "conditionsRaw": { "sublicense": "AFFILIATE_ONLY" },
        "evidence": {
          "legal_right": { "quote": "제8조 제1항 ..." },
          "exploitation_mode": { "quote": "구독형 VOD로 ..." },
          "territory": { "quote": "일본 및 싱가포르에서 ..." },
          "period": { "quote": "2027년 7월 1일부터 2029년 6월 30일까지 ..." },
          "exclusivity": { "quote": "독점적으로 ..." }
        }
      }
    ],
    "rawText": "제1조 (목적) ...",
    "confidence": 0.918
  }
}
```

**결과 구조 설명**

|필드|설명|
|---|---|
|`ipCandidates`|OCR로 읽은 작품명을 등록 IP와 대조한 후보. `mode=new` 일 때만 화면에 매칭 패널로 표시|
|`rights[].contentAsset`|작품 **내부 범위**만 담습니다 — 시리즈 전체 / 시즌 / 에피소드 / 감독판. OST·리메이크는 별도 IP이므로 그 IP의 `content_asset` 으로 잡힙니다|
|`rights[].territories`|지역 그룹(`APAC` 등)은 이미 국가 단위로 펼쳐진 상태로 옵니다. 저장 시 국가마다 `rights_grant` 한 행|
|`rights[].legalRight` / `exploitationMode`|법적 권리와 사업적 이용형태의 2축 분류. 두 값을 모두 확정 저장 요청에 보냄|
|`rights[].evidence`|`legal_right`·`exploitation_mode`·`territory`·`period`·`exclusivity`별 근거 객체. 각 항목의 비어 있지 않은 `quote`가 필수|
|`rights[].conditionsRaw`|Reserved·Carve-out·Holdback·Sublicense 원문. **판정에는 쓰지 않고 화면 표시용**|
|`confidence`|전체 추출 신뢰도. 필드별 신뢰도는 `evidence` 안에|

**실패**

```json
{ "tmpid": "0a7c...", "status": "FAILED", "reason": "OCR_TIMEOUT", "result": null }
```

|`reason`|의미|
|---|---|
|`OCR_TIMEOUT`|문자 인식이 제한 시간을 넘김|
|`LLM_TIMEOUT`|조건 추출이 제한 시간을 넘김|
|`UNREADABLE_PDF`|암호화되었거나 손상된 파일|
|`MAX_ATTEMPTS`|재시도 한도 초과|

---

## 4. IP 매칭 후보 — `GET /ips/match`

### API 역할 및 사용되는 프로세스 위치

**③ 결과 확인·수정 단계.**

업로드 화면의 IP 매칭 패널에서 씁니다. OCR이 추출한 콘텐츠 제목으로 활성 IP의 `ip.title` 과 `ip_alias` 를 검색하고, IP 선택 직후 필요한 작품 내부 범위까지 함께 반환합니다. `pg_trgm` 문자열·단어 유사도와 양방향 부분 일치 점수를 조합하므로 `겨울왕국 시즌2`로 `겨울왕국`을 찾을 수 있습니다.

`ip_relation` 은 현재 P2-DB에 구현되지 않았습니다. 응답 형식은 유지하지만 `relations` 는 항상 빈 배열입니다.

### payload

쿼리 파라미터

|파라미터|타입|필수|설명|
|---|---|---|---|
|`q`|string|O|OCR 추출 제목 또는 검색어. 1자 이상|
|`limit`|int|X|기본 10, 최대 100|
|`includeInactive`|bool|X|기본 false|

### 사용 예시

OCR 결과의 콘텐츠 제목을 가공하지 않고 `q`에 넣습니다.

```http
GET /api/ips/match?q=겨울왕국%20시즌2&limit=10&includeInactive=false
```

검색 결과는 `score` 내림차순이며, 같은 점수에서는 대표명(`title`) 일치가 별칭(`alias`) 일치보다 먼저 나옵니다. `score`는 문자열 관련도 지표이며 계약 판정의 신뢰도가 아닙니다. 0.4 미만인 후보는 반환하지 않고, 비활성 IP까지 찾아야 할 때만 `includeInactive=true`를 사용합니다.

### response

|필드|타입|설명|
|---|---|---|
|`matches[].ipId`|int||
|`matches[].title`|string|대표명|
|`matches[].kind`|string·null|IP 유형|
|`matches[].matchedOn`|enum|`title` / `alias`|
|`matches[].matchedText`|string·null|최고 점수를 만든 대표명 또는 별칭|
|`matches[].score`|number·null|0~1 관련도. 높은 순서로 반환|
|`matches[].assets`|array|이 IP의 작품 내부 범위 목록|
|`matches[].relations`|array|현재는 항상 빈 배열|

```json
{
  "matches": [
    {
      "ipId": 12,
      "title": "겨울의 신호",
      "kind": "DRAMA",
      "matchedOn": "alias",
      "matchedText": "겨울 신호",
      "score": 0.94,
      "assets": [
        { "contentAssetId": 30, "scopeType": "SERIES_ALL", "title": "시리즈 전체" },
        { "contentAssetId": 31, "scopeType": "SEASON", "seasonNo": 2, "title": "시즌 2" }
      ],
      "relations": []
    }
  ]
}
```

`assets` 를 함께 내려주는 이유는 IP를 고른 직후 권리 대상까지 바로 선택해야 하기 때문입니다. OST·리메이크는 별도 IP로 등록하는 방향이지만 관계 연결은 `ip_relation`이 추가된 뒤 확장합니다.
---

## 5. 충돌 검증 — `POST /contracts/verify`

### API 역할 및 사용되는 프로세스 위치

**④ 검증 단계.**

사용자가 값을 다 확인한 뒤 "충돌검사 실행"을 누르면 호출됩니다. `public.validate_rights_batch()`가 실제 저장과 같은 INSERT·제약 경로로 판정한 뒤 내부 서브트랜잭션을 항상 되돌립니다. Python에서 별도의 충돌 알고리즘을 만들지 않습니다.

**호출 방식이 두 가지입니다(D-34).**

| 경로 | 보내는 것 | 서버가 하는 일 |
|---|---|---|
| **staging 경로** (업로드에서 이어지는 정상 흐름) | `tmpId` + `patch` + 화면이 확정하는 값(`ipId`/`contractId`) | 사용자가 고친 값을 `staging.extract_result.payload.edited`에 **먼저 반영·커밋**한 뒤, **저장된 값으로** 판정합니다. `rights`·`grantor`·`grantee`·`fileName`·`filePath`·`fileHash`는 서버가 채우므로 보내지 않습니다 |
| **직접 경로** (수기 등록·테스트) | 종전대로 전체 body | 요청 값 그대로 판정합니다 |

`patch`는 3번 응답의 `result`와 같은 shape에 대한 **JSON Merge Patch(RFC 7386)** 입니다. 사용자가 고친 필드만 보내면 됩니다.

- `null`을 보내면 그 키를 지웁니다.
- **배열은 원소 단위로 병합되지 않고 통째로 교체됩니다.** `rights`를 고칠 때는 전체 목록을 보내세요.
- 재검증하면 이전 수정본 위에 누적됩니다. `GET /extract/{tmpid}`도 이후로는 수정본을 돌려줍니다.
- `rights`를 top-level로 보내도 됩니다 — `patch`의 배열 전체 교체와 같게 처리되어 staging에 반영됩니다. 그래야 확정이 검증과 같은 값을 저장합니다.
- `contractInfo`의 `title`·`signedDate`·`amount`·`currency`·`lang`·`grantor`·`grantee`도 patch로 고칠 수 있고, 확정 시 `public.contract` 행에 저장됩니다(D-36).

판정 결과는 롤백되지만 **수정본은 남습니다.** 그래서 확정(6번)에서 같은 값을 다시 보낼 필요가 없습니다.

권리 한 행은 다음 원자 단위로 판정합니다.

```text
content_asset_id × territory × legal_right span × exploitation_mode span × period
```

`legal_right`는 법적 권리, `exploitation_mode`는 사업적 이용형태입니다. 두 taxonomy의 상·하위 포함관계까지 nested-set span으로 검사합니다.

### payload

|필드|타입|필수|설명|
|---|---|---|---|
|`contractId`|int·null|X|개정판이면 기존 계약 id. **staging 경로에서는 생략 가능** — 업로드 시 받은 값이 쓰입니다(D-37)|
|`grantor`|string·null|△|권리를 주는 쪽. **staging 경로에서는 생략 가능** — 추출 결과의 `parties[]`에서 서버가 뽑습니다(D-36). 보내면 그 값이 우선|
|`grantee`|string·null|△|권리를 받는 쪽. 위와 동일|
|`ipId`|int·null|X|확정된 IP. 신규 작품이면 null 가능. **staging 경로에서는 생략 시 업로드 시 받은 값**|
|`tmpId`|uuid·null|X|추출 작업 id. 있으면 staging 경로|
|`patch`|object·null|X|화면 DTO 부분수정(RFC 7386). `tmpId`와 함께만 씁니다|
|`fileName`|string·null|△|직접 경로에서만 필수|
|`filePath`|string·null|△|직접 경로에서만 필수. **staging 경로에서는 무시됩니다** — 저장 경로는 서버가 정합니다(D-34b)|
|`fileHash`|string·null|△|직접 경로에서만 필수. staging 경로에서는 서버가 원본에서 계산합니다|
|`mimeType`|string·null|X||
|`rawText`|string·null|X|추출 원문|
|`documentKind`|enum·null|X|`draft` / `final`. 생략하면 업로드 시 받은 `mode`, 그것도 없으면 draft (D-37)|
|`rights`|array·null|△|직접 경로에서만 필수. staging 경로에서는 저장된 수정본에서 읽습니다|

`rights[]` 원소

|필드|타입|필수|설명|
|---|---|---|---|
|`contentAssetId`|int·null|X|생략 시 해당 IP의 기본 asset 사용|
|`legalRight`|string|O|`legal_right.code`|
|`exploitationMode`|string|O|`exploitation_mode.code`|
|`territories`|string[]|O|국가 또는 지역 그룹. 한 건 이상|
|`period.start` / `period.end`|date|O|종료일 포함. DB에는 `[start,end+1day)`로 저장|
|`exclusivity`|enum|O|`exclusive` / `sole` / `non_exclusive`|
|`conditionsRaw`|object·null|X|원문 보존용. 판정에 사용하지 않음|
|`evidence`|object|O|5개 판정축별 근거 객체. 각 `quote` 필수|

```json
{
  "contractId": null,
  "grantor": "해솔미디어 주식회사",
  "grantee": "웨이브플랫폼 주식회사",
  "ipId": 12,
  "fileName": "contract.pdf",
  "filePath": "contracts/contract.pdf",
  "fileHash": "sha256:...",
  "documentKind": "draft",
  "rights": [
    {
      "contentAssetId": 30,
      "legalRight": "TRANSMISSION",
      "exploitationMode": "SVOD",
      "territories": ["JP", "SG"],
      "period": { "start": "2027-07-01", "end": "2029-06-30" },
      "exclusivity": "exclusive",
      "conditionsRaw": { "sublicense": "AFFILIATE_ONLY" },
      "evidence": {
        "legal_right": { "quote": "전송할 권리를 ..." },
        "exploitation_mode": { "quote": "구독형 VOD로 ..." },
        "territory": { "quote": "일본 및 싱가포르에서 ..." },
        "period": { "quote": "2027년 7월 1일부터 ..." },
        "exclusivity": { "quote": "독점적으로 ..." }
      }
    }
  ]
}
```

### response

`200 OK` — 충돌이 있어도 `200` 입니다.

|필드|타입|설명|
|---|---|---|
|`batchResult`|enum|`APPLIED` / `CONFLICTED`|
|`hasConflict`|bool|충돌 유무|
|`constraintName`|string·null|충돌을 판정한 DB 제약|
|`conflictReport`|object·null|P2 함수가 만든 JSON의 내용을 유지하고 내부 키를 camelCase로 변환|

```json
{
  "batchResult": "CONFLICTED",
  "hasConflict": true,
  "constraintName": "no_exclusive_overlap",
  "conflictReport": {
    "constraintName": "no_exclusive_overlap",
    "exceptionDetail": "...",
    "conflicts": [
      {
        "incoming": {
          "legalRight": "TRANSMISSION",
          "exploitationMode": "SVOD",
          "territory": "JP",
          "period": "[2027-07-01,2029-07-01)",
          "exclusivity": "exclusive"
        },
        "existingGrantId": 4512,
        "existingContractId": 87,
        "overlapPeriod": "[2027-07-01,2028-07-01)",
        "legalRightRelation": "same",
        "exploitationModeRelation": "same",
        "blockingLayer": "no_exclusive_overlap"
      }
    ]
  }
}
```

검증 전후 `rights_grant` 행 수는 같아야 합니다. 여기서 통과해도 확정 전에 다른 요청이 들어올 수 있으므로 6번 저장에서 같은 DB 경로로 다시 판정합니다.
---

## 6. 계약 확정 저장 — `POST /contracts`

### API 역할 및 사용되는 프로세스 위치

**⑥ 확정 저장 단계. 이 프로젝트에서 가장 중요한 엔드포인트입니다.**

`public.save_rights_batch()`가 계약 세대와 권리를 한 트랜잭션으로 처리합니다.

1. `tmpId`가 있으면 `staging.extract_job.status='DONE'`이고 대응하는 `extract_result`가 있는지 확인
2. 이미 `contract.source_tmpid`에 사용 중인 값인지 검사 — 재사용이면 `409 ALREADY_CONFIRMED`
3. 같은 계약의 동시 버전 등록은 contract 행을 `FOR UPDATE`로 잠금
4. 계약·계약 이력·문서 청크 저장 후 권리 배치 INSERT 시도
5. `201`로 종료되는 `APPLIED`·`CONFLICTED` 모두 같은 트랜잭션에서 **원본 PDF를 서버 저장소로 옮기고**(`staging.pdf_blob.data` → `{contract_id}/{history_id}.pdf`) `contract_history.file_path`·`file_hash`를 기록한 뒤 `staging.extract_job.consumed_at`을 기록
5. 적용이면 `contract_history.status='applied'`와 active grant를 함께 커밋
6. 충돌이면 grant INSERT 전체를 되돌리고 `contract_history.status='conflicted'`와 `conflict_report`만 커밋

**부분 승인은 발생하지 않습니다.** 배치 내부 한 행만 충돌해도 이번 요청의 grant는 0행입니다. 충돌은 트랜잭션 실패가 아니라 판정 결과이므로 APPLIED와 CONFLICTED 모두 `201`입니다.

### payload

5번 검증 API와 같은 필드에 선택 `chunks[]`가 추가됩니다.

**`tmpId`를 보내면 화면이 계약과 권리 전체를 다시 보낼 필요가 없습니다(D-34).** 서버가 `staging.extract_result.payload.edited`(검증 때 반영된 수정본, 없으면 워커 원본)를 읽어 저장 배치를 만듭니다. `evidence`·`conditionsRaw`처럼 화면이 들고 있지 않은 값도 서버가 채웁니다.

|필드|타입|필수|설명|
|---|---|---|---|
|`contractId` / `ipId`|-|-|5번과 동일|
|`grantor` / `grantee`|-|△|5번과 동일. staging 경로에서는 서버가 추출 결과에서 뽑습니다|
|`tmpId`|uuid·null|X|추출 작업 id이자 중복 확정 차단 키. 있으면 staging 경로|
|`fileName` / `filePath` / `fileHash`|-|△|5번과 동일. **staging 경로에서는 무시되고 서버가 채웁니다**|
|`mimeType` / `rawText`|-|-|5번과 동일|
|`documentKind`|enum·null|X|`draft` / `final`. 생략하면 업로드 시 받은 `mode`, 그것도 없으면 final (D-37)|
|`rights`|array·null|△|직접 경로에서만 필수. staging 경로에서는 저장된 수정본에서 읽습니다|
|`chunks`|array|X|검색용 문서 청크|

`chunks[]`

|필드|타입|필수|설명|
|---|---|---|---|
|`clauseNo`|string·null|X|조항 번호|
|`chunkText`|string|O|청크 본문|
|`lang`|string·null|X|원문 언어|
|`pageStart` / `pageEnd`|int·null|X|페이지 범위. 둘 다 있으면 pageEnd ≥ pageStart|
|`embedding`|number[]·null|X|벡터 임베딩|

```json
{
  "contractId": null,
  "grantor": "해솔미디어 주식회사",
  "grantee": "웨이브플랫폼 주식회사",
  "ipId": 12,
  "fileName": "contract.pdf",
  "filePath": "contracts/contract.pdf",
  "fileHash": "sha256:...",
  "documentKind": "final",
  "rights": [
    {
      "contentAssetId": 30,
      "legalRight": "TRANSMISSION",
      "exploitationMode": "SVOD",
      "territories": ["JP"],
      "period": { "start": "2027-07-01", "end": "2029-06-30" },
      "exclusivity": "exclusive",
      "evidence": {
        "legal_right": { "quote": "전송할 권리를 ..." },
        "exploitation_mode": { "quote": "구독형 VOD로 ..." },
        "territory": { "quote": "일본에서 ..." },
        "period": { "quote": "2027년 7월 1일부터 ..." },
        "exclusivity": { "quote": "독점적으로 ..." }
      }
    }
  ],
  "chunks": [
    {
      "clauseNo": "제8조",
      "chunkText": "전송할 권리를 독점적으로 ...",
      "lang": "ko",
      "pageStart": 12,
      "pageEnd": 13,
      "embedding": null
    }
  ],
  "tmpId": "0a7c3f2e-9b41-4d55-8c10-2f4b7e1d9a33"
}
```

### response

`201 Created`

|필드|타입|설명|
|---|---|---|
|`batchResult`|enum|`APPLIED` / `CONFLICTED`|
|`contractId`|int|생성되었거나 갱신된 계약|
|`contractHistoryId`|int|이번 업로드가 남긴 세대|
|`hasConflict`|bool|충돌 여부|
|`constraintName`|string·null|충돌 제약|
|`conflictReport`|object·null|P2 함수의 충돌 JSON. 내부 키는 camelCase로 반환|

**성공**

```json
{
  "batchResult": "APPLIED",
  "contractId": 101,
  "contractHistoryId": 344,
  "hasConflict": false,
  "constraintName": null,
  "conflictReport": null
}
```

**충돌**

```json
{
  "batchResult": "CONFLICTED",
  "contractId": 101,
  "contractHistoryId": 345,
  "hasConflict": true,
  "constraintName": "no_exclusive_overlap",
  "conflictReport": {
    "constraintName": "no_exclusive_overlap",
    "conflicts": [
      {
        "incoming": { "legalRight": "TRANSMISSION", "exploitationMode": "SVOD", "territory": "JP" },
        "existingGrantId": 4512,
        "existingContractId": 87,
        "blockingLayer": "no_exclusive_overlap"
      }
    ]
  }
}
```

충돌 세대에는 `rights_grant` 행이 없습니다. 7번은 최신 계약 이력 상태로 `hasConflict`를 계산하고, 8번은 충돌 조건을 `histories[].conflictReport`에서 읽습니다.

`POST /contracts`가 `201`로 완료되면 `staging.extract_job.consumed_at`을 같은 트랜잭션에서 기록합니다. PDF·작업·결과 JSONB의 실제 삭제는 TTL 정리 작업의 별도 책임이며, 이번 범위에는 포함하지 않습니다. 현재 계약의 `source_tmpid`는 개정 시 마지막 값으로 덮어쓰므로 과거 tmpid 영구 차단에는 history 단위 UNIQUE나 별도 소비 원장이 필요합니다.
---

## 7. 계약 목록 — `GET /contracts`

### API 역할 및 사용되는 프로세스 위치

**Ⓐ 진입 단계.** 첫 화면(`/`)의 테이블을 채우며 검색(15번)과 나란한 두 진입점 중 하나입니다.

확정된 계약과 `staging.extract_job`의 `QUEUED`·`RUNNING`·`FAILED` 항목을 최신순으로 섞어 반환합니다. `contract.title` 컬럼이 없으므로 계약 표시명은 최신 `contract_history.file_name`을 사용합니다.

### payload

쿼리 파라미터

|파라미터|타입|필수|설명|
|---|---|---|---|
|`includeProcessing`|bool|X|기본 true. 처리 중 업로드 포함 여부|
|`displayStates`|string|X|`displayState` 필터. 콤마로 여러 값(`EXPIRING,EXPIRED`), 대소문자 무시. 미지원 값이 하나라도 있으면 `400 VALIDATION_FAILED`|
|`page` / `size`|int|X|기본 1 / 설정값, size 최대 100|

`displayStates`를 주면 처리 중 항목은 `includeProcessing`과 무관하게 제외됩니다 — 처리 중인 건에는 `displayState`가 없기 때문입니다. 필터는 페이징 전에 적용되므로 `total`도 필터를 반영합니다.

### response

|필드|타입|설명|
|---|---|---|
|`items`|array|계약과 처리 중 항목|
|`total`|int|전체 건수|
|`page` / `size`|int||

`items[]` — 확정된 계약

|필드|타입|설명|
|---|---|---|
|`kind`|enum|`contract`|
|`id`|int|계약 id|
|`title`|string·null|최신 계약 이력의 fileName|
|`grantor` / `grantee`|string|권리를 주는 쪽 / 받는 쪽|
|`status`|enum|`draft` / `signed` / `cancelled`|
|`hasConflict`|bool|최신 이력이 `conflicted`인지|
|`displayState`|enum·null|`PRE_CONTRACT` / `BEFORE_TERM` / `IN_TERM` / `EXPIRING` / `EXPIRED`|
|`daysToExpiry`|int·null|종료일(포함)까지 남은 일수. 만료 후에는 음수, `BEFORE_TERM`이면 시작일까지 남은 일수|
|`expiringTier`|int·null|`EXPIRING`일 때만 `30` / `60` / `90`. 그 밖에는 null|
|`periodStart`|date·null|active 권리 중 가장 이른 시작일|
|`periodEnd`|date·null|active 권리 중 가장 늦은 종료일. 포함값|
|`serviceTitle`|null|스키마 미확정|
|`signedDate` / `createdAt`|-||

`items[]` — 처리 중인 건

|필드|타입|설명|
|---|---|---|
|`kind`|enum|`processing`|
|`tmpid`|uuid|클릭 시 `/upload/{tmpid}`로 이동|
|`status`|enum|`QUEUED` / `RUNNING` / `FAILED`|
|`stage`|enum·null|`OCR` / `LLM`|
|`filename`|null|현재 최소권한 staging 계약에서는 미제공|
|`reason`|string·null|실패 사유|
|`createdAt`|datetime·null||

```json
{
  "items": [
    {
      "kind": "processing",
      "tmpid": "0a7c...",
      "status": "RUNNING",
      "stage": "LLM",
      "filename": null,
      "reason": null,
      "createdAt": "2026-08-22T15:20:11+09:00"
    },
    {
      "kind": "contract",
      "id": 106,
      "title": "Fintrex_v3.pdf",
      "grantor": "해솔미디어 주식회사",
      "grantee": "웨이브플랫폼 주식회사",
      "status": "signed",
      "hasConflict": false,
      "displayState": "EXPIRING",
      "daysToExpiry": 17,
      "expiringTier": 30,
      "periodStart": "2026-01-01",
      "periodEnd": "2026-09-11",
      "serviceTitle": null,
      "signedDate": "2026-01-01",
      "createdAt": "2026-01-01T09:00:00+09:00"
    }
  ],
  "total": 9,
  "page": 1,
  "size": 20
}
```

`displayState` · `daysToExpiry` · `expiringTier` · `periodStart` · `periodEnd`는 저장된 값이 아니라 active 권리 기간으로 계산합니다.

`displayState` 판정 순서는 다음과 같습니다. `contract.status`가 `draft`면 기간과 무관하게 `PRE_CONTRACT`이고(계약 체결일은 판정에 쓰지 않습니다), active 권리가 없어 기간을 못 구하면 null입니다. 그 밖에는 오늘이 시작일 전이면 `BEFORE_TERM`, 종료일(포함)을 지났으면 `EXPIRED`, 잔여 90일 이상이면 `IN_TERM`, 90일 미만이면 `EXPIRING`이며 `expiringTier`는 잔여 30일 이하 `30`, 60일 이하 `60`, 그 외 `90`입니다.

`BEFORE_TERM`의 의미가 좁아졌습니다 — 예전에는 계약 체결 전까지 포함하는 값이었지만, 지금은 "권리 유효기간이 아직 시작되지 않음"만 뜻하고 계약 체결 전은 `PRE_CONTRACT`로 따로 나갑니다.
---

## 8. 계약 상세 — `GET /contracts/{id}`

### API 역할 및 사용되는 프로세스 위치

**Ⓒ 계약서 상세.** Ⓑ PIN 세션이 선행됩니다.

기본 정보, IP, active 권리, 전체 버전 이력, 최신 충돌 리포트를 한 번에 반환합니다. 충돌 세대에는 grant가 없으므로 사용자가 입력한 충돌 조건은 `histories[].conflictReport`에서 읽습니다.

**`?historyId=N`을 붙이면 그 세대 기준으로 권리를 돌려줍니다(D-34).** 생략하면 종전대로 현재 점유 중인 active 권리입니다. 세대를 지정하면 `rights_grant.contract_history_id`로 묶어 **그 버전에 실제로 있었던 권리**를 보여주며, 개정판에서 `superseded`로 내려간 행도 포함됩니다(`rights[].status`로 구분).

|파라미터|타입|필수|설명|
|---|---|---|---|
|`id`|int|O|계약 id|
|`historyId`|int·null|X|이 계약의 세대 id. 다른 계약의 세대를 넣으면 `404 NOT_FOUND`|

충돌(`conflicted`) 세대에는 `rights_grant` 행이 애초에 없으므로 `rights`는 빈 배열이고, 그 세대에 무엇을 입력했었는지는 `histories[].conflictReport`에서 읽습니다.

### payload

없음. 경로 파라미터 `id`만 사용합니다.

### response

|필드|타입|설명|
|---|---|---|
|`id`|int|계약 id|
|`title`|string·null|현재 이력, 없으면 최신 이력의 fileName|
|`grantor` / `grantee`|string|권리를 주는 쪽 / 받는 쪽|
|`status`|enum|`draft` / `signed` / `cancelled`|
|`signedDate` / `lang`|-||
|`amount` / `currency`|-|계약 금액·통화|
|`currentVersion`|int·null|현재 유효 이력 버전|
|`hasConflict`|bool|최신 이력이 conflicted인지|
|`conflictReport`|object·null|최신 충돌 세대의 P2 리포트|
|`displayState` / `daysToExpiry` / `expiringTier`|-|active 권리 기간 기반 화면 파생값. 값의 정의는 §7과 같다|
|`serviceTitle`|null|스키마 미확정|
|`ips`|array|active 권리에서 참조한 IP 목록|
|`rights`|array|현재 active 권리|
|`histories`|array|전체 업로드 세대|
|`authority`|object|재허락 카드. 스키마 미확정으로 전 필드 null|

`histories[]`

|필드|타입|설명|
|---|---|---|
|`historyId`|int||
|`version`|int|세대 번호|
|`documentKind`|enum|`draft` / `final`|
|`status`|enum|`applied` / `conflicted`|
|`fileName`|string·null||
|`uploadedAt`|datetime·null||
|`isCurrent`|bool|현재 유효 세대인지|
|`conflictReport`|object·null|해당 세대의 충돌 리포트|

`rights[]`

|필드|타입|설명|
|---|---|---|
|`rightsGrantId` / `lineageId`|int|권리 행과 계보 id|
|`status`|enum|현재 응답에서는 `active`|
|`contentAsset`|object|contentAssetId · ipId · ipTitle · ipKind · scopeType · title|
|`legalRight` / `legalRightLabel`|string|법적 권리 코드·라벨|
|`exploitationMode` / `exploitationModeLabel`|string|사업적 이용형태 코드·라벨|
|`territory` / `territoryLabel`|string|국가 코드·라벨|
|`periodStart` / `periodEnd`|date|API 종료일은 포함값|
|`exclusivity`|enum||
|`conditionsRaw` / `evidence`|object·null|원문 조건과 판정 근거|
|`createdAt` / `terminatedAt` / `terminatedReason`|-|세대 정보|

```json
{
  "id": 101,
  "title": "겨울의신호_최종.pdf",
  "grantor": "해솔미디어 주식회사",
  "grantee": "웨이브플랫폼 주식회사",
  "status": "signed",
  "signedDate": "2027-03-01",
  "lang": "ko",
  "amount": 300000,
  "currency": "USD",
  "currentVersion": 2,
  "hasConflict": false,
  "conflictReport": null,
  "displayState": "IN_TERM",
  "daysToExpiry": 480,
  "expiringTier": null,
  "serviceTitle": null,
  "ips": [{ "ipId": 12, "title": "겨울의 신호", "kind": "DRAMA" }],
  "rights": [
    {
      "rightsGrantId": 5120,
      "lineageId": 5100,
      "status": "active",
      "contentAsset": {
        "contentAssetId": 30,
        "ipId": 12,
        "ipTitle": "겨울의 신호",
        "ipKind": "DRAMA",
        "scopeType": "SERIES_ALL",
        "title": "시리즈 전체"
      },
      "legalRight": "TRANSMISSION",
      "legalRightLabel": "전송권",
      "exploitationMode": "SVOD",
      "exploitationModeLabel": "구독형 VOD",
      "territory": "JP",
      "territoryLabel": "일본",
      "periodStart": "2027-07-01",
      "periodEnd": "2029-06-30",
      "exclusivity": "exclusive",
      "evidence": { "legal_right": { "quote": "..." } },
      "conditionsRaw": { "sublicense": "AFFILIATE_ONLY" }
    }
  ],
  "histories": [
    {
      "historyId": 344,
      "version": 2,
      "documentKind": "final",
      "status": "applied",
      "fileName": "겨울의신호_최종.pdf",
      "uploadedAt": "2027-03-01T09:12:00+09:00",
      "isCurrent": true,
      "conflictReport": null
    }
  ],
  "authority": {
    "sublicensable": null,
    "allowedPartyTypes": null,
    "targetRecipientType": null
  }
}
```

권리가 하나도 없으면 `rights`는 빈 배열입니다. 정상·충돌 상세의 최상위 응답 형태는 같지만 충돌 입력은 grant가 아니라 이력의 리포트에 존재합니다.
---

## 9. 원본 PDF 조회 — `GET /contracts/{id}/file`

### API 역할 및 사용되는 프로세스 위치

**Ⓓ 원문·이력 열람.** 좌측 원본 문서 미리보기 패널에서 사용합니다. PIN 세션이 필요합니다.

현재 이력의 `contract_history.file_path`, 없으면 최신 이력의 경로가 가리키는 원본을 반환합니다.

**`?historyId=N`으로 이전 버전 원본을 받을 수 있습니다(D-34).** 확정 시 서버가 세대마다 파일을 남기므로 버전별 조회가 성립합니다.

저장 위치는 서버 내부 디렉터리(`CONTRACT_STORAGE_DIR`, 기본 `./data/contracts`)이며 object storage는 도입하지 않습니다(D-34b). **경로는 서버가 정하고 클라이언트가 지정할 수 없습니다** — 저장소 경계 밖을 가리키는 값은 조회에서 거부됩니다.

### payload

|파라미터|타입|필수|설명|
|---|---|---|---|
|`id`|int|O|계약 id|
|`historyId`|int·null|X|이 계약의 세대 id. 생략하면 현재 세대|

### response

`200 OK` · `Content-Type: application/pdf` · 바이너리 스트림

원문이 없는 계약(수기 등록 등)은 `404` 와 `{"error":{"code":"NO_SOURCE_FILE"}}` 를 반환하고, 화면은 "원문 텍스트가 없습니다" 빈 상태를 표시합니다.

다음 경우도 같은 `404 NO_SOURCE_FILE`입니다.

- `historyId`가 이 계약의 세대가 아닐 때 — id만 갈아끼워 남의 계약 원본을 받아갈 수 없습니다
- 저장된 경로가 저장소 경계 밖일 때 — D-34b 이전에 자유 문자열로 기록된 행(`/tmp/...`, `s3://...`)이 여기 해당합니다

---

## 10. 권리 이력 — `GET /rights/{lineageId}/history`

### API 역할 및 사용되는 프로세스 위치

**Ⓓ 원문·이력 열람.** 계약 상세의 권리 카드에서 "이력 보기"를 눌렀을 때 호출합니다.

같은 `lineage_id`를 공유하는 active·terminated 권리 세대를 오래된 순서로 반환합니다. 서버는 직전 세대와 `territory`, `legalRight`, `exploitationMode`, `periodStart`, `periodEnd`, `exclusivity`를 비교해 `changedFields`를 계산합니다.

### payload

|파라미터|타입|설명|
|---|---|---|
|`lineageId`|int|권리 계보 식별자|

### response

|필드|타입|설명|
|---|---|---|
|`lineageId`|int||
|`generations`|array|세대 목록. 오래된 순|

`generations[]`

|필드|타입|설명|
|---|---|---|
|`rightsGrantId` / `contractId` / `contractHistoryId`|int|권리·계약·업로드 세대 id|
|`version`|int|계약 이력 버전|
|`territory`|string|국가 코드|
|`legalRight`|string|법적 권리|
|`exploitationMode`|string|사업적 이용형태|
|`periodStart` / `periodEnd`|date|기간|
|`exclusivity`|enum||
|`status`|enum|`active` / `terminated`|
|`changedFields`|string[]|직전 세대 대비 바뀐 필드명|
|`createdAt` / `terminatedAt` / `terminatedReason`|-||

```json
{
  "lineageId": 5100,
  "generations": [
    {
      "rightsGrantId": 5100,
      "contractId": 101,
      "contractHistoryId": 341,
      "version": 1,
      "territory": "JP",
      "legalRight": "TRANSMISSION",
      "exploitationMode": "SVOD",
      "periodStart": "2027-07-01",
      "periodEnd": "2028-06-30",
      "exclusivity": "exclusive",
      "status": "terminated",
      "changedFields": [],
      "createdAt": "2027-02-10T11:04:00+09:00",
      "terminatedAt": "2027-03-01T09:12:04+09:00",
      "terminatedReason": "superseded"
    },
    {
      "rightsGrantId": 5120,
      "contractId": 101,
      "contractHistoryId": 344,
      "version": 2,
      "territory": "JP",
      "legalRight": "TRANSMISSION",
      "exploitationMode": "SVOD",
      "periodStart": "2027-07-01",
      "periodEnd": "2029-06-30",
      "exclusivity": "exclusive",
      "status": "active",
      "changedFields": ["periodEnd"],
      "createdAt": "2027-03-01T09:12:04+09:00",
      "terminatedAt": null,
      "terminatedReason": null
    }
  ]
}
```

`changedFields`는 화면 타임라인에서 무엇이 바뀌었는지 강조 표시하는 데 씁니다.
---

## 11. 계약 종료 — `POST /contracts/{id}/cancel`

### API 역할 및 사용되는 프로세스 위치

**상태를 바꾸는 동작.** 열람 중 계약 상세 화면에서 갈라져 나갑니다.

계약 상태를 `cancelled` 로 바꾸면 P2의 `contract_release_rights` 트리거가 **그 계약의 active 권리를 전부 `terminated/cancelled` 로 내립니다.** 상태만 바꾸고 권리를 그대로 두면 다른 계약을 계속 막기 때문에 두 처리를 함께 수행합니다.

종료는 PDF 업로드가 아니므로 `contract_history` 행을 만들지 않습니다. 이력은 권리 쪽 `terminated_reason` 에만 남습니다.

### payload

request body는 없습니다. 경로 파라미터 `id`만 사용합니다.

### response

`200 OK`

|필드|타입|설명|
|---|---|---|
|`contractId`|int||
|`status`|enum|`cancelled`|
|`terminatedRights`|int|`terminated` 로 바뀐 권리 행 수|
|`terminatedAt`|datetime||

```json
{
  "contractId": 101,
  "status": "cancelled",
  "terminatedRights": 4,
  "terminatedAt": "2026-08-22T16:03:22+09:00"
}
```

이미 `cancelled` 인 계약에 다시 호출하면 `422` 와 `{"error":{"code":"ALREADY_CANCELLED"}}`.

---

## 12. IP 목록 — `GET /ips`

### API 역할 및 사용되는 프로세스 위치

**㉮ IP 목록 조회.** IP 관리 화면 `UI-D-001` 좌측 목록이며 계약과 독립된 마스터 데이터입니다.

대표명과 별칭을 검색하며, 삭제 대신 `activity=deactive`로 비활성화합니다. 기본 목록은 비활성 IP를 숨깁니다. `q`가 있으면 `pg_trgm` 문자열·단어 유사도와 양방향 부분 일치 점수를 조합해 관련도 내림차순으로 반환하고, `q`가 없으면 최신 등록순으로 반환합니다.

### payload

쿼리 파라미터

|파라미터|타입|필수|설명|
|---|---|---|---|
|`q`|string|X|타이틀·별칭 유사도 검색. OCR 추출 제목처럼 등록명보다 긴 문자열도 가능|
|`includeInactive`|bool|X|기본 false|
|`page` / `size`|int|X|size 최대 100|

### 사용 예시

OCR 제목 또는 사용자가 입력한 문자열로 검색할 때는 `q`를 전달합니다.

```http
GET /api/ips?q=겨울왕국%20시즌2&includeInactive=false&page=1&size=20
```

전체 목록을 최신 등록순으로 조회할 때는 `q`를 생략합니다.

```http
GET /api/ips?page=1&size=20
```

`q`가 있으면 필터링과 관련도 정렬을 먼저 적용한 뒤 페이지를 나눕니다. 검색 응답의 `score`는 문자열 관련도이며, `matchedOn`과 `matchedText`로 대표명과 별칭 중 어느 값이 검색에 걸렸는지 확인할 수 있습니다. 0.4 미만인 후보는 반환하지 않습니다.

### response

|필드|타입|설명|
|---|---|---|
|`items`|array|IP 목록|
|`total` / `page` / `size`|int|페이지 정보|
|`items[].ipId`|int||
|`items[].title`|string|대표명|
|`items[].kind`|string·null|유형|
|`items[].activity`|enum|`active` / `deactive`|
|`items[].aliases`|array|`{ id, lang, text, aliasType }`|
|`items[].assets`|array|작품 내부 범위 목록|
|`items[].contractCount`|int|이 IP를 참조하는 계약 수|
|`items[].createdAt`|datetime·null|등록 시각|
|`items[].score`|number·null|`q` 검색 관련도 0~1. `q`가 없으면 null|
|`items[].matchedOn`|enum·null|최고 점수 대상 `title` / `alias`|
|`items[].matchedText`|string·null|최고 점수를 만든 대표명 또는 별칭|

```json
{
  "items": [
    {
      "ipId": 12,
      "title": "겨울의 신호",
      "kind": "DRAMA",
      "activity": "active",
      "aliases": [
        { "id": 41, "lang": "ko", "text": "겨울의 신호", "aliasType": "title" },
        { "id": 42, "lang": "en", "text": "Winter Signal", "aliasType": "OFFICIAL" }
      ],
      "assets": [
        {
          "contentAssetId": 30,
          "scopeType": "SERIES_ALL",
          "title": "시리즈 전체",
          "assetType": "MAIN",
          "seasonNo": null,
          "episodeNo": null,
          "editionCode": null
        }
      ],
      "contractCount": 7,
      "createdAt": "2026-08-19T10:22:00+09:00",
      "score": 0.98,
      "matchedOn": "title",
      "matchedText": "겨울의 신호"
    }
  ],
  "total": 24,
  "page": 1,
  "size": 20
}
```

---

## 17. IP 상세 조회 — `GET /ips/{id}`

### API 역할 및 사용되는 프로세스 위치

**㉯ IP 상세 조회.** 목록 행을 선택했을 때 우측 상세 패널을 채웁니다. 기존 계약 확인을 위해 `deactive` IP도 조회할 수 있습니다.

### payload

|파라미터|타입|설명|
|---|---|---|
|`id`|int|IP id|

### response

12번 `items[]`와 같은 단일 IP 객체를 반환합니다.

```json
{
  "ipId": 12,
  "title": "겨울의 신호",
  "kind": "DRAMA",
  "activity": "deactive",
  "aliases": [
    { "id": 41, "lang": "ko", "text": "겨울의 신호", "aliasType": "title" }
  ],
  "assets": [
    { "contentAssetId": 30, "scopeType": "SERIES_ALL", "title": "시리즈 전체", "assetType": "MAIN" }
  ],
  "contractCount": 7,
  "createdAt": "2026-08-19T10:22:00+09:00"
}
```

없는 ID는 `404 NOT_FOUND`입니다. 동적 경로가 `/ips/match`를 가로채지 않도록 라우터에서 정적 match 경로 뒤에 선언합니다.
---

## 13. IP 등록 — `POST /ips`

### API 역할 및 사용되는 프로세스 위치

**㉰ IP 신규 등록. 경로가 둘인데 엔드포인트는 하나입니다.**

|경로|진입|화면|
|---|---|---|
|1 / 2|IP 관리 화면의 "+ 새 IP 등록"|`UI-D-002` — 계약과 무관하게 IP 마스터만 등록|
|2 / 2|업로드 화면의 "신규 IP로 등록"|③ 단계 매칭 패널|

업로드 도중 새 작품이 나오면 화면을 벗어나지 않고 바로 만들고, 응답의 `ipId`를 매칭 패널에 채웁니다.

### payload

|필드|타입|필수|설명|
|---|---|---|---|
|`title`|string|O|대표명|
|`kind`|string·null|X|IP 유형|
|`aliases`|array|X|기본 빈 배열. `{ lang, text, aliasType }`|
|`assets`|array·null|X|작품 내부 범위 초기 목록. 생략하면 P2 트리거가 SERIES_ALL 한 행 생성|

`assets[]`는 `scopeType`, `title`, `assetType`, `seasonNo`, `episodeNo`, `editionCode`를 받을 수 있습니다. `scopeType`은 `SERIES_ALL | SEASON | EPISODE | EDITION`입니다.

```json
{
  "title": "겨울의 신호",
  "kind": "DRAMA",
  "aliases": [
    { "lang": "en", "text": "Winter Signal", "aliasType": "OFFICIAL" }
  ],
  "assets": [
    { "scopeType": "SERIES_ALL", "title": "시리즈 전체", "assetType": "MAIN" }
  ]
}
```

### response

`201 Created` — 17번과 같은 단일 IP 객체를 반환합니다.

```json
{
  "ipId": 31,
  "title": "겨울의 신호",
  "kind": "DRAMA",
  "activity": "active",
  "aliases": [
    { "id": 91, "lang": "en", "text": "Winter Signal", "aliasType": "OFFICIAL" }
  ],
  "assets": [
    { "contentAssetId": 80, "scopeType": "SERIES_ALL", "title": "시리즈 전체", "assetType": "MAIN" }
  ],
  "contractCount": 0,
  "createdAt": "2026-08-22T16:20:41+09:00"
}
```

같은 정규화 키의 IP가 이미 있으면 `409 IP_DUPLICATE`와 기존 `ipId`를 함께 반환합니다. `ip_relation`이 아직 없으므로 관계 생성 필드는 받지 않습니다.
---

## 14. IP 수정 · 활성화 — `PATCH /ips/{id}`

### API 역할 및 사용되는 프로세스 위치

**㉯ IP 상세·수정·활성화.** `UI-D-001` 우측 상세 패널의 "수정" 버튼과 활성 스위치입니다. 부분 수정이므로 보낸 필드만 반영합니다.

수정 버튼은 `UI-D-002` 를 수정 모드로 열고, 활성 스위치는 **확인 모달 없이 즉시 반영**합니다. 삭제가 아니라 되돌리기 쉬우므로 한 번 더 묻지 않습니다.

### payload

|필드|타입|설명|
|---|---|---|
|`title`|string|대표명 변경|
|`kind`|string|유형 변경|
|`aliases`|array|**전체 교체**. 보낸 목록이 최종 상태가 됩니다|
|`activity`|enum|`active` / `deactive` 전환|

```json
{ "activity": "deactive" }
```

### response

`200 OK` — 17번과 같은 구조의 단일 IP 객체를 돌려줍니다. 응답의 `assets[]`는 현재 상태를 그대로 보여주지만, 이 API로는 바꿀 수 없습니다 — 권리 대상 수정은 **18번**의 행 단위 엔드포인트를 씁니다.

```json
{
  "ipId": 12,
  "title": "겨울의 신호",
  "kind": "DRAMA",
  "activity": "deactive",
  "aliases": [
    { "id": 41, "lang": "ko", "text": "겨울의 신호", "aliasType": "title" }
  ],
  "assets": [
    { "contentAssetId": 30, "scopeType": "SERIES_ALL", "title": "시리즈 전체", "assetType": "MAIN" }
  ],
  "contractCount": 7,
  "createdAt": "2026-08-19T10:22:00+09:00"
}
```

`contractCount` 가 0보다 큰 IP를 비활성화해도 기존 계약 조회에는 영향이 없습니다. 새 계약을 만들 때 목록에 안 나올 뿐입니다.

---

## 18. 권리 대상 관리 — `POST · PATCH · DELETE /ips/{id}/assets`

### API 역할 및 사용되는 프로세스 위치

**㉯ IP 상세·수정.** `UI-D-001` 우측 상세 패널의 "권리 대상"(DB의 `content_asset`) 목록을 편집합니다. 권리 대상은 IP 안에서 권리를 걸 수 있는 범위 단위(`SERIES_ALL` / `SEASON` / `EPISODE` / `EDITION`)이고, 충돌 판정의 원자 단위가 `contentAssetId × territory × legalRight × exploitationMode × period`라 **판정 축의 하나**입니다.

|메서드|경로|하는 일|
|---|---|---|
|`POST`|`/ips/{id}/assets`|행 하나 추가|
|`PATCH`|`/ips/{id}/assets/{assetId}`|행 하나 부분 수정|
|`DELETE`|`/ips/{id}/assets/{assetId}`|행 하나 삭제|

**전체 교체가 아니라 행 단위입니다.** 14번의 `aliases`처럼 배열 통째로 받으면 빈 배열 한 번에 기존 권리 대상이 전부 사라지고, 그 대상을 참조하던 권리의 판정 근거가 함께 무너집니다. 그래서 이 API만 별도 경로로 열었습니다.

**권리가 걸린 대상은 읽기 전용입니다.** `rights_grant`가 해당 `contentAssetId`를 한 건이라도 참조하면 `PATCH`·`DELETE` 모두 `409 ASSET_IN_USE`입니다(`status`가 `terminated`인 권리도 셉니다 — 판정 이력이 남아 있습니다). 이미 판정이 끝난 권리의 대상 범위가 사후에 바뀌는 것을 막습니다.

**마지막 한 행은 지울 수 없습니다.** P2 트리거 `ensure_default_content_asset()`이 IP 생성 시 `SERIES_ALL` 한 행을 보장하는 이유가 "모든 권리 등록이 유효한 `contentAssetId`를 갖도록"인데, 마지막 행이 사라지면 `save_rights_batch()`의 기본 대상 조회가 깨집니다. 같은 `409 ASSET_IN_USE`지만 `details`로 구분합니다.

`parentId`(상하위 대상 관계)는 아직 이 API 범위가 아닙니다. 컬럼은 있으나 값을 받지 않습니다.

### payload

`POST`의 본문은 13번 `assets[]`의 원소와 같습니다.

|필드|타입|필수|설명|
|---|---|---|---|
|`scopeType`|enum|X|`SERIES_ALL`(기본) / `SEASON` / `EPISODE` / `EDITION`|
|`title`|string·null|X|대상 이름|
|`assetType`|string|X|기본 `MAIN`|
|`seasonNo`|int·null|X|`SEASON` · `EPISODE`에만|
|`episodeNo`|int·null|X|`EPISODE`에만|
|`editionCode`|string·null|X|`EDITION`에만|

```json
{ "scopeType": "SEASON", "title": "시즌 2", "assetType": "MAIN", "seasonNo": 2 }
```

`PATCH`는 같은 필드를 모두 선택으로 받습니다. **보낸 필드만 반영**하고, 명시적 `null`은 값을 비웁니다.

```json
{ "scopeType": "SERIES_ALL", "seasonNo": null }
```

`scopeType`만 좁은 범위에서 넓은 범위로 바꾸면 기존 `seasonNo`·`episodeNo`가 남아 DB CHECK 제약(`content_asset_season_scope` 등)에 걸립니다. 서버가 **기존 행과 병합한 뒤** 같은 규칙으로 검증하므로, 위 예시처럼 비울 필드를 함께 보내야 합니다. 병합 결과가 규칙을 어기면 `400 VALIDATION_FAILED`입니다.

`DELETE`는 본문이 없습니다.

|파라미터|타입|설명|
|---|---|---|
|`id`|int|IP id|
|`assetId`|int|권리 대상 id. **경로의 `id`에 속하지 않으면 `404 NOT_FOUND`**|

### response

`POST`는 `201 Created`, `PATCH`는 `200 OK`로 권리 대상 한 건을 돌려줍니다(12·17번 `assets[]`의 원소와 같은 모양).

```json
{
  "contentAssetId": 81,
  "scopeType": "SEASON",
  "title": "시즌 2",
  "assetType": "MAIN",
  "seasonNo": 2,
  "episodeNo": null,
  "editionCode": null
}
```

`DELETE`는 `204 No Content`이며 본문이 없습니다.

|상태|`code`|`details`|언제|
|---|---|---|---|
|`400`|`VALIDATION_FAILED`|`{ "field": ... }`|`scopeType`과 `seasonNo`·`episodeNo`·`editionCode` 조합이 어긋남(병합 후 기준)|
|`404`|`NOT_FOUND`|—|IP가 없거나, `assetId`가 그 IP의 것이 아님|
|`409`|`ASSET_IN_USE`|`{ "rightsGrantCount": 3 }`|권리가 걸린 대상의 수정·삭제|
|`409`|`ASSET_IN_USE`|`{ "assetCount": 1 }`|IP의 마지막 권리 대상 삭제|

```json
{
  "error": {
    "code": "ASSET_IN_USE",
    "message": "권리가 등록된 권리 대상은 수정할 수 없습니다",
    "details": { "rightsGrantCount": 3 }
  }
}
```

---

## 15. 통합 검색 — `POST /search`

### API 역할 및 사용되는 프로세스 위치

**Ⓐ 진입 단계.** 목록과 나란한 또 하나의 진입점입니다.

다음 순서로 동작합니다.

1. 자연어 질의를 `legalRights`·`exploitationModes`·지역·기간·독점여부로 해석
2. UI가 명시한 `filters`를 자연어 해석보다 우선 적용
3. `confirmed_rights_grant`의 서명 완료 계약을 SQL로 축소
4. 남은 후보 안에서만 `contract_chunk.embedding` 벡터 랭킹

벡터 검색 후 SQL 필터를 적용하면 안 됩니다.

### payload

|필드|타입|필수|설명|
|---|---|---|---|
|`query`|string|X|자연어 질의. 기본 빈 문자열|
|`filters`|object·null|X|명시 필터. 자연어 해석보다 우선|
|`page`|int|X|기본 1|
|`size`|int·null|X|최대 100|

`filters`

|필드|타입|설명|
|---|---|---|
|`legalRights`|string[]·null|법적 권리 코드|
|`exploitationModes`|string[]·null|사업적 이용형태 코드|
|`territories`|string[]·null|국가 또는 지역 그룹|
|`exclusivity`|enum·null|`exclusive` / `sole` / `non_exclusive`|
|`period.start` / `period.end`|date·null|권리 기간 중첩 검색|

```json
{
  "query": "한국 독점 SVOD 계약",
  "filters": {
    "legalRights": ["TRANSMISSION"],
    "exploitationModes": ["SVOD"],
    "territories": ["KR"],
    "exclusivity": "exclusive",
    "period": { "start": "2027-01-01", "end": "2027-12-31" }
  },
  "page": 1,
  "size": 20
}
```

### response

|필드|타입|설명|
|---|---|---|
|`interpreted`|object|자연어에서 해석한 조건|
|`results`|array|계약별 결과|
|`total` / `page` / `size`|int|페이지 정보|
|`vectorRanked`|bool|벡터 랭킹 적용 여부|

`results[]`

|필드|타입|설명|
|---|---|---|
|`contractId`|int||
|`title`|string·null|최신 계약 이력의 fileName|
|`grantor` / `grantee`|string|권리를 주는 쪽 / 받는 쪽|
|`status`|string·null|계약 상태|
|`score`|number·null|벡터 유사도. 임베딩이 없으면 null|

```json
{
  "interpreted": {
    "legalRights": ["TRANSMISSION"],
    "exploitationModes": ["SVOD"],
    "territories": ["KR"],
    "territoryGroups": [],
    "exclusivity": "exclusive",
    "period": null
  },
  "results": [
    {
      "contractId": 118,
      "title": "Fintrex_최종.pdf",
      "grantor": "해솔미디어 주식회사",
      "grantee": "SEA Digital Pte. Ltd.",
      "status": "signed",
      "score": 0.91
    }
  ],
  "total": 1,
  "page": 1,
  "size": 20,
  "vectorRanked": true
}
```

`interpreted`를 그대로 내려주는 이유는 사용자가 시스템의 질의 해석을 확인하고 명시 필터로 교정할 수 있게 하기 위해서입니다.
---

## 16. 참조 코드 목록 — `GET /refs`

### API 역할 및 사용되는 프로세스 위치

**전 구간 공통.** 법적 권리·사업적 이용형태의 2축 taxonomy와 국가·지역그룹·판정 사유코드를 제공합니다. 구형 단일축 `rightsType`은 제공하지 않습니다.

값이 자주 바뀌지 않으므로 응답에 `Cache-Control: max-age=3600`을 설정합니다. `lang`은 국가·지역그룹 라벨 선택에 적용하고 taxonomy 라벨은 현재 P2 테이블의 `name_ko`를 사용합니다.

### payload

쿼리 파라미터

|파라미터|타입|필수|설명|
|---|---|---|---|
|`types`|string|X|쉼표 구분. 생략하면 전체|
|`lang`|string|X|기본 `ko`|

`types`에 넣을 수 있는 값 — `legalRight` / `exploitationMode` / `country` / `territoryGroup` / `reasonCode`

### response

|필드|타입|설명|
|---|---|---|
|`legalRights`|array|`{ code, parentCode, nameKo, note }`|
|`exploitationModes`|array|`{ code, parentCode, nameKo, note }`|
|`countries`|array|`{ code, label, inScope }`|
|`territoryGroups`|array|`{ code, label, countries[] }`|
|`reasonCodes`|array|`{ code, category, resultType, severity, nameKo, templateKo, templateEn }`|

```json
{
  "legalRights": [
    {
      "code": "TRANSMISSION",
      "parentCode": "PUBLIC_TRANSMISSION",
      "nameKo": "전송권",
      "note": null
    }
  ],
  "exploitationModes": [
    {
      "code": "SVOD",
      "parentCode": "VOD",
      "nameKo": "구독형 VOD",
      "note": null
    }
  ],
  "countries": [
    { "code": "KR", "label": "대한민국", "inScope": true },
    { "code": "JP", "label": "일본", "inScope": true }
  ],
  "territoryGroups": [
    { "code": "APAC", "label": "아시아·태평양", "countries": ["KR", "JP", "SG", "TW"] }
  ],
  "reasonCodes": [
    {
      "code": "EXCLUSIVE_RIGHT_OVERLAP",
      "category": "RIGHTS",
      "resultType": "CONFLICT",
      "severity": 95,
      "nameKo": "독점 권리 중첩",
      "templateKo": "{territory} 권리가 겹칩니다",
      "templateEn": "Rights overlap in {territory}"
    }
  ]
}
```

`territoryGroups[].countries`를 함께 내려주므로 화면에서 지역 그룹을 즉시 국가 단위로 펼칠 수 있습니다. 저장 시에도 `rights_grant.territory`에는 국가 하나만 들어갑니다.
---

## 확인이 필요한 항목

|#|항목|대상|
|---|---|---|
|0|**OST·리메이크 관계** — 별도 IP 방향은 유지하지만 P2-DB에 `ip_relation`이 아직 없어 4번의 `relations`는 빈 배열. 관계 테이블·API 계약 확정 필요|P2·P4|
|1|**재허락(authority) 필드** — 화면에 카드가 있으나 스키마 미확정. 현재 8번 응답은 전 필드 null|P2·P5|
|2|**`serviceTitle`** — 목록 화면의 서비스 타이틀에 대응하는 컬럼이 없어 현재 null|P2·P5|
|3|**원본 파일 저장소** — 9번은 개발용 로컬 파일 어댑터. 실제 object storage 연결 필요|P1·P4|
|4|**staging TTL 정리** — `consumed_at`은 확정 API가 기록. PDF·작업·결과 JSONB 삭제 책임과 주기는 후속 결정|P1·P2·P4|
|5|**과거 tmpid 재사용 차단** — 개정 시 `contract.source_tmpid`가 덮어써지므로 history 단위 UNIQUE 또는 별도 소비 원장 필요|P2|
|6|**처리 목록 filename** — 최소권한 staging 계약에서는 null. 필요하면 `pdf_blob` 직접 권한이 아닌 메타데이터 view 정의|P1·P2·P4|
|7|**검색 결과 확장** — 스니펫·교차언어 UI 계약은 임베딩 서비스 연결 시 확장하되 SQL 필터 우선 순서 유지|P3·P4·P5|
|8|**추출 결과 병합** — `extract_result.payload`와 사용자가 검토한 6번 요청 본문의 필드별 병합 규칙 확정|P1·P4|

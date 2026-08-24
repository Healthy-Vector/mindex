# 추출 파이프라인 API 명세 (업로드 → 비동기 추출)

status: 팀 명세 정본 반영본
date: 2026-08-24
소유: **P1**(접수 API·큐·워커). P3는 이 API를 구현하지 않고, 워커가 호출하는
`stage=OCR` 함수만 제공한다.

---

## 0. 이 문서의 위치

프론트 → 업로드 접수 → 비동기 추출 → 결과 조회까지의 계약이다.
Task1(`retrieve_contract_chunks`)은 **이 API에 노출되지 않는다.** 워커 내부에서
`stage=OCR` → `stage=LLM` 사이를 잇는 중간값이다.

```
POST 업로드
   └─▶ staging.pdf_blob + staging.extract_job(QUEUED)   ← 한 트랜잭션
                    │
            [K8s 워커 파드가 리스로 가져감]
                    │
            stage=OCR   retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle
                    │      · P3 담당 · DB에 저장되지 않는 프로세스 내부값
                    ▼
            stage=LLM   RetrievalBundle -> ExtractionResult
                    │
                    ▼
            staging.extract_result.payload (JSONB)
                    │
                    ▼
            GET /extract/{tmpid}  →  status=DONE, result=payload
```

`retrieve_contract_chunks` 규격은 [docs/handoff/](../handoff/README.md) 참조.

---

## 1. 업로드 접수 — `POST` (업로드 엔드포인트)

### 역할

PDF를 `staging.pdf_blob` 에 넣고 `staging.extract_job` 에 대기 작업을 하나
등록한다. **두 INSERT가 한 트랜잭션**이라 "파일은 저장됐는데 큐에 안 들어간"
상태가 생기지 않는다. 커밋이 끝나야 응답한다.

OCR·LLM 추출은 건당 50~60초가 걸리므로 이 API는 기다리지 않는다. `202` 로
`tmpid` 만 즉시 돌려주고, 실제 처리는 워커 파드가 뒤에서 가져간다.

프론트는 응답을 받는 즉시 주소창을 `/upload/{tmpid}` 로 바꿔야 한다.
새로고침해도 돌아올 수 있게 하는 가장 싼 방법이다.

### payload — `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | binary | O | PDF. 최대 100MB. 스캔본 권장 상한은 20MB |
| `mode` | enum | O | `new` / `revision` / `final` |
| `contractId` | int | △ | `revision`·`final` 일 때 필수 |
| `ipId` | int | △ | `revision`·`final` 일 때 필수 |

| `mode` | 의미 | 후속 처리 |
|---|---|---|
| `new` | 신규 계약 | `contract` 를 새로 만들고 `status='draft'` |
| `revision` | 기존 계약의 새 초안 | 같은 `contract` 에 `contract_history` 추가, `version = v(n+1)` |
| `final` | 서명된 최종본 | 충돌이 없으면 `contract.status='signed'`, `version='final'` |

### response — `202 Accepted`

| 필드 | 타입 | 설명 |
|---|---|---|
| `tmpid` | uuid | 추출 작업 식별자. 이후 모든 단계에서 사용 |
| `status` | enum | 접수 직후이므로 항상 `QUEUED` |
| `filename` | string | 저장된 원본 파일명 |
| `byteSize` | int | 바이트 크기 |

```json
{
  "tmpid": "0a7c3f2e-9b41-4d55-8c10-2f4b7e1d9a33",
  "status": "QUEUED",
  "filename": "겨울의신호_이용허락계약서_v2.pdf",
  "byteSize": 4823910
}
```

---

## 2. 추출 상태·결과 조회 — `GET /extract/{tmpid}`

### 역할

프론트가 주기적으로 호출해 진행 상태를 확인한다. 완료되면 이 응답에 추출
결과가 함께 실려 온다.

**브라우저를 닫아도 워커는 계속 돈다.** 나중에 같은 `tmpid` 로 다시 들어오면
결과를 그대로 받는다. 폴링이 몇 번 실패해도 에러 화면으로 넘기지 말고
간격을 늘려가며(2s → 4s → 8s → 최대 30s) 계속 재시도해야 한다.

**실패도 `200` 으로 준다.** 조회 요청 자체는 성공했기 때문이다. `5xx` 로 주면
프론트가 조회 실패와 처리 실패를 구분하지 못한다.

### payload

없음. 경로 파라미터 `tmpid`(uuid)만 사용한다.

### response

| 필드 | 타입 | 설명 |
|---|---|---|
| `tmpid` | uuid | |
| `status` | enum | `QUEUED` / `RUNNING` / `DONE` / `FAILED` |
| `stage` | enum·null | `RUNNING` 일 때만. `OCR` / `LLM` |
| `queuePosition` | int·null | `QUEUED` 일 때 앞에 몇 건 있는지 |
| `reason` | string·null | `FAILED` 일 때 사유 코드 |
| `result` | object·null | `DONE` 일 때만 채워짐 |

**화면 상태 매핑**

| status / stage | 화면 표시 |
|---|---|
| `QUEUED` | 대기 중 (앞에 N건) |
| `RUNNING` / `OCR` | 문자 인식 중 |
| `RUNNING` / `LLM` | 조건 추출 중 |
| `DONE` | 검증 표 렌더 |
| `FAILED` | 사유 + 다시 시도 버튼 |

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
      "counterparty": "웨이브플랫폼 주식회사",
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
        "rightsType": "SVOD",
        "period": { "start": "2027-07-01", "end": "2029-06-30" },
        "exclusivity": "exclusive",
        "conditionsRaw": { "sublicense": "AFFILIATE_ONLY" },
        "evidence": {
          "rightsType":  [{ "location": "BODY", "page": 12, "clause": "제8조 제1항", "quote": "...", "confidence": 0.94 }],
          "territory":   [{ "location": "BODY", "page": 12, "clause": "제8조 제1항", "quote": "...", "confidence": 0.98 }],
          "period":      [{ "location": "SCHEDULE", "page": 27, "clause": "별표 2", "quote": "...", "confidence": 0.91 }],
          "exclusivity": [{ "location": "BODY", "page": 12, "clause": "제8조 제2항", "quote": "독점적으로", "confidence": 0.88 }]
        }
      }
    ],
    "rawText": "제1조 (목적) ...",
    "confidence": 0.918
  }
}
```

| 필드 | 설명 |
|---|---|
| `ipCandidates` | OCR로 읽은 작품명을 등록 IP와 대조한 후보. `mode=new` 일 때만 화면에 매칭 패널로 표시 |
| `rights[].territories` | 지역 그룹(APAC 등)은 이미 국가 단위로 펼쳐진 상태로 온다. 저장 시 국가마다 `rights_grant` 한 행 |
| `rights[].evidence` | 조건 필드마다 근거 배열. 한 필드의 근거가 본문과 별표에 흩어져 있으면 원소가 여러 개 |
| `rights[].conditionsRaw` | Reserved·Carve-out·Holdback·Sublicense 원문. 판정에는 쓰지 않고 화면 표시용 |

**실패**

```json
{ "tmpid": "0a7c...", "status": "FAILED", "reason": "OCR_TIMEOUT", "result": null }
```

| `reason` | 의미 |
|---|---|
| `OCR_TIMEOUT` | 문자 인식이 제한 시간을 넘김 |
| `LLM_TIMEOUT` | 조건 추출이 제한 시간을 넘김 |
| `UNREADABLE_PDF` | 암호화되었거나 손상된 파일 |
| `MAX_ATTEMPTS` | 재시도 한도 초과 |

---

## 3. ERD 대조 — 확인된 간극 (P3 검토, 2026-08-24)

`docs/erd/mindex_remastered.dbml` 과 위 명세를 필드 단위로 대조한 결과다.

### 3.1 이미 맞는 것

| 명세 | ERD |
|---|---|
| `status` QUEUED/RUNNING/DONE/FAILED | `staging.extract_job.status` 기본값·note 동일 |
| `stage` OCR/LLM | `staging.extract_job.stage` |
| `reason` (`MAX_ATTEMPTS` 등) | `staging.extract_job.reason` + `attempts` |
| `queuePosition` | 컬럼은 없지만 `Indexes { (status, created_at) }` 로 계산 가능 |
| `filename`, `byteSize` | `staging.pdf_blob.filename`, `byte_size` |
| `result` 전체 | `staging.extract_result.payload JSONB` |
| `confidence: 0.918` | `staging.extract_result.confidence NUMERIC(4,3)` |
| `signedDate`·`lang`·`amount`·`currency` | `contract` 에 모두 존재 |
| `territories` 를 국가 단위로 펼침 | `rights_grant.territory CHAR(2)` — 국가당 1행 |
| `period {start,end}` | `rights_grant.period DATERANGE` |
| `evidence` 필드별 배열 | `rights_grant.evidence JSONB` |
| `conditionsRaw` | `rights_grant.conditions_raw JSONB` |
| 워커 리스 방식 | `lease_until`, `attempts`, `consumed_at` |

### 3.2 간극 A — `mode` / `contractId` / `ipId` 를 저장할 곳이 없다

업로드 payload의 필수 필드인데 `staging.pdf_blob` 과 `staging.extract_job`
어느 쪽에도 대응 컬럼이 없다. 접수 API가 `202` 를 돌려준 뒤 워커가 큐에서
행을 꺼내면, 그 건이 `new` 인지 `revision` 인지 알 방법이 없다.

명세는 `mode` 에 따라 후속 처리가 완전히 갈린다고 못박고 있으므로
(`contract` 신규 생성 vs `contract_history` 추가 vs `status='signed'`)
이 값은 반드시 큐에 함께 실려야 한다.

제안 — `staging.extract_job` 에 3컬럼 추가:

```
mode        TEXT   [not null, note: 'new | revision | final']
contract_id BIGINT [note: 'revision·final 일 때 필수']
ip_id       BIGINT [note: 'revision·final 일 때 필수']
```

`pdf_blob` 이 아니라 `extract_job` 이 맞다. 같은 PDF를 다른 mode로 재처리할 수
있고, 워커가 읽는 테이블이 `extract_job` 이기 때문이다.

### 3.3 간극 B — `rightsType` 단일 필드 ↔ DB는 2컬럼 + span 2개

v3 ERD에서 권리 유형이 분리됐다.

```
rights_grant.legal_right            TEXT      (예: 공중송신권)
rights_grant.exploitation_mode      TEXT      (예: SVOD)
rights_grant.legal_right_span       INT4RANGE (not null)
rights_grant.exploitation_mode_span INT4RANGE (not null)
```

명세의 `"rightsType": "SVOD"` 는 `exploitation_mode` 한쪽만 채운다.
`legal_right` 와 두 span은 `not null` 이라 그대로는 INSERT가 안 된다.

**회수(Task1) 쪽은 영향 없다** — 근거 조항을 찾아 주는 단계라 필드 이름이
`rights_type` 한 개여도 같은 조항을 회수한다. 갈라지는 지점은 **추출(Task2)**
이다. 명세의 `rights[]` 스키마를 `legalRight` / `exploitationMode` 로 쪼갤지,
아니면 워커의 저장 단계에서 `rightsType` → 2컬럼 매핑을 태울지 결정이 필요하다.

### 3.4 간극 C — `contractInfo` 와 `contract` 테이블이 어긋난다

| 명세 | ERD |
|---|---|
| `counterparty` 1개 | `grantor`·`grantee` **둘 다 not null** |
| `title` | `contract` 에 컬럼 없음 |

`counterparty`(상대방) 하나로는 갑·을 두 칸을 못 채운다. 우리 쪽(자사)이 갑인지
을인지는 계약마다 다르다. 추출 결과에 두 당사자를 다 담고 화면에서 상대방만
골라 보여 주는 쪽이 안전하다.

`title` 은 `contract` 가 아니라 `ip`/`content_asset` 쪽 이름일 가능성이 있다.
화면 표시용이라면 `extract_result.payload` 안에만 두고 `contract` 에는
안 넣어도 된다.

### 3.5 참고 — `rawText` 크기

`result.rawText` 는 계약 원문 전체다. `extract_result.payload` 가 JSONB
한 컬럼이라 30페이지 계약이면 수십~수백 KB가 들어간다. 조회 API가 매번
이걸 통째로 실어 보내면 폴링 응답이 무거워진다. `DONE` 응답에서 `rawText` 를
빼고 별도 엔드포인트로 내리는 편이 낫다 — 최적화이지 결함은 아니다.

---

## 4. P3(파이프라인) 쪽 결론

1. **별도의 job API를 만들지 않는다.** `POST /api/parse-jobs` 류의 자체
   엔드포인트는 위 명세와 중복이므로 폐기한다.
2. **FastAPI 안에서 OCR을 별도 프로세스로 빼는 작업도 하지 않는다.**
   워커가 이미 별도 파드라 크래시 격리는 파드 재시작이 담당한다.
   (`app/pipeline/ocr.py` 의 use-after-free 는 원인 자체를 고쳐 해결됐다.)
3. **P3가 제공하는 것은 `stage=OCR` 함수 하나다.**
   `retrieve_contract_chunks(pdf_bytes) -> RetrievalBundle`.
   시그니처는 이미 확정돼 있고 이 명세 때문에 바뀌지 않는다.
4. 워커가 이 함수를 호출할 때 필요한 것:
   - 임베딩 모델 로딩이 13.7초이므로 **파드 안에서 상주 싱글턴**이어야 한다.
     요청마다 로드하면 건당 50~60초 예산을 로딩만으로 까먹는다.
   - readiness probe 는 첫 로딩이 끝난 뒤 통과시켜야 한다.
   - `UNREADABLE_PDF` 는 파이프라인이 예외로 올리고 워커가 `reason` 에 매핑한다.

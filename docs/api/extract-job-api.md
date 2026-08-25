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
있고(초안으로 한 번, 최종본으로 한 번), 워커가 읽는 테이블이 `extract_job`
이기 때문이다. FK로 걸지 않기를 권한다 — `new` 일 때 NULL이고, staging이
본 스키마를 잠그면 안 된다.

**"임시 테이블인데 그게 중요한가"에 대해** — 두 가지를 짚어 둔다.

첫째, `revision`·`final` 의 `contractId`·`ipId` 는 **DB가 배정하는 값이 아니라
사용자가 화면에서 고른 입력값**이다. "123번 계약의 새 초안" 이라고 알려 주는
값이지 새로 받아 오는 값이 아니다.

둘째, 접수와 처리 사이에 아무것도 남지 않는다.

```
t=0.1s   POST 업로드 -> 202 -> HTTP 연결 끊김
              |   여기서 mode 를 아는 주체가 사라진다. 세션도 메모리도 없다.
t=?      워커가 큐에서 행을 꺼낸다 (몇 분 뒤, 다른 파드, 재시작 이후일 수 있다)
              v   이 워커가 아는 것 = staging.extract_job 의 그 행 하나뿐
```

행에 없는 정보는 워커에게 존재하지 않는다. 그리고 워커는 `mode` 를 실제로
쓴다 — 명세가 `ipCandidates` 를 "`mode=new` 일 때만" 이라고 적어 두었다.
모르면 항상 IP 매칭을 돌리거나(불필요) 아예 안 돌리거나(`new` 가 깨짐) 둘 중
하나다. `revision` 이면 `contract_id` 가 있어야 `contract_history.version`
을 `v(n+1)` 로 계산한다.

덧붙여 이 행은 요청보다 오래 산다. `consumed_at` 컬럼이 있고
`contract.source_tmpid` 가 `unique` 로 이 행을 참조한다(`delete: set null`).
계약이 확정된 뒤에도 계보로 남는 **큐 행**이므로 자기 입력을 스스로 들고
있어야 한다.

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
| `signedDate`·`lang`·`amount`·`currency` | `signed_date`·`lang`·`amount`·`currency` ✓ |

`counterparty`(상대방)는 한 명인데 `grantor`(갑, 주는 쪽)와 `grantee`(을, 받는
쪽)는 둘 다 `not null` 이다. 게다가 우리 쪽이 갑인지 을인지는 계약마다 다르다
— 라이선스를 주는 계약이면 우리가 갑, 받는 계약이면 우리가 을이다. 상대방
이름 하나로는 어느 칸에 넣을지도 정해지지 않는다.

**추출 결과에 두 당사자를 다 담고, 화면에서 상대방만 골라 보여 주는 쪽이
안전하다.**

`title` 은 `contract` 에 없다. `ip.title` 과 `content_asset.title` 이 있지만
예시의 "겨울의 신호 영상 및 OST 이용허락계약서" 는 **계약서 문서의 제목**이라
IP 제목과도 다르다. 화면 표시용이면 `extract_result.payload` 안에만 두면 된다.

### 3.5 간극 D — `stage=OCR` 에서 만든 임베딩이 갈 곳이 없다

`contract_chunk` 는 청크 텍스트와 1024차원 벡터의 영구 자리다.

```
contract_chunk.contract_id         BIGINT  not null
contract_chunk.contract_history_id BIGINT  not null
contract_chunk.embedding           VECTOR(1024)
```

임베딩은 `stage=OCR` 에서 계산된다. 그런데 `mode=new` 면 그 시점에 `contract`
행이 아직 없다 — 계약은 사용자가 검증 화면에서 확정한 뒤에 만들어진다.
`contract_id` 가 없으니 INSERT가 불가능하다.

번들을 나중에 재활용할 수도 없다. `RetrievalBundle.chunks[]` 는 **어떤 field
에든 한 번이라도 회수된 청크만** 담기 때문이다. 실측:

```
docs/handoff/samples/CTR-EN-0017.retrieval.json
  retrieval.chunk_total = 20,  len(chunks) = 14      (chunk_referenced = 14)
```

검색용 `contract_chunk` 에는 20개가 다 있어야 하는데 번들에는 14개뿐이다.

| 안 | 방법 | 비용 |
|---|---|---|
| **① 확정 시 재계산 (권장)** | 커밋 단계에서 청킹·임베딩을 다시 돌린다 | 모델 상주 시 계약당 약 0.3초(20청크 / 80청크·s⁻¹). 규격·스키마 무변경 |
| ② 번들에 전체 청크 포함 | `chunks[]` 에 20개를 다 담고 워커가 들고 있다가 저장 | 규격 변경 + payload 증가 |
| ③ staging 청크 테이블 신설 | `staging.chunk_draft` | 테이블 추가 |

### 3.6 간극 E — `file_hash` 와 PDF 암호화가 명세만 있고 구현이 없다

`contract_history.file_hash TEXT not null` 인데 이 값을 계산하는 코드가 없다.
`staging.pdf_blob.data` 의 note 는 '암호화된 PDF 바이트 원본' 이라고 적고
있지만, `app/security/` 에는 `rls.py` 뿐이고 `app/`·`sql/` 전체에서
`encrypt`/`pgcrypto` 검색 결과가 0건이다.

BYTEA 저장 자체는 안전하다 — 바이트 배열이라 인코딩·개행 변환이 개입할
여지가 없고 1GB 상한이라 100MB 는 여유가 있다. 무결성 위험은 저장이 아니라
**staging BYTEA → 영구 저장소 이동** 구간에 있고, `file_hash` 가 정확히 그
구간을 검증하라고 있는 컬럼이다. 업로드 시 SHA-256 을 떠 두고 이동 후 재계산해
비교하면 된다. (P1/P2 영역이므로 기록만 해 둔다.)

### 3.7 참고 — `rawText` 의 자리

`result.rawText` 는 계약 원문 전체다. 영구 자리는 있다 —
`contract_history.raw_text TEXT`. 문제는 폴링 쪽이다. `extract_result.payload`
가 JSONB 한 컬럼이라 30페이지 계약이면 수십~수백 KB가 들어가는데, 조회 API가
`DONE` 응답마다 이걸 통째로 실어 보내면 폴링 응답이 무거워진다. `rawText` 를
별도 엔드포인트로 내리는 편이 낫다 — 최적화이지 결함은 아니다.

---

## 3.8 워커의 진행 상태 관리 — 푸시 없이 DB만 본다

별도의 감시 프로세스도, 웹소켓도 없다. 워커와 조회 API가 같은 행을 각각
쓰고 읽는다.

```
[워커 파드]                     [staging.extract_job]              [조회 API]
     │ ① 하나 집어옴 ─────────────────▶ │                              │
     │   status=RUNNING, stage=OCR      │                              │
     │   lease_until=now()+5min         │                              │
     │   attempts=attempts+1            │                              │
     │                                  │ ◀──── ② SELECT ─────────────│ 2s→30s 폴링
     │ ③ OCR 끝 ──────────────────────▶ │ stage=LLM                    │
     │ ④ 30초마다 하트비트 ───────────▶ │ lease_until 갱신             │
     │ ⑤ 완료 ────────────────────────▶ │ status=DONE                  │
     │   extract_result INSERT          │                              │
```

**① 집어오기** — `SKIP LOCKED` 로 워커가 여러 개여도 같은 행을 안 집는다.
두 번째 WHERE 조건이 죽은 워커의 작업을 회수한다.

```sql
UPDATE staging.extract_job SET status='RUNNING', stage='OCR',
       lease_until=now()+interval '5 min', attempts=attempts+1
WHERE tmpid = (SELECT tmpid FROM staging.extract_job
               WHERE status='QUEUED'
                  OR (status='RUNNING' AND lease_until < now())
               ORDER BY created_at LIMIT 1
               FOR UPDATE SKIP LOCKED)
RETURNING *;
```

**④ 하트비트가 곧 생존 신호다.** 워커가 죽으면 `lease_until` 이 지나가고 다른
워커가 회수하면서 `attempts` 가 오른다. 한도를 넘으면 `MAX_ATTEMPTS` 로 `FAILED`.

**대기 순번** — `Indexes { (status, created_at) }` 가 이걸 위해 있다.

```sql
SELECT count(*) FROM staging.extract_job
WHERE status='QUEUED'
  AND created_at < (SELECT created_at FROM staging.extract_job WHERE tmpid = $1);
```

**진행률의 한계** — `stage` 는 `OCR`/`LLM` 두 값뿐이다. 화면에 띄울 수 있는 건
"문자 인식 중" / "조건 추출 중" 이지 **"3/10 페이지" 같은 페이지 단위 진행률이
아니다.** 그걸 원하면 컬럼이 하나 더 필요하다.

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
5. **`contract_chunk` 적재는 회수 단계가 아니라 확정 단계의 일이다**(3.5절).
   `stage=OCR` 에서는 `contract_id` 가 존재하지 않는다. 권장안은 확정 시
   재계산이며, 그러려면 파이프라인이 "번들 없이 청크 전량만 내놓는" 경로도
   노출해야 한다 — `chunk_document(pdf_bytes) -> list[Chunk]` 수준.
   Phase 6 이후 과제로 남긴다.

---

## 5. 열린 항목

| # | 내용 | 소유 |
|---|---|---|
| A | `staging.extract_job` 에 `mode`/`contract_id`/`ip_id` 추가 | P1·P2 |
| B | `rightsType` 단일 필드 → `legal_right`+`exploitation_mode`+span 2 | Task2·P2 |
| C | `counterparty` → `grantor`/`grantee` 양측, `title` 자리 결정 | Task2·P2 |
| D | `contract_chunk` 를 언제 무엇으로 채울지 (권장: 확정 시 재계산) | P3·P1 |
| E | `file_hash` 계산과 PDF 암호화가 명세만 있고 구현이 없음 | P1·P2 |
| F | 페이지 단위 진행률이 필요하면 `extract_job` 에 컬럼 추가 필요 | P1·프론트 |

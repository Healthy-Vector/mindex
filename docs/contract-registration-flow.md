# Mindex 계약·권리 등록 프로세스

이 문서는 계약서 최초 업로드부터 권리 등록과 계약 최종화까지의 실행 흐름을 정의한다. 데이터 모델은 [`mindex_remastered.dbml`](mindex_remastered.dbml), 설계 근거는 [`DECISIONS.md`](DECISIONS.md)의 D-28·D-29를 따른다.

## 전제

- Mindex는 회사 서버에 직접 설치되는 단일 회사용 시스템이다. 회사 구분용 `tenant`는 없다.
- `ip`는 미리 등록된 작품을 선택하는 것이 기본이다. `ip` 행은 관리 대상 작품이라는 뜻이며 법적 소유권을 뜻하지 않는다.
- 최초 검증 단계에서는 `contract`와 `contract_document`의 실제 DB ID가 아직 없다.
- PDF 바이너리는 DB가 아니라 오브젝트 스토리지에 저장한다.
- AI 후보 하나에는 `candidate_evidence`가 한 건 이상 필요하며 여러 근거를 연결할 수 있다.

## 전체 흐름

```text
기존 IP 선택
→ PDF 임시 업로드
→ OCR·AI 추출
→ evidence 배열 생성
→ 사용자 확인·수정
→ probe_rights() 검증
→ 검증용 행 전체 롤백
→ 결과 표시
→ 실제 등록 또는 충돌 처리 시작
→ 계약 최종화
```

## 1. IP 선택

사용자는 등록된 작품을 선택한다.

```sql
SELECT id, title_ko, title_en, title_ja
FROM ip
WHERE id = :ip_id;
```

신규 작품이면 실제 등록 트랜잭션에서 `ip`를 먼저 생성하고 `RETURNING id`로 ID를 받는다.

## 2. PDF 임시 업로드

최초 PDF는 오브젝트 스토리지에 업로드하지만 DB에는 아직 계약과 문서 행을 만들지 않는다.

```text
storage_key
file_name
file_hash
mime_type
```

이 단계의 작업 식별자는 애플리케이션의 임시 작업 ID다. `contract_id`나 `document_id`를 미리 요구하면 안 된다.

등록하지 않고 이탈한 파일의 수명과 삭제 정책은 별도 스토리지 TTL 정책으로 정한다.

## 3. OCR·AI 추출

OCR과 AI가 문서에서 권리 후보와 인용 근거를 만든다. 등록 전 작업 데이터의 보관 위치는 애플리케이션 작업 저장소이며, 아직 업무 테이블에는 커밋하지 않는다.

```json
{
  "ip_id": 10,
  "document": {
    "storage_key": "contracts/temp/abc.pdf",
    "file_name": "contract.pdf",
    "file_hash": "sha256:..."
  },
  "candidates": [
    {
      "territory": "JP",
      "legal_right": "TRANSMISSION",
      "exploitation_mode": "SVOD",
      "period": "[2026-01-01,2028-01-01)",
      "exclusivity": "exclusive",
      "confidence": 0.93,
      "evidence": [
        {
          "page_start": 8,
          "source_clause": "제8조",
          "source_quote": "권리 부여에 관한 원문"
        },
        {
          "page_start": 12,
          "page_end": 13,
          "source_clause": "제12조",
          "source_quote": "기간과 지역에 관한 원문"
        }
      ]
    }
  ]
}
```

`page_start`와 `page_end`는 파서가 페이지를 알아내지 못하면 생략할 수 있지만 `source_quote`는 비어 있을 수 없다.

## 4. 사용자 확인·수정

사용자가 정규화된 권리값과 모든 근거 인용을 확인한다.

```text
territory
legal_right
exploitation_mode
period
exclusivity
evidence[]
```

AI가 표현을 읽었지만 코드로 정규화하지 못한 경우에는 `*_UNRESOLVED` 계열 `review_reason_code`를 함께 전달한다.

## 5. 검증

화면의 `검증` 동작은 후보별로 `probe_rights()`를 호출한다. 함수는 evidence JSON 배열을 받는다.

함수 내부에서는 실제 제약조건을 태우기 위해 다음 행을 서브트랜잭션에 INSERT한다.

```text
ip                 신규 작품인 경우에만 임시 생성
contract
contract_document
rights_grant_candidate
candidate_evidence N건
rights_evaluation
rights_evaluation_reason N건
rights_grant             최종 EXCLUDE·trigger 확인용 시도
```

판정 결과와 실제 제약명을 수집한 뒤 sentinel 예외로 전체 서브트랜잭션을 롤백한다.

```text
반환됨: NORMAL / WARNING / REVIEW_REQUIRED / CONFLICT, 사유, 겹침 기간, 제약명
남지 않음: 위에서 만든 모든 업무 행
남는 부작용: BIGSERIAL 시퀀스의 번호 간격
```

검증은 조회 조건을 흉내 내는 작업이 아니다. 실제 `rights_grant` INSERT를 시도하므로 `no_exclusive_overlap`과 `no_exclusivity_conflict`의 최종 동작을 그대로 확인한다.

## 6. 검증 결과별 동작

| 결과 | 다음 동작 | 검증 시 DB 커밋 |
|---|---|---:|
| `NORMAL` | 권리 등록 가능 | 없음 |
| `WARNING` | 경고 확인 후 권리 등록 가능 | 없음 |
| `REVIEW_REQUIRED` | 값 또는 근거 수정 후 재검증 | 없음 |
| `CONFLICT` | AMENDED, WAIVER, REJECTED 중 선택 | 없음 |

`AMENDED`는 입력값을 수정하고 다시 검증한다. `REJECTED`는 등록을 진행하지 않는다. `WAIVER`처럼 며칠에 걸친 후속 처리가 필요하면 다음 실제 등록 단계에서 충돌 후보와 판정 사유를 저장해 처리 대상을 만든다.

## 7. 실제 등록 트랜잭션

사용자가 등록을 확정하면 그때 실제 ID를 순서대로 받는다.

```sql
BEGIN;

-- 신규 작품일 때만
INSERT INTO ip (...)
RETURNING id;

INSERT INTO contract (...)
RETURNING id;

INSERT INTO contract_document (...)
RETURNING id;

INSERT INTO rights_grant_candidate (...)
RETURNING id;

INSERT INTO candidate_evidence (...); -- 후보별 N건

SELECT evaluate_candidate(:candidate_id);

-- 최신 판정에 blocking 사유가 없는 후보만 호출
SELECT register_candidate(:candidate_id, :verified_by);

COMMIT;
```

계약서에서 후보가 여러 건 나온 경우 모든 후보와 근거를 같은 계약·문서에 연결한다.

- `NORMAL`과 허용 가능한 `WARNING` 후보는 `register_candidate()`를 호출해 `rights_grant`로 승격한다.
- blocking 사유가 있는 후보에는 `register_candidate()`를 호출하지 않는다. candidate·evaluation·reason을 남겨 후속 처리한다.
- 일부 후보가 충돌해도 정상 후보의 grant와 충돌 후보의 처리 상태를 같은 계약 건에 보존할 수 있다.
- 예상하지 못한 EXCLUDE 위반이나 시스템 오류가 발생하면 트랜잭션 전체를 롤백한다.

확정 권리의 근거 추적 경로는 다음과 같다.

```text
rights_grant.source_candidate_id
→ rights_grant_candidate.id
→ candidate_evidence.candidate_id
```

## 8. 충돌 후속 처리

저장된 충돌 후보는 `rights_evaluation_reason` 단위로 처리한다.

```text
AMENDED
→ candidate 값 수정
→ evaluate_candidate() 재실행

WAIVER
→ conflict_resolution 생성·승인
→ 기존 conflicting rights_grant를 terminated로 전환
→ evaluate_candidate() 재실행
→ blocking 사유가 사라지면 register_candidate()

REJECTED
→ candidate를 rejected로 종료
```

WAIVER도 EXCLUDE를 우회하지 않는다. 충돌 원인이 되는 기존 grant를 먼저 종료한 뒤 신규 grant가 정상 제약을 다시 통과한다.

## 9. 계약 최종화

모든 후보가 `approved` 또는 `rejected`로 결론나고 최종 문서가 준비되면 다음을 수행한다.

```text
contract.final_document_id = 최종 contract_document.id
contract_document.status = final
rights_grant.status = final       애플리케이션이 해당 grant들을 전환
contract.status = final
```

`validate_contract_finalize()`는 다음을 검사한다.

- `final_document_id`가 존재하는가
- 그 문서가 같은 contract 소속인가
- 문서 상태가 `approved` 또는 `final`인가
- `extracted` 또는 `review` 상태의 candidate가 남아 있지 않은가

권리 충돌은 이 단계에서 다시 계산하지 않는다. 각 `rights_grant` INSERT 시점의 EXCLUDE와 statement trigger가 최종 무결성을 이미 보장한다.

## 10. 기존 계약의 수정 문서

위 흐름은 계약을 처음 등록할 때의 무커밋 규약이다. 이미 `contract`가 존재하는 상태에서 수정 PDF를 올리면 새 `contract_document.version`을 생성해 버전을 관리한다.

```text
contract #10
├─ document v1
├─ document v2
└─ document v3 (final_document_id)
```

수정 문서에서 다시 추출한 후보와 evidence는 반드시 새 `document_id`에 연결해 이전 PDF의 근거와 섞이지 않게 한다.

## 구현 불변조건

- 클라이언트가 임의의 `contract_id`나 `document_id`를 만들어 보내지 않는다.
- 실제 ID는 INSERT의 `RETURNING id`로 받는다.
- candidate에는 evidence가 한 건 이상 있어야 등록할 수 있다.
- `source_quote`는 빈 문자열일 수 없다.
- blocking 사유가 있는 후보는 grant로 승격하지 않는다.
- 모든 grant INSERT는 EXCLUDE와 statement trigger를 통과한다.
- `contract.status`와 `contract_document.status`는 의미가 다르므로 자동 동기화하지 않는다.

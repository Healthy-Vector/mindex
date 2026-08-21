# Mindex 계약·권리 등록 프로세스

이 문서는 D-30의 계약서 단위 all-or-nothing 흐름을 정의한다. 데이터 모델은 [정본 DBML](mindex_remastered.dbml), 설계 근거는 [DECISIONS](DECISIONS.md)를 따른다.

## 핵심 규약

- PDF 한 건이 판정 한 건이다.
- candidate를 저장해 건별 승인하지 않는다.
- 검증은 전체 권리 배열을 실제 DB 제약에 넣어 본 뒤 롤백한다.
- 저장은 배치 전체가 성공하거나 전체가 실패한다.
- 충돌한 PDF 세대는 `contract_history.conflict_report`만 남고 grant는 하나도 생기지 않는다.

## 전체 흐름

```text
기존 IP와 content_asset 선택
→ PDF 임시 업로드
→ OCR·AI 추출
→ 사용자 확인·수정
→ validate_rights_batch()
→ 정상: save_rights_batch()
→ 충돌: 조건 수정 또는 기존 grant 종료 후 전체 재제출
→ 필요 시 contract final 전환
```

## 1. 대상과 PDF 준비

`ip`는 관리 작품, `content_asset`은 실제 권리 판정 대상이다. 신규 IP가 생성되면 `ip_default_content_asset` trigger가 `ensure_default_content_asset()`를 실행해 `SERIES_ALL` 기본 asset을 만든다. 이미 존재하는 IP에 기본 asset이 없을 때 이를 자동 복구하는 함수는 현재 없다.

PDF 바이너리는 object storage에 임시 업로드한다. 등록 전에는 `contract_history`가 없으므로 고아 객체 정리는 storage TTL 정책이 담당해야 한다.

## 2. 추출 배치

앱은 PDF에서 권리 배열과 필드별 evidence를 만든다.

```json
[
  {
    "content_asset_id": 42,
    "territory": "JP",
    "legal_right": "TRANSMISSION",
    "exploitation_mode": "SVOD",
    "period": "[2026-01-01,2028-01-01)",
    "exclusivity": "exclusive",
    "conditions_raw": {"holdback": "30 days"},
    "evidence": {
      "legal_right": {"page": 8, "clause": "제8조", "quote": "전송할 권리"},
      "exploitation_mode": {"page": 8, "clause": "제8조", "quote": "구독형 VOD"},
      "territory": {"page": 9, "quote": "일본 지역"},
      "period": {"page": 10, "quote": "2026년부터 2년간"},
      "exclusivity": {"page": 8, "quote": "독점적으로"}
    }
  }
]
```

`evidence`에는 다섯 필수 키가 모두 있어야 하며 각 항목의 `quote`는 빈 문자열일 수 없다. `conditions_raw`는 아직 판정축으로 정형화하지 않은 원문 조건 보존용이다.

## 3. 검증

`validate_rights_batch()`에 계약 메타데이터, PDF 메타데이터, 권리 배열을 전달한다. 함수는 `attempt_rights_batch_insert()`를 통해 실제 `rights_grant` INSERT 경로와 EXCLUDE/trigger를 실행하지만 서브트랜잭션을 되돌린다.

반환 결과에는 등록 가능 여부와 충돌 보고서가 포함된다. EXCLUDE가 발생하면 실제 `constraint_name`, 기존 grant ID, 겹친 기간을 보고서에서 확인할 수 있다. 검증 호출은 업무 행을 남기지 않지만 sequence 번호 간격은 생길 수 있다.

## 4. 저장

`save_rights_batch()`는 다음을 한 트랜잭션에서 수행한다.

```text
contract 생성 또는 기존 contract ID 사용
→ 다음 version 계산
→ contract_history 생성
→ 권리 배열을 한 INSERT 문장으로 rights_grant에 투입
→ 성공 시 registered + current_history_id 갱신
→ 실패 시 grant 전체 롤백 + conflicted history와 conflict_report 저장
```

현재 `save_rights_batch()`는 기존 contract를 명시적으로 잠그지 않고 `MAX(version) + 1`로 다음 version을 계산한다. 같은 계약에 대한 동시 등록을 직렬화해야 한다면 애플리케이션에서 막거나 DB 잠금 로직을 추가해야 한다.

성공한 첫 세대에서 `lineage_id`는 각 grant의 자기 ID로 시작한다. 기존 계약의 새 세대는 자연키가 일치하는 이전 권리의 lineage를 승계하고, 이전 세대의 active grant를 `terminated_reason='superseded'`로 종료한다.

## 5. 충돌 처리

충돌 세대에는 grant가 0행이므로 후보별 승인이나 부분 등록은 없다.

- AMENDED: 입력 조건을 수정하고 전체 배치를 다시 검증·저장한다.
- WAIVER: `terminate_rights_grant(grant_id, 'waiver', note)`로 충돌 원인을 종료한 뒤 전체 배치를 재제출한다.
- REJECTED: 추가 저장 없이 conflicted history를 판정 기록으로 유지한다.

WAIVER는 EXCLUDE 우회가 아니다. 기존 active grant가 사라진 뒤 동일 제약을 다시 통과하는 절차다.

## 6. 계약 상태

등록 성공 후 `contract.status`는 `active`, `current_history_id`는 최신 registered 세대를 가리킨다. `final` 전환 시 DB trigger는 current history가 같은 계약 소속이고 `registered`인지 검사한다.

`final` 계약에 새 PDF를 등록할 수 있는지 여부는 앱 정책이다. DB는 개정 자체를 금지하지 않는다. `contract_version`은 없으므로 counterparty·amount 같은 계약 메타데이터 수정 감사이력이 필요하면 별도 모델을 설계해야 한다.

## 7. 검색과 변경 로그

`contract_chunk`는 `contract_history_id`에 연결되어 세대별 조항과 임베딩을 분리한다. `contract_history` 행의 INSERT/UPDATE/DELETE는 `change_log`를 만든다. 이를 소비해 재청킹·재임베딩할 worker 골격은 있으나 실제 재처리 함수는 아직 구현되지 않았다.

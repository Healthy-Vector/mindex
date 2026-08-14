# mindex ERD 개요

`docs/mindex.erd.json`(erd-editor 포맷)의 텍스트 설명본. 2026-08-14 세션(D-17~D-22) 기준 —
**15개 테이블 · 106개 컬럼 · 20개 관계**.

erd-editor에서 열어 시각적으로 보려면 [erd-editor.io](https://erd-editor.io)나 VSCode erd-editor 확장에서
`docs/mindex.erd.json`을 불러오면 된다.

## 1. 테넌트 (D-20)

| 테이블 | 역할 |
|---|---|
| `tenant` | 팀 실체 테이블. 여기저기 UUID로만 떠돌던 `tenant_id`를 공식화했다. `access_key_hash`는 bcrypt 해시만 저장하고, `CHECK` 제약으로 DB가 평문 저장을 거부한다 |

`content`·`contract`·`contract_version`·`rights_grant`·`rights_grant_history`·`contract_chunk`의 `tenant_id`가
전부 `tenant(id)`를 단일 컬럼 FK로 가리킨다(기존 `(id, tenant_id)` 복합 FK 구조(D-09)는 그대로 유지 — 그 위에
얹는 참조 무결성).

## 2. 참조 테이블 (어휘·매핑, 판정에 직접 안 쓰이거나 조회용)

| 테이블 | 역할 |
|---|---|
| `country` | 국가코드 어휘. `rights_grant.territory`가 참조하는 유일한 지역 단위. `in_scope=true` 8개국이 WORLDWIDE 전개 대상 |
| `territory_group` | "아시아 전역", "Worldwide" 같은 지역 표현의 정의. **저장 단위 아님** — 등록 시점에 국가로 전개된다 |
| `territory_group_member` | `territory_group` ↔ `country` 매핑 |
| `statutory_right` | 법정 지분권(방송권·전송권·공중송신권 등) 어휘. **판정에 안 쓰인다** — 국가별 관행 차이를 사람에게 경고하는 자문축 |
| `right_mapping` | 유통창구(`rights_type`, 판정축) ↔ 법정 지분권(`statutory_right`, 자문축) 매핑 + 경고 문구. 저장을 막지는 않는다 |
| `conflict_code` | 충돌 코드 → 한/영 템플릿 문구. 코드값은 EXCLUDE/트리거의 `constraint_name`을 그대로 쓴다 |

> `statutory_right`·`right_mapping`을 앱 설정(JSON/코드)으로 축소하자는 코드리뷰 제안이 있었으나,
> 데모 시나리오 1(겨울연가·NHK 유형)의 경고 근거라 **유지하기로 결정**했다 (D-22).

## 3. 도메인 테이블 (실제 업무 데이터)

| 테이블 | 역할 |
|---|---|
| `content` | 콘텐츠(IP). 언어별 제목이 달라도 같은 작품이면 같은 행 — 다국어 충돌 판정의 기반 |
| `contract` | 계약서 원문·당사자·체결일. `raw_text`·`amount`는 SER-006 암호화 대상(미적용) |
| `contract_version` | 계약 메타데이터 수정 이력(jsonb 스냅샷). **D-22에서 실제로 연결** — `contract` UPDATE 시 `snapshot_contract_version()` 트리거가 자동으로 `version`을 올리고 이전 값을 스냅샷으로 남긴다(전에는 채우는 코드가 없어 죽어있던 테이블이었다) |
| `rights_grant` | **플랫폼의 심장.** 실제 권리 레코드 — 지역 1개당 1행. `status`(draft/review/provisional/complete/terminated)로 워크플로우 상태 관리, EXCLUDE·트리거가 여기서 충돌을 잡는다(판정 대상은 provisional·complete뿐) |
| `rights_grant_history` | append-only 원장. `parsed`(파싱+probe 직후 "저장" 버튼) → `registered`(등록) → `status_changed`/`terminated`(상태 전이) 이벤트가 순서대로 쌓인다. **D-22에서 `history_seq` 컬럼 제거** — `MAX+1` 방식이 동시 등록 시 유니크 충돌을 낼 수 있어서, `id`(bigserial)로 순서를 보장하는 쪽으로 단순화했다. 등록해도 원본 `parsed` 행은 더 이상 UPDATE하지 않는다(진짜 append-only) |
| `contract_chunk` | 조항 단위 텍스트 + 임베딩 벡터(1024차원). 교차언어 검색용 |
| `change_log` | P1 재색인 워커가 폴링하는 기술 로그. **D-22에서 `rights_grant` 트리거 제거** — 워커 목적이 계약 재임베딩이라 권리 데이터 변경은 무관함을 코드(`change_log_worker.py`)로 확인 후 제거했다. 이제 `contract` 변경만 로그에 쌓인다 |
| `schema_meta` | 스키마 버전 기록. 낡은 볼륨 감지용 |

## 4. 핵심 흐름

```
업로드 → 파싱 → 검증
  → probe_rights_conflict() : rights_grant에 INSERT 시도 후 무조건 ROLLBACK
      (충돌 여부만 반환, 흔적 0)
  → "저장" 버튼 : rights_grant_history에 event_type='parsed' INSERT
  → "등록" 버튼 : register_rights_grant(history_id)
      → rights_grant에 진짜 INSERT (여기서 재판정됨)
      → 트리거가 event_type='registered' history 자동 기록,
        source_history_id로 원본 parsed 행과 연결
  → 이후 status UPDATE(가확정→완료→종료)마다
      트리거가 status_changed/terminated history 자동 기록
```

## 5. ERD 파일 안의 메모 2개

EXCLUDE 제약·트리거는 erd-editor의 테이블/관계로 표현이 안 되므로 텍스트 메모로 보완했다.

- **memo-1** — `no_exclusive_overlap` EXCLUDE 제약의 실제 SQL과 판정 규칙 요약
- **memo-2** — D-17~D-22 변경 이력 요약 (probe→history→등록 흐름, 코드리뷰 반영 4건까지)

## 6. 설계 근거

전체 결정 이력은 `docs/DECISIONS.md`의 D-17~D-22 참조 (개인 작업 문서라 `.gitignore` 대상 — 클론 시 없는 것이 정상).

| ID | 요약 |
|---|---|
| D-17 | `rights_grant` status 5값 도입, 판정 대상은 provisional·complete만 (D-16 대체) |
| D-18 | `rights_grant_history` append-only 원장 + `conflict_code` 참조 |
| D-19 | probe/등록 분리 — `probe_rights_conflict()`·`register_rights_grant()` |
| D-20 | `tenant` 테이블 신설, 팀 공유 API 키는 bcrypt 해시로만 저장 |
| D-21 | `rights_grant_history.ai_note` → `conflict_report jsonb`로 교체 |
| D-22 | 코드리뷰(Codex) 반영 4건 — contract_version 연결·history_seq 제거·진짜 append-only·change_log 범위 축소 |

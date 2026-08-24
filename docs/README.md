# docs

이 디렉터리의 데이터 모델 정본은 [`mindex_remastered.dbml`](mindex_remastered.dbml) 하나다.
스키마 변경 시 `sql/init/*.sql`과 이 파일을 함께 갱신한다.

## 현재 문서

- [`mindex_remastered.dbml`](mindex_remastered.dbml): PostgreSQL 17 데이터 모델 정본. `public`(운영) 스키마와 `staging`(비동기 추출 큐) 스키마를 모두 포함한다
- [`mindex DB 설명서.md`](mindex%20DB%20설명서.md): 정본 DBML의 테이블 구조와 서비스 플로우 설명
- [`mindex_staging DB 설명서.md`](mindex_staging%20DB%20설명서.md), [`mindex_staging_erd.svg`](mindex_staging_erd.svg): `staging` 스키마(비동기 OCR/LLM 추출 파이프라인) 구조 설명. D-32/D-33 참고
- [`contract-registration-flow.md`](contract-registration-flow.md): 최초 업로드·검증·실제 등록·충돌 처리·계약 최종화 실행 흐름
- [`ha-design.md`](ha-design.md), [`mindex-architecture.svg`](mindex-architecture.svg): HA 및 배포 아키텍처
- `WORKLOG.md`, `DECISIONS.md`: 개인 작업 기록이며 `.gitignore` 대상

구세대 ERD export와 이전 스키마 설명은 정본과 충돌하므로 보관하지 않는다.
RFP·일정·공수 산정 등 팀 공유 문서는 저장소 밖에서 관리한다.

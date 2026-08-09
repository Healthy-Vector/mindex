# CLAUDE.md — mindex (K-RIGHTS)

OpenSQL 기반 저작권 계약 인텔리전스 플랫폼. 2026 오픈소스 개발자대회 티맥스티베로 지정과제.

## 작업 시작 전 반드시 읽을 것

1. **`docs/WORKLOG.md`** — 지난 세션에서 어디까지 했고 무엇이 막혀 있는지
2. **`docs/DECISIONS.md`** — 확정된 설계 결정(D-xx)과 미결 항목(O-xx)

이 두 파일을 읽지 않고 작업을 시작하면 이미 조사한 것을 다시 조사하게 된다.
**작업이 끝나면 `WORKLOG.md`에 항목을 추가하고, 새 결정이 있으면 `DECISIONS.md`를 갱신한다.**

> 이 두 파일은 **개인 작업 문서라 `.gitignore` 대상이다.** 저장소를 clone하면 없는 것이
> 정상이며, `SessionStart` 훅(`.claude/hooks/session-context.py`)이 있으면 읽고 없으면
> 조용히 넘어간다. 각자 자기 것을 만들어 쓰면 된다.
> 팀 공유 산출물은 `docs/RIGHTS-VOCABULARY.md`, `docs/mindex.erd.json`, 이 문서다.

## 이 저장소에서 내 역할

**P2 — 데이터 / 보안.** 담당 요구사항: `DAR-001·003·004`, `SFR-006·007·011·016`, `SER-002·004·006·007·008·009`, `COR-001~005`.

| 내가 만드는 것 | 내가 만들지 않는 것 |
|---|---|
| 스키마 · migration SQL · EXCLUDE/트리거 충돌 판정 · RLS · DB 롤 · 암호화 대상 컬럼 · DB 단위 테스트 | OpenSQL 실물 설치·배포(P1) · 파싱/추출(P3) · 검증/검색/API(P4) · 화면/오케스트레이션(P5) |

경계 원칙: **P2가 SQL과 DB 규칙을 만들고, P1이 OpenSQL 실물에 배포해 제품 기능을 검증한다.**

## 설계 원칙 (변경 불가)

| | |
|---|---|
| **P-1** | LLM은 비정형→정형 **변환만** 한다. 판정하지 않는다 |
| **P-2** | 충돌 판정은 **DB 제약조건**이 수행한다 (결정론적) |
| **P-3** | 모든 추출값은 **원문 인용을 동반**한다 |
| **P-4** | 애플리케이션 레이어가 침해돼도 **데이터 무결성은 유지**된다 |

## 절대 규칙

- **PostgreSQL 16 고정.** OpenSQL이 16.8 기반이다. 17 사용 금지
- **PyMuPDF 금지.** AGPL이라 프로젝트 전체 라이선스가 오염된다. `pdfplumber` + `pypdfium2` 사용
- **`.env`·라이선스 XML 절대 커밋 금지.** 라이선스 XML은 상용 SW 자격증명이다. `.gitignore` 확인
- 프로젝트 라이선스: **Apache 2.0**

## 함정 (실제로 당한 것들)

- **스키마를 바꿨는데 반영이 안 된다** → `docker-entrypoint-initdb.d`는 **pgdata 볼륨이 비어 있을 때만** 실행된다. `docker compose down -v` 후 재기동해야 한다. `-v`가 없으면 낡은 스키마가 그대로 남는다
- **CI가 초록인데 스키마가 깨져 있다** → `ci.yml`의 `psql -f`에 `ON_ERROR_STOP=1`이 없으면 문 단위 에러가 나도 exit 0이다
- **`sql/init/`에 새 파일을 추가했는데 CI가 안 돈다** → CI가 특정 파일 하나만 지정해 실행하는지 확인. 디렉터리 전체를 루프로 돌려야 한다
- ~~git 저장소 루트가 `mindex/`가 아니다~~ → **2026-08-09 해소.** 루트는 이제 `mindex/`이고 원격은 `Healthy-Vector/mindex`다 (O-03)
- **로컬 파일이 최신이라고 가정하지 말 것.** 2026-08-09에 로컬 워킹트리가 원격보다 낡아 `frontend/` 전체와 라우터 등록이 빠져 있었다. **작업 시작 전 `git fetch && git status`**. 팀은 PR 기반으로 일한다 — `main`에 직접 push하지 않는다
- **`git push --force` 금지.** 원격에 팀 작업과 열린 PR이 있다
- **`fatal: detected dubious ownership`** → 폴더 소유 SID가 현재 Windows 계정과 달라서다. `git config --global --add safe.directory 'E:/석 공부/오픈소스/mindex'` 한 번 실행하면 된다. 파일은 건드리지 않는다

## 문서 위치

| 문서 | 위치 |
|---|---|
| 세션 로그 · 설계 결정 | `docs/WORKLOG.md`, `docs/DECISIONS.md` |
| 권리유형 어휘 3안 비교 | `docs/RIGHTS-VOCABULARY.md` |
| ERD | `docs/mindex.erd.json` |
| RFP · 실행 계획서 | 저장소 **밖** `../기획서 v3/` |
| 코퍼스 분석 4종 | 저장소 **밖** `../k-rights/analysis/` |

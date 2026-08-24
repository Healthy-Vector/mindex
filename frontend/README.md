# mindex — 계약/IP 라이선스 관리 웹 프론트엔드

| 분류 | 기술 | 버전 | 비고 |
|---|---|---|---|
| UI 라이브러리 | React | 18.3 | |
| 언어 | JavaScript (JSX) | - | TypeScript 미사용 |
| 번들러 / 개발 서버 | Vite | 5.4 | |
| 라우팅 | React Router | 6.26 | |
| HTTP 클라이언트 | fetch (브라우저 내장) | - | `api/client.js`에서 공통 처리, mock/실 API 분기 |
| UI 컴포넌트 | Radix UI (`react-select`) | 2.3 | `CustomSelect` 등에서 사용 |
| PDF 렌더링 | react-pdf | 10.5 | 계약서 원문 미리보기 |
| 스타일링 | 순수 CSS | - | Tailwind 미사용, `styles/` 아래 파일 단위 관리 |
| 아이콘 | 인라인 SVG 컴포넌트 | - | 외부 아이콘 패키지 미사용 |

## 실행

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # 프로덕션 빌드 (타입체크 없음)
npm run lint      # eslint .
npm run test      # node --test src/**/*.test.js
```

## 환경 변수

`.env`에 아래 값을 설정한다 (미설정 시 기본값으로 동작).

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | 실 백엔드 주소. 비워두면 dev 서버 프록시(`vite.config.js`)나 `vercel.json` rewrite를 탄다 |
| `VITE_API_KEY` | `""` | 백엔드 요청에 실어 보내는 `x-api-key` |
| `VITE_USE_REAL_API` | (미설정) | `"true"`가 아니면 항상 mock 모드로 동작 |

## Mock / 실 백엔드 연동

기본은 mock 모드다. `VITE_USE_REAL_API=true`를 설정해야 `api/client.js`가 실 API를 호출한다 — 빌드 모드가 아니라 이 값 하나로 분기하므로, 배포 환경별로 아무 때나 켜고 끌 수 있다.

로컬에서 실 백엔드와 붙일 때는 `vite.config.js`의 dev 서버 프록시가 `/api` 요청을 `http://localhost:8081`(Spring)로 넘긴다. Python(FastAPI, `:8000`)과 API 계약이 동일하므로 그쪽에 붙이려면 프록시 대상만 `8000`으로 바꾸면 된다.

## 인증 / PIN 세션

팀 단위 PIN으로 로그인한다. 세션 토큰은 URL이 아니라 `Authorization` 헤더로만 전달하며(`lib/pinSession.js`), 컴포넌트 트리 밖(예: 파일 다운로드 fetch)에서도 꺼내 쓸 수 있도록 모듈 스코프에 보관한다. 만료 임박 시 리스너를 통해 화면에 카운트다운을 알린다.

## 배포

- **Vercel**: `vercel.json`의 SPA rewrite로 모든 경로가 `index.html`로 fallback.
- **CI**(`.github/workflows/ci.yml`): `frontend-build` 잡이 PR/push마다 `npm install && npm run build`로 빌드만 확인한다. 배포는 Vercel 연동을 통해 별도로 이뤄진다.

## 구조

```
src/
├─ api/        # client(fetch 래퍼) · ApiError
├─ mock/       # mock 데이터 (contracts · uploadJobs · ipDirectory · verify · refs · search · auth)
├─ lib/        # evidence · contractPayload · contractStatus · ip · apiNormalizers · pinSession · securitySession · useRefs · useDebouncedEffect (+ 각 *.test.js)
├─ components/ # Layout · ConflictBadge · ConflictTimeline · CustomSelect · DuplicateIpPrompt · IpForm · Pagination · StatusBadge · contract/ · upload/ · icons/
├─ pages/      # ContractListPage · UploadPage · ContractDetailPage · SearchPage · IpManagementPage · ConflictCheckPage
├─ styles/     # index.css(디자인 토큰) · shared.css·mindex-ui.css(공통 컴포넌트) · layout.css · 페이지별 css
└─ labels.js   # 화면 표시용 한글 라벨 매핑
```

## 라우트

| 경로 | 화면 |
|---|---|
| `/` | 계약 목록 |
| `/upload`, `/upload/:tmpId` | 계약서 업로드·추출 (mode=new/revision/final은 쿼리 파라미터) |
| `/contracts/:id` | 계약 상세 |
| `/search` | 통합검색 |
| `/ips` | IP 관리 |
| `/upload/conflict` | 충돌 검토 |

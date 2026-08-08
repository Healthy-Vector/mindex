# 웹 대시보드 (Tier 2 · SFR-014)

계약 목록·상세·검색 3개 화면. React + Vite. UI 언어는 한국어만 지원한다.
여유 공수가 있을 때 진행하며, 1일 5시간 이하로 투입이 떨어지면 드롭 대상이다.
드롭 시 FastAPI `/docs` (Swagger UI) 화면을 대신 시연에 활용한다.

담당: P5

## 실행

```bash
npm install
npm run dev
```

`vite.config.js`에서 `/api` 요청을 백엔드(`localhost:8000`)로 프록시한다.
백엔드가 먼저 떠 있어야 데이터가 보인다.

## 구조

```
src/
├── main.jsx              라우터 진입점
├── App.jsx                라우트 정의 (목록 · 상세 · 검색)
├── api/client.js          fetch 래퍼 — app/api/contracts.py 경로와 1:1
├── components/
│   ├── Layout.jsx          공통 네비게이션
│   └── ConflictBadge.jsx   시연 구간 C(충돌 판정) 강조 배지
└── pages/
    ├── ContractListPage.jsx
    ├── ContractDetailPage.jsx    근거 인용(P-3) 표시 포함
    └── SearchPage.jsx            SFR-008/009 검색 연동
```

백엔드 `app/api/contracts.py`가 아직 `NotImplementedError`라서, 지금은 목록이 비어 있는 게 정상이다. P4가 엔드포인트를 채우면 바로 연동된다.

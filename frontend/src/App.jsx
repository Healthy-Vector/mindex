import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import ContractListPage from "./pages/ContractListPage.jsx";
import ContractDetailPage from "./pages/ContractDetailPage.jsx";
import SearchPage from "./pages/SearchPage.jsx";

// SFR-014 웹 대시보드 — 계약 목록·상세·검색 UI. UI 언어는 한국어만 지원한다.
// Tier 2(권장). 1일 5시간 이하로 투입이 떨어지면 드롭 대상 — 그때는
// 백엔드 FastAPI /docs (Swagger UI) 로 시연을 대체한다.
export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ContractListPage />} />
        <Route path="/contracts/:id" element={<ContractDetailPage />} />
        <Route path="/search" element={<SearchPage />} />
      </Routes>
    </Layout>
  );
}

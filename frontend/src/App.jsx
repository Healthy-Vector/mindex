import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import ContractListPage from "./pages/ContractListPage.jsx";

const UploadPage = lazy(() => import("./pages/UploadPage.jsx"));
const ContractDetailPage = lazy(() => import("./pages/ContractDetailPage.jsx"));
const SearchPage = lazy(() => import("./pages/SearchPage.jsx"));
const IpManagementPage = lazy(() => import("./pages/IpManagementPage.jsx"));
const ConflictCheckPage = lazy(() => import("./pages/ConflictCheckPage.jsx"));

// 계약 목록·상세·검색 웹 대시보드.
//
// "수정 이력 조회"와 "버전 비교" 화면은 뺐다 — 수정 이력은 사용자 테이블이 없어 "누가"
// 했는지 적을 근거가 없었고, 버전 비교는 팀과 논의된 적 없는 기능이었다. 필요해지면
// git 이력에서 ContractHistoryPage.jsx/ContractComparePage.jsx를 복원하면 된다.
export default function App() {
  return (
    <Layout>
      <Suspense fallback={<p className="mx-empty-state">화면 불러오는 중…</p>}>
        <Routes>
          <Route path="/" element={<ContractListPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/upload/:tmpId" element={<UploadPage />} />
          <Route path="/contracts/:id" element={<ContractDetailPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/ips" element={<IpManagementPage />} />
          <Route path="/upload/conflict" element={<ConflictCheckPage />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

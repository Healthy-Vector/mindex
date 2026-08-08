import { Link } from "react-router-dom";

export default function Layout({ children }) {
  return (
    <div>
      <header style={{ borderBottom: "1px solid #e2e8f0", padding: "12px 20px" }}>
        <strong>mindex</strong>
        <nav style={{ display: "inline-flex", gap: 16, marginLeft: 24 }}>
          <Link to="/">계약 목록</Link>
          <Link to="/search">검색</Link>
        </nav>
      </header>
      <main style={{ padding: 20 }}>{children}</main>
    </div>
  );
}

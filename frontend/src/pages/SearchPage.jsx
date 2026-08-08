import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";

// SFR-014 검색 UI + SFR-008/009 MCP·하이브리드 검색 API 연동.
// 시연 구간 D — 한국어 질의로 영문 계약을 찾는 것까지 이 화면에서 보여준다.
export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSearch(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await api.search(query);
      setResults(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1>검색</h1>
      <form onSubmit={handleSearch}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="예: 2027년 만료되는 일본 계약"
          style={{ width: 320 }}
        />
        <button type="submit" disabled={loading}>
          {loading ? "검색 중…" : "검색"}
        </button>
      </form>

      {error && <p style={{ color: "crimson" }}>오류: {error}</p>}

      {results && (
        <ul>
          {results.map((r) => (
            <li key={r.contract_id}>
              <Link to={`/contracts/${r.contract_id}`}>{r.title ?? r.contract_id}</Link>
              {r.score != null && <span> (유사도 {r.score.toFixed(2)})</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

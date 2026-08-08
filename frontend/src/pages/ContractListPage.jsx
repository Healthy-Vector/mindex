import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";

// SFR-014 — 계약 목록
export default function ContractListPage() {
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listContracts()
      .then(setContracts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>불러오는 중…</p>;
  if (error) return <p style={{ color: "crimson" }}>오류: {error}</p>;

  return (
    <div>
      <h1>계약 목록</h1>
      {contracts.length === 0 ? (
        <p>표시할 계약이 없습니다. (백엔드 /api/contracts 미구현 — app/api/contracts.py 참조)</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>상대방</th>
              <th>체결일</th>
              <th>버전</th>
            </tr>
          </thead>
          <tbody>
            {contracts.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link to={`/contracts/${c.id}`}>{c.id}</Link>
                </td>
                <td>{c.counterparty}</td>
                <td>{c.signed_date}</td>
                <td>{c.version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

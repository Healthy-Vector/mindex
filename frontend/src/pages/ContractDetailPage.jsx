import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client.js";
import ConflictBadge from "../components/ConflictBadge.jsx";

// SFR-014 — 계약 상세.
// 근거 인용(Evidence) 표시는 설계원칙 P-3(모든 추출값은 원문 인용 동반)를 화면에서 증명하는 자리다.
export default function ContractDetailPage() {
  const { id } = useParams();
  const [contract, setContract] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getContract(id)
      .then(setContract)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p style={{ color: "crimson" }}>오류: {error}</p>;
  if (!contract) return <p>불러오는 중…</p>;

  return (
    <div>
      <h1>계약 #{contract.id}</h1>
      <p>상대방: {contract.counterparty}</p>

      <h2>권리 목록</h2>
      <table>
        <thead>
          <tr>
            <th>지역</th>
            <th>법적 권리</th>
            <th>이용형태</th>
            <th>기간</th>
            <th>독점</th>
            <th>신뢰도</th>
            <th>근거 원문</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(contract.rights_grants ?? []).map((r) => (
            <tr key={r.id}>
              <td>{r.territory}</td>
              <td>{r.legal_right}</td>
              <td>{r.exploitation_mode}</td>
              <td>{r.period}</td>
              <td>{r.is_exclusive ? "예" : "아니오"}</td>
              <td>{r.confidence}</td>
              <td>
                <span title={r.source_quote}>{r.source_clause}</span>
              </td>
              <td>
                <ConflictBadge conflict={r.conflict} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import { STATUS_LABEL } from "../labels.js";
import { useDebouncedEffect } from "../lib/useDebouncedEffect.js";
import { computeContractStatus } from "../lib/contractStatus.js";
import StatusBadge from "../components/StatusBadge.jsx";
import Pagination from "../components/Pagination.jsx";
import "../styles/contract-list-page.css";

const PAGE_SIZE = 10;

// 계약 목록 — GET /api/contracts가 지원하는 page/size/include_processing만 사용한다.
export default function ContractListPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [toast, setToast] = useState(location.state?.toast ?? null);
  const [contracts, setContracts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [includeProcessing, setIncludeProcessing] = useState(true);

  // location.state는 캡처만 하고 바로 지운다 — 안 그러면 새로고침·뒤로가기 때 토스트가 다시 뜬다.
  useEffect(() => {
    if (location.state?.toast) navigate(".", { replace: true, state: {} });
  }, []);

  useDebouncedEffect(
    () => {
      let cancelled = false;
      setLoading(true);
      setError(null);
      api
        .listContracts({
          includeProcessing,
          page,
          size: PAGE_SIZE,
        })
        .then((res) => {
          if (cancelled) return;
          setContracts(res.items);
          setTotal(res.total);
        })
        .catch((err) => {
          if (!cancelled) setError(err.message);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    },
    [includeProcessing, page],
  );

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = (page - 1) * PAGE_SIZE;

  return (
    <div>
      {toast && (
        <div className="list-toast">
          {toast}
          <button type="button" className="mx-link-btn list-toast-close" onClick={() => setToast(null)} aria-label="닫기">
            ×
          </button>
        </div>
      )}

      <div className="mx-page-header">
        <h2 className="mx-heading-lg">계약 목록</h2>
        <Link to="/upload" className="mx-btn mx-btn-primary">
          + 새 계약 등록
        </Link>
      </div>

      <div className="list-filters">
        <span className="list-total-label">
          전체 항목 {total}건
        </span>
        <span className="mx-divider-v" />
        <label className="list-processing-toggle">
          <button
            type="button"
            className="mx-switch"
            data-on={includeProcessing}
            role="switch"
            aria-checked={includeProcessing}
            onClick={() => {
              setIncludeProcessing((value) => !value);
              setPage(1);
            }}
          >
            <span className="mx-switch-thumb" />
          </button>
          처리 중 작업 포함
        </label>
      </div>

      {loading && <p>불러오는 중…</p>}
      {error && <div className="mx-alert-banner">API 연결 실패: {error}</div>}

      {!loading && !error && (
        <div className="mx-card" style={{ padding: 0, overflow: "hidden" }}>
          {contracts.length === 0 ? (
            <p className="list-table-empty">표시할 계약이 없습니다.</p>
          ) : (
            <div className="mx-table-scroll">
            <table className="mx-table list-table">
              <colgroup>
                <col style={{ width: "25%" }} />
                <col style={{ width: "27%" }} />
                <col style={{ width: "14%" }} />
                <col style={{ width: "18%" }} />
                <col style={{ width: "16%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={{ paddingLeft: 20 }}>계약서</th>
                  <th>계약 당사자 (갑/을)</th>
                  <th>계약 상태</th>
                  <th>권리 유효 상태</th>
                  <th style={{ paddingRight: 20 }}>서명일</th>
                </tr>
              </thead>
              <tbody>
                {contracts.map((c) => {
                  if (c.kind === "processing") {
                    return (
                      <tr key={`processing-${c.tmpid}`}>
                        <td style={{ paddingLeft: 20 }}>
                          <Link to={`/upload/${c.tmpid}`} className="list-row-title mx-cell-truncate" title={c.filename}>
                            {c.filename}
                          </Link>
                          <div className="list-row-sub">추출 작업: {c.tmpid}</div>
                        </td>
                        <td>—</td>
                        <td><span className="mx-tag mx-tag-outline">{processingLabel(c)}</span></td>
                        <td colSpan={2} className="mx-muted">업로드 처리를 계속하려면 파일명을 선택하세요.</td>
                      </tr>
                    );
                  }
                  const grantor = c.grantor ?? "—";
                  const grantee = c.grantee ?? "—";
                  const title = c.title ?? `계약 #${c.contractId}`;
                  const status = displayStatus(c);
                  return (
                    <tr key={c.contractId}>
                      <td style={{ paddingLeft: 20 }}>
                        <Link to={`/contracts/${c.contractId}`} className="list-row-title mx-cell-truncate" title={title}>
                          {title}
                        </Link>
                        <div className="list-row-sub">계약 ID: {c.contractId} · {STATUS_LABEL[c.status] ?? c.status}</div>
                      </td>
                      <td className="mx-cell-truncate" title={`갑: ${grantor} · 을: ${grantee}`}>
                        {grantor} <span className="mx-muted">/</span> {grantee}
                      </td>
                      <td>
                        <span className="mx-tag mx-tag-neutral">{STATUS_LABEL[c.status] ?? c.status}</span>
                      </td>
                      <td>
                        <StatusBadge status={status} />
                      </td>
                      <td style={{ paddingRight: 20 }}>
                        {formatDate(c.signedDate)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          )}
        </div>
      )}

      {!loading && !error && total > 0 && (
        <Pagination page={page} totalPages={totalPages} totalItems={total} pageStart={pageStart} pageSize={PAGE_SIZE} onPageChange={setPage} />
      )}
    </div>
  );
}

function displayStatus(contract) {
  if (contract.hasConflict) return { key: "conflicted", label: "충돌" };
  if (contract.status === "draft") return { key: "unknown", label: "미적용" };
  const key = contract.displayState?.toLowerCase() ?? "unknown";
  const agreementDate = contract.agreementDate ?? contract.signedDate;
  if (key === "before_term" && agreementDate && contract.period?.start && contract.period?.end) {
    const computed = computeContractStatus({
      signedDate: agreementDate,
      periodStart: contract.period.start,
      periodEnd: contract.period.end,
    });
    if (computed.key === "before_term") return computed;
  }
  const daysToExpiry = contract.daysToExpiry ?? null;
  const tier = key === "expiring" ? (daysToExpiry <= 30 ? 30 : daysToExpiry <= 60 ? 60 : 90) : null;
  return { key, daysToExpiry, tier, label: contract.displayStateLabel };
}

function processingLabel(item) {
  if (item.status === "QUEUED") return "대기 중";
  if (item.status === "FAILED") return "처리 실패";
  return item.stage === "LLM" ? "AI 추출 중" : "OCR 처리 중";
}

function formatDate(value) {
  return value ? value.replaceAll("-", ".") : "—";
}

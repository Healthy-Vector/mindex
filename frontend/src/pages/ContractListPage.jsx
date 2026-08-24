import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import { STATUS_LABEL } from "../labels.js";
import { useDebouncedEffect } from "../lib/useDebouncedEffect.js";
import { useRefs } from "../lib/useRefs.js";
import { computeContractStatus } from "../lib/contractStatus.js";
import StatusBadge from "../components/StatusBadge.jsx";
import CustomSelect from "../components/CustomSelect.jsx";
import Pagination from "../components/Pagination.jsx";
import "../styles/contract-list-page.css";

const FILTER_DEFS = [{ key: "exclusive", label: "독점 라이선스" }];

const PAGE_SIZE = 10;

const STATUS_FILTER_DEFS = [
  { key: "all", label: "전체 상태" },
  { key: "draft", label: "초안" },
  { key: "signed", label: "서명 완료" },
  { key: "cancelled", label: "취소/해지" },
];

const SORT_OPTIONS = [
  { value: "recent", label: "최근 등록순" },
  { value: "expiring", label: "만료 임박순" },
];

// 계약 목록 — GET /api/contracts로 검색/필터/페이지네이션.
export default function ContractListPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { territoryLabel, territoryOptions, legalRightLabel, exploitationModeLabel } = useRefs();
  const territoryFilterDefs = [
    { key: "all", label: "전체 지역" },
    ...territoryOptions.map(({ value, label }) => ({ key: value, label })),
  ];
  const [toast, setToast] = useState(location.state?.toast ?? null);
  const [contracts, setContracts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [activeFilters, setActiveFilters] = useState(() => new Set());
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [territoryFilter, setTerritoryFilter] = useState("all");
  const [sort, setSort] = useState("recent");

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
          q: search.trim() || undefined,
          status: statusFilter === "all" ? undefined : [statusFilter],
          exclusiveOnly: activeFilters.has("exclusive"),
          territory: territoryFilter !== "all" ? territoryFilter : undefined,
          includeProcessing: true,
          sort,
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
    [search, activeFilters, statusFilter, territoryFilter, sort, page],
  );

  function toggleFilter(key) {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setPage(1);
  }

  function handleTerritoryChange(key) {
    setTerritoryFilter(key);
    setPage(1);
  }

  function clearFilters() {
    setActiveFilters(new Set());
    setPage(1);
  }

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

      <div className="list-toolbar">
        <input
          className="mx-input"
          style={{ flex: 1 }}
          placeholder="IP명, 파트너사명 검색..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
      </div>

      <div className="list-filters">
        <span className="list-total-label">
          전체 계약 {total}건
        </span>
        <span className="mx-divider-v" />
        {FILTER_DEFS.map((def) => (
          <button
            key={def.key}
            type="button"
            onClick={() => toggleFilter(def.key)}
            className={`mx-tag mx-chip-btn ${activeFilters.has(def.key) ? "mx-tag-accent" : "mx-tag-neutral"}`}
          >
            {def.label}
          </button>
        ))}
        {activeFilters.size > 0 && (
          <span className="list-filter-summary">
            적용된 필터: {activeFilters.size}개 ·{" "}
            <button type="button" onClick={clearFilters} className="mx-link-btn list-filter-reset">
              초기화
            </button>
          </span>
        )}
        <span className="mx-divider-v" />
        <div className="list-status-select">
          <CustomSelect
            ariaLabel="지역 필터"
            value={territoryFilter}
            onChange={handleTerritoryChange}
            options={territoryFilterDefs.map((def) => ({ value: def.key, label: def.label }))}
          />
        </div>
        <div className="list-status-select">
          <CustomSelect
            ariaLabel="상태값 필터"
            value={statusFilter}
            onChange={(value) => { setStatusFilter(value); setPage(1); }}
            options={STATUS_FILTER_DEFS.map((def) => ({ value: def.key, label: def.label }))}
          />
        </div>
        <div className="list-status-select">
          <CustomSelect ariaLabel="정렬" value={sort} onChange={(value) => { setSort(value); setPage(1); }} options={SORT_OPTIONS} />
        </div>
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
                <col style={{ width: "18%" }} />
                <col style={{ width: "19%" }} />
                <col style={{ width: "14%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "16%" }} />
                <col style={{ width: "12%" }} />
                <col style={{ width: "11%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={{ paddingLeft: 20 }}>IP명 / 서비스 타이틀</th>
                  <th>계약 당사자 (갑/을)</th>
                  <th>상태값</th>
                  <th>계약 유효 지역</th>
                  <th>주요 권리 유형</th>
                  <th>기간</th>
                  <th style={{ paddingRight: 20 }}>독점 여부</th>
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
                        <td colSpan={4} className="mx-muted">업로드 처리를 계속하려면 파일명을 선택하세요.</td>
                      </tr>
                    );
                  }
                  const grantor = c.grantor ?? "—";
                  const grantee = c.grantee ?? "—";
                  const title = c.serviceTitle ?? c.ipTitle ?? c.grantee;
                  const territory = formatCodes(c.territories, territoryLabel);
                  const rightsType = formatRights(c.mainLegalRights, c.mainExploitationModes, legalRightLabel, exploitationModeLabel);
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
                        <StatusBadge status={status} />
                      </td>
                      <td className="mx-cell-truncate" title={territory}>
                        {territory}
                      </td>
                      <td className="mx-cell-truncate" title={rightsType}>
                        {rightsType}
                      </td>
                      <td>{formatPeriod(c.period)}</td>
                      <td style={{ paddingRight: 20 }}>
                        <span className={`mx-tag ${c.isExclusive ? "mx-tag-accent" : "mx-tag-neutral"}`}>
                          {c.isExclusive ? "독점/단독" : "비독점"}
                        </span>
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

function formatCodes(codes = [], labels) {
  if (!codes.length) return "—";
  const values = codes.map((code) => labels[code] ?? code);
  return values.length > 2 ? `${values.slice(0, 2).join(" · ")} 외 ${values.length - 2}` : values.join(" · ");
}

function formatRights(legalRights = [], exploitationModes = [], legalLabels, modeLabels) {
  const legal = formatCodes(legalRights, legalLabels);
  const mode = formatCodes(exploitationModes, modeLabels);
  return legal === "—" && mode === "—" ? "—" : `${legal} · ${mode}`;
}

function processingLabel(item) {
  if (item.jobStatus === "QUEUED") return "대기 중";
  if (item.jobStatus === "FAILED") return "처리 실패";
  return item.stage === "LLM" ? "AI 추출 중" : "OCR 처리 중";
}

function formatPeriod(period) {
  if (!period?.start) return "—";
  const [y1, mo1] = period.start.split("-");
  if (!period.end) return `${y1}.${mo1} ~`;
  const [y2, mo2] = period.end.split("-");
  return `${y1}.${mo1} ~ ${y2}.${mo2}`;
}

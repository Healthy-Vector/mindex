import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { isIpActive } from "../lib/ip.js";
import { LANG_LABEL } from "../labels.js";
import { useDebouncedEffect } from "../lib/useDebouncedEffect.js";
import { useRefs } from "../lib/useRefs.js";
import IpForm, { REQUIRED_LANGS, emptyIpForm, ipFormFromIp } from "../components/IpForm.jsx";
import DuplicateIpPrompt from "../components/DuplicateIpPrompt.jsx";
import Pagination from "../components/Pagination.jsx";
import "../styles/ip-management-page.css";

const PAGE_SIZE = 10;
const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

// IP 마스터 데이터 조회. 등록/수정은 목록 위에 뜨는 팝업에서 한다 — 짧은 폼이라 목록의
// 스크롤·검색 상태를 유지하는 쪽이 전용 페이지 이동보다 낫다고 판단.
export default function IpManagementPage() {
  const { ipKindLabel } = useRefs();
  const [ips, setIps] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [showInactive, setShowInactive] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedIp, setSelectedIp] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const [formModal, setFormModal] = useState(null); // null | { mode: "create" } | { mode: "edit", ip }
  const [duplicatePrompt, setDuplicatePrompt] = useState(null); // { title, ipId } | null
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);

  // API 명세서 #12의 page/size를 그대로 사용한다. 검색·비활성 포함 여부도 서버에 전달해
  // 전체 결과 기준 total과 현재 10개가 항상 일치하게 한다.
  useDebouncedEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .searchIps(query, { includeInactive: showInactive, page, size: PAGE_SIZE })
      .then((result) => {
        if (!cancelled) {
          setIps(result.items);
          setTotal(result.total);
        }
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
  }, [query, showInactive, page, refreshKey]);

  // 목록 행에는 표시용 데이터가 충분히 들어오더라도, 상세 패널은 단건 API를 기준으로
  // 표시한다. 수정 직후 refreshKey가 바뀌면 선택한 IP 상세도 다시 조회한다.
  useEffect(() => {
    if (selectedId == null) {
      setSelectedIp(null);
      setDetailError(null);
      return undefined;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    api
      .getIp(selectedId)
      .then((ip) => {
        if (!cancelled) setSelectedIp(ip);
      })
      .catch((err) => {
        if (!cancelled) {
          setSelectedIp(null);
          setDetailError(err.message || "IP 상세 정보를 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = (page - 1) * PAGE_SIZE;

  function handleSaveForm(form) {
    const save = formModal.mode === "edit" ? api.updateIp(formModal.ip.id, form) : api.createIp(form);
    save
      .then((saved) => {
        setSelectedId(saved.id);
        setFormModal(null);
        setPage(1);
        setRefreshKey((value) => value + 1);
      })
      .catch((err) => {
        // API 명세서 #13 — 같은 정규화 키의 IP가 이미 있으면 409 + 기존 ipId. 빨간 에러
        // 배너 대신 "기존 IP 사용" 복구 동작을 제안한다.
        if (err.status === 409 && err.body?.code === "DUPLICATE_IP") {
          setFormModal(null);
          setDuplicatePrompt({ title: err.body.title, ipId: err.body.ipId });
        } else {
          setError(err.message);
        }
      });
  }

  return (
    <div>
      <div className="mx-page-header">
        <div>
          <h2 className="mx-heading-lg">IP 관리</h2>
          <div className="mx-text-sm mx-muted">IP 마스터 데이터를 등록·조회·수정합니다. 삭제는 지원하지 않습니다 — 비활성화로 대신합니다.</div>
        </div>
        <button type="button" className="mx-btn mx-btn-primary" onClick={() => setFormModal({ mode: "create" })}>
          + 새 IP 등록
        </button>
      </div>

      <div className="ipmgmt-toolbar">
        <input
          className="mx-input"
          style={{ flex: 1 }}
          placeholder="IP명 또는 별칭(한/영/일) 검색..."
          value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
        />
        <label className="ipmgmt-inactive-toggle">
          <button
            type="button"
            className="mx-switch"
            data-on={showInactive}
            role="switch"
            aria-checked={showInactive}
            onClick={() => { setShowInactive((v) => !v); setPage(1); }}
          >
            <span className="mx-switch-thumb" />
          </button>
          비활성 IP 포함
        </label>
      </div>

      {error && <div className="mx-alert-banner mx-mb-20">API 연결 실패: {error}</div>}

      <div className="ipmgmt-grid">
        <div>
        <div className="mx-card" style={{ padding: 0, overflow: "hidden" }}>
          {loading ? (
            <p className="list-table-empty">불러오는 중…</p>
          ) : ips.length === 0 ? (
            <p className="list-table-empty">표시할 IP가 없습니다.</p>
          ) : (
            <div className="mx-table-scroll">
            <table className="mx-table ipmgmt-table">
              <colgroup>
                <col style={{ width: "26%" }} />
                <col style={{ width: "20%" }} />
                <col style={{ width: "36%" }} />
                <col style={{ width: "18%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={{ paddingLeft: 20 }}>타이틀</th>
                  <th>유형</th>
                  <th>별칭</th>
                  <th style={{ paddingRight: 20 }}>상태</th>
                </tr>
              </thead>
              <tbody>
                {ips.map((ip) => (
                  <tr
                    key={ip.id}
                    className={`ipmgmt-row${String(selectedId) === String(ip.id) ? " ipmgmt-row--active" : ""}`}
                    onClick={() => setSelectedId(ip.id)}
                  >
                    <td style={{ paddingLeft: 20 }}>
                      <span className="list-row-title mx-cell-truncate" title={ip.title}>
                        {ip.title}
                      </span>
                    </td>
                    <td className="mx-cell-truncate" title={ipKindLabel[ip.kind] ?? ip.kind}>
                      {ipKindLabel[ip.kind] ?? ip.kind}
                    </td>
                    <td
                      className="mx-text-xs mx-muted mx-cell-truncate"
                      title={ip.aliases.map((a) => a.text).join(" · ")}
                    >
                      {ip.aliases.map((a) => a.text).slice(0, 2).join(" · ")}
                      {ip.aliases.length > 2 ? ` 외 ${ip.aliases.length - 2}` : ""}
                    </td>
                    <td style={{ paddingRight: 20 }}>
                      <span className={`mx-tag ${isIpActive(ip) ? "mx-tag-accent" : "mx-tag-neutral"}`}>
                        {isIpActive(ip) ? "활성" : "비활성"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>

        {!loading && !error && total > 0 && (
          <Pagination
            page={page}
            totalPages={totalPages}
            totalItems={total}
            pageStart={pageStart}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        )}
        </div>

        <div className="ipmgmt-panel">
          {detailLoading ? (
            <div className="mx-card mx-card-pad"><p className="mx-empty-state">IP 상세 정보를 불러오는 중…</p></div>
          ) : detailError ? (
            <div className="mx-card mx-card-pad"><div className="mx-alert-banner">{detailError}</div></div>
          ) : selectedIp ? (
            <IpDetail ip={selectedIp} onEdit={() => setFormModal({ mode: "edit", ip: selectedIp })} />
          ) : (
            <div className="mx-card mx-card-pad">
              <p className="mx-empty-state">목록에서 IP를 선택하거나 새로 등록하세요.</p>
            </div>
          )}
        </div>
      </div>

      {formModal && (
        <div className="ipform-overlay" onClick={() => setFormModal(null)}>
          <div className="ipform-modal" onClick={(e) => e.stopPropagation()}>
            <IpForm
              mode={formModal.mode === "edit" ? "edit" : "create"}
              heading={formModal.mode === "edit" ? "IP 정보 수정" : "새 IP 등록"}
              initial={formModal.mode === "edit" ? ipFormFromIp(formModal.ip) : emptyIpForm()}
              onSave={handleSaveForm}
              onCancel={() => setFormModal(null)}
            />
          </div>
        </div>
      )}

      {duplicatePrompt && (
        <DuplicateIpPrompt
          title={duplicatePrompt.title}
          onCancel={() => setDuplicatePrompt(null)}
          onUseExisting={() => {
            setSelectedId(duplicatePrompt.ipId);
            setDuplicatePrompt(null);
          }}
        />
      )}
    </div>
  );
}

function IpDetail({ ip, onEdit }) {
  const { ipKindLabel } = useRefs();
  const byLang = REQUIRED_LANGS.map((lang) => ({ lang, entries: ip.aliases.filter((a) => a.lang === lang) }));
  return (
    <div className="mx-card mx-card-pad">
      <div className="mx-flex-between mx-mb-20">
        <h5 className="mx-heading-panel" style={{ margin: 0 }}>{ip.title}</h5>
        <span className={`mx-tag ${isIpActive(ip) ? "mx-tag-accent" : "mx-tag-neutral"}`}>{isIpActive(ip) ? "활성" : "비활성"}</span>
      </div>

      <div className="ipmgmt-detail-row">
        <span className="mx-muted">유형</span>
        <b>{ipKindLabel[ip.kind] ?? ip.kind ?? "—"}</b>
      </div>
      <div className="ipmgmt-detail-row">
        <span className="mx-muted">등록일</span>
        <b>{formatCreatedAt(ip.createdAt)}</b>
      </div>

      <div className="ipmgmt-alias-groups">
        {byLang.map(({ lang, entries }) => (
          <div key={lang} className="ipmgmt-alias-group">
            <div className="ipmgmt-alias-group-label">{LANG_LABEL[lang]}</div>
            {entries.length === 0 ? (
              <span className="mx-empty-state">등록된 별칭 없음</span>
            ) : (
              entries.map((a, i) => (
                <div key={i} className="ipmgmt-alias-item">
                  <span className="mx-tag mx-tag-outline">{a.aliasType}</span>
                  {a.text}
                </div>
              ))
            )}
          </div>
        ))}
      </div>

      <div className="ipmgmt-detail-actions">
        <button type="button" className="mx-btn mx-btn-secondary" onClick={onEdit}>
          수정
        </button>
      </div>
    </div>
  );
}

function formatCreatedAt(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : CREATED_AT_FORMATTER.format(date);
}

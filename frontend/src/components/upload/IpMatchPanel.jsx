import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client.js";
import DuplicateIpPrompt from "../DuplicateIpPrompt.jsx";
import IpForm, { emptyIpForm } from "../IpForm.jsx";
import { normalizeIp } from "../../lib/apiNormalizers.js";
import { useDebouncedEffect } from "../../lib/useDebouncedEffect.js";
import { useRefs } from "../../lib/useRefs.js";

export default function IpMatchPanel({ ipMatch, setIpMatch, showHeading = true, disabled = false }) {
  const { ipKindLabel } = useRefs();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [duplicatePrompt, setDuplicatePrompt] = useState(null);
  const [results, setResults] = useState([]);
  const wrapRef = useRef(null);

  useDebouncedEffect(() => {
    if (!open) return;
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2) {
      setResults([]);
      return;
    }
    api.matchIps(normalizedQuery)
      .then((candidates) => setResults(candidates.map(normalizeIp)))
      .catch(() => setResults([]));
  }, [open, query], 200);

  useEffect(() => {
    if (!open) return;
    function handleOutside(event) {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) setOpen(false);
    }
    function handleKey(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  function selectIp(ip) {
    setIpMatch({ status: "manual", ip });
    setOpen(false);
    setQuery("");
  }

  return (
    <div className={`upload-ipmatch${showHeading ? " mx-mb-20" : " upload-ipmatch--inline"}`}>
      {showHeading && <h5 className="mx-heading-panel">IP 매칭</h5>}
      <div className="mx-combobox" ref={wrapRef}>
        <button type="button" className="mx-input mx-select-trigger" onClick={() => { if (!disabled) setOpen((value) => !value); }} aria-expanded={open} disabled={disabled}>
          {ipMatch ? (
            <span className="mx-combobox-trigger-value">
              <span className="mx-tag mx-tag-accent">{ipMatch.status === "auto" ? "자동 연결됨" : "선택됨"}</span>
              <b className="upload-ipmatch-title">{ipMatch.ip.title}</b>
              <span className="mx-muted mx-text-xs">IP #{ipMatch.ip.id} · {ipKindLabel[ipMatch.ip.kind] ?? ipMatch.ip.kind ?? "유형 미지정"}</span>
            </span>
          ) : <span className="mx-muted">IP를 선택하세요</span>}
          <span className="mx-select-chevron">▾</span>
        </button>

        {open && (
          <div className="mx-combobox-panel">
            <input className="mx-input mx-combobox-search" placeholder="IP명 또는 별칭 검색..." value={query} onChange={(event) => setQuery(event.target.value)} autoFocus />
            <div className="mx-combobox-list">
              {results.length > 0 ? results.map((ip) => (
                <button key={ip.id} type="button" className={`mx-select-option${ipMatch?.ip.id === ip.id ? " mx-combobox-option--checked" : ""}`} onClick={() => selectIp(ip)}>
                  <span className="upload-ipmatch-result-title">{ip.title}</span>
                  <span className="mx-muted mx-text-xs">
                    {ipKindLabel[ip.kind] ?? ip.kind ?? "유형 미지정"}{ip.matchedAlias && ` · 별칭 "${ip.matchedAlias}"로 일치`}
                  </span>
                </button>
              )) : <p className="mx-empty-state">{query.trim().length < 2 ? "IP명 또는 별칭을 2자 이상 입력하세요." : "검색 결과가 없습니다."}</p>}
            </div>
            <button type="button" className="mx-btn mx-btn-secondary mx-combobox-create-btn" onClick={() => { setOpen(false); setShowCreateModal(true); }}>
              + 새 IP로 등록
            </button>
          </div>
        )}
      </div>

      {showCreateModal && (
        <div className="detail-pin-wrap detail-extend-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="ipform-modal" onClick={(event) => event.stopPropagation()}>
            <IpForm
              heading="신규 IP 등록"
              initial={emptyIpForm(query)}
              onCancel={() => setShowCreateModal(false)}
              onSave={(form) => api.createIp(form).then((created) => {
                selectIp(created);
                setShowCreateModal(false);
              }).catch((error) => {
                if (error.status === 409 && error.body?.code === "DUPLICATE_IP") {
                  setShowCreateModal(false);
                  setDuplicatePrompt({ title: error.body.title, ipId: error.body.ipId });
                }
              })}
            />
          </div>
        </div>
      )}

      {duplicatePrompt && (
        <DuplicateIpPrompt
          title={duplicatePrompt.title}
          onCancel={() => setDuplicatePrompt(null)}
          onUseExisting={() => api.getIp(duplicatePrompt.ipId).then((ip) => {
            if (ip) selectIp(ip);
            setDuplicatePrompt(null);
          })}
        />
      )}
    </div>
  );
}

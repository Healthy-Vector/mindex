import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import CustomSelect from "../CustomSelect.jsx";
import { EXCLUSIVITY_OPTIONS } from "../../labels.js";
import { firstEvidenceEntry, updateFirstEvidenceEntry } from "../../lib/evidence.js";
import { useRefs } from "../../lib/useRefs.js";
import IpMatchPanel from "./IpMatchPanel.jsx";

export function RegistrationContextEditor({ mode, entryMode, ipMatch, selectedContractId, onModeChange, onContractChange }) {
  const finalLocked = entryMode === "final";
  return (
    <CollapsibleCard title="등록 대상 확인" className="upload-hitl-section upload-registration-context">
      <div className="ipform-field-label">최종 등록 유형</div>
      <div className="mx-seg upload-mode-selector" role="group" aria-label="최종 등록 유형">
        <button type="button" className={`mx-seg-opt${mode === "new" ? " active" : ""}`} disabled={finalLocked} onClick={() => onModeChange("new")}>신규 계약</button>
        <button type="button" className={`mx-seg-opt${mode === "revision" ? " active" : ""}`} disabled={finalLocked} onClick={() => onModeChange("revision")}>버전 계약</button>
        <button type="button" className={`mx-seg-opt${mode === "final" ? " active" : ""}`} disabled>최종 계약</button>
      </div>
      <div className="mx-text-xs mx-muted upload-mode-help">
        {finalLocked ? "최종 계약은 계약 상세에서만 진입할 수 있으며 등록 유형을 변경할 수 없습니다." : "HITL 검증 결과에 따라 신규 계약과 버전 계약을 전환할 수 있습니다."}
      </div>
      {finalLocked
        ? <ReadonlyRegistrationTarget contractId={selectedContractId} />
        : mode === "revision" && <TargetContractPicker ip={ipMatch?.ip} value={selectedContractId} onChange={onContractChange} />}
    </CollapsibleCard>
  );
}

function ReadonlyRegistrationTarget({ contractId }) {
  return (
    <div className="upload-readonly-target">
      <label><span className="ipform-field-label">대상 기존 계약</span><input className="mx-input" disabled value={contractId ? `계약 #${contractId}` : "계약 정보 없음"} /></label>
    </div>
  );
}

function TargetContractPicker({ ip, value, onChange }) {
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!ip) { setContracts([]); return; }
    let cancelled = false;
    setLoading(true);
    api.listContracts({ ipId: ip.id, includeProcessing: false, sort: "recent", page: 1, size: 100 })
      .then((result) => { if (!cancelled) setContracts((result.items ?? []).filter((item) => item.kind === "contract")); })
      .catch(() => { if (!cancelled) setContracts([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ip]);

  const options = contracts.map((contract) => ({ value: String(contract.contractId), label: `#${contract.contractId} ${contract.serviceTitle ?? contract.ipTitle}` }));
  if (value && !options.some((option) => option.value === String(value))) options.unshift({ value: String(value), label: `#${value} 현재 대상 계약` });
  return (
    <div className="upload-target-contract">
      <div className="ipform-field-label">대상 기존 계약</div>
      <CustomSelect ariaLabel="대상 기존 계약" value={value ? String(value) : ""} onChange={onChange} options={options} placeholder={loading ? "계약 목록 불러오는 중…" : ip ? "기존 계약을 선택하세요" : "IP를 먼저 선택하세요"} disabled={!ip || loading} />
      <div className="mx-text-xs mx-muted upload-mode-help">선택한 IP에 속한 계약 중 새 버전을 추가할 계약을 선택합니다.</div>
    </div>
  );
}

export function HitlReviewEditor({ contractInfo, setContractInfo, rights, onUpdateRight, ipMatch, setIpMatch, ipLocked = false }) {
  const refs = useRefs();
  const updateContract = (key, next) => setContractInfo((previous) => ({ ...previous, [key]: next }));
  const assets = ipMatch?.ip?.assets ?? [];
  const assetOptions = assets.map((asset) => ({ value: String(asset.contentAssetId), label: `${asset.title || "권리 대상"} · ${asset.scopeType ?? "범위 미지정"} (#${asset.contentAssetId})` }));

  return (
    <section className="upload-hitl-section upload-hitl-review" aria-label="AI 추출 결과 수정">
      <CollapsibleCard title="IP 및 권리 대상" className="upload-review-section">
        <div className="upload-review-basic-table">
          <BasicReviewRow
            label="대상 IP"
            value={<IpMatchPanel ipMatch={ipMatch} setIpMatch={setIpMatch} showHeading={false} disabled={ipLocked} />}
          />
          {rights.map((right, index) => (
            <BasicReviewRow
              key={`asset-${index}`}
              label={rights.length > 1 ? `Content Asset #${index + 1}` : "Content Asset"}
              value={<CustomSelect ariaLabel={`Content Asset ${index + 1}`} value={right.contentAssetId == null ? "" : String(right.contentAssetId)} onChange={(next) => onUpdateRight(index, { contentAssetId: Number(next) })} options={assetOptions} placeholder={assets.length ? "권리 대상을 선택하세요" : "IP를 먼저 선택하세요"} disabled={!assets.length || ipLocked} />}
            />
          ))}
        </div>
      </CollapsibleCard>

      <CollapsibleCard title="계약 기본 정보" className="upload-review-section">
        <div className="upload-review-basic-table">
          <BasicReviewRow label="권리 허락자" value={<ReviewInput ariaLabel="권리 허락자" value={contractInfo.grantor} onChange={(next) => updateContract("grantor", next)} />} />
          <BasicReviewRow label="권리 이용자" value={<ReviewInput ariaLabel="권리 이용자" value={contractInfo.grantee} onChange={(next) => updateContract("grantee", next)} />} />
        </div>
      </CollapsibleCard>

      <CollapsibleCard title="권리 조건" className="upload-review-section">
        <div className="upload-review-table">
          <div className="upload-review-row upload-review-head">
            <div>필드명</div>
            <div>추출값 (제안)</div>
            <div>근거조항</div>
          </div>
          {rights.length === 0 && <p className="mx-empty-state">OCR/LLM에서 추출된 권리가 없습니다. 원문을 확인한 뒤 다시 추출해 주세요.</p>}
          {rights.map((right, index) => (
            <div className="upload-review-right" key={index}>
              {rights.length > 1 && <div className="upload-review-right-title">권리 #{index + 1}</div>}
              <ReviewRow
                label="이용지역"
                value={<TerritoryEditor value={right.territories ?? []} refs={refs} onChange={(territories) => onUpdateRight(index, { territories })} />}
                evidence={<EvidenceCell evidence={right.evidence} field="territory" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="법적 권리"
                value={<CustomSelect ariaLabel={`법적 권리 ${index + 1}`} value={right.legalRight} onChange={(next) => onUpdateRight(index, { legalRight: next })} options={refs.legalRightOptions} />}
                evidence={<EvidenceCell evidence={right.evidence} field="legalRight" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="사업적 이용형태"
                value={<CustomSelect ariaLabel={`사업적 이용형태 ${index + 1}`} value={right.exploitationMode} onChange={(next) => onUpdateRight(index, { exploitationMode: next })} options={refs.exploitationModeOptions} />}
                evidence={<EvidenceCell evidence={right.evidence} field="exploitationMode" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="독점 형태"
                value={<CustomSelect ariaLabel={`독점 형태 ${index + 1}`} value={right.exclusivity} onChange={(next) => onUpdateRight(index, { exclusivity: next })} options={EXCLUSIVITY_OPTIONS} />}
                evidence={<EvidenceCell evidence={right.evidence} field="exclusivity" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="라이선스 유효 기간"
                value={(
                  <div className="upload-review-period">
                    <ReviewInput ariaLabel={`시작일 ${index + 1}`} type="date" value={right.period?.start} onChange={(next) => onUpdateRight(index, { period: { ...right.period, start: next } })} />
                    <span>~</span>
                    <ReviewInput ariaLabel={`종료일 ${index + 1}`} type="date" value={right.period?.end} onChange={(next) => onUpdateRight(index, { period: { ...right.period, end: next } })} />
                  </div>
                )}
                evidence={<EvidenceCell evidence={right.evidence} field="period" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
            </div>
          ))}
        </div>
      </CollapsibleCard>
    </section>
  );
}

function CollapsibleCard({ title, className = "", children }) {
  const [open, setOpen] = useState(true);
  return (
    <details className={`mx-card upload-collapsible-card ${className}`} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="upload-card-summary">
        <h5 className="mx-heading-panel">{title}</h5>
        <span className="upload-card-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div className="upload-card-body">{children}</div>
    </details>
  );
}

function BasicReviewRow({ label, value }) {
  return (
    <div className="upload-review-basic-row">
      <div className="upload-review-label">{label}</div>
      <div className="upload-review-value">{value}</div>
    </div>
  );
}

function ReviewRow({ label, value, evidence = null }) {
  return (
    <div className="upload-review-row">
      <div className="upload-review-label">{label}</div>
      <div className="upload-review-value">{value}</div>
      {evidence ?? <div className="upload-review-evidence"><span className="mx-muted">—</span></div>}
    </div>
  );
}

function ReviewInput({ ariaLabel, value, onChange, type = "text" }) {
  return <input aria-label={ariaLabel} className="mx-input" type={type} value={value ?? ""} onChange={(event) => onChange(event.target.value)} />;
}

function TerritoryEditor({ value, refs, onChange }) {
  const matchingGroup = Object.entries(refs.territoryGroupMembers).find(([, members]) => sameCodes(value, members))?.[0] ?? "";
  const [selectedMode, setSelectedMode] = useState(null);
  const selectionMode = selectedMode ?? (matchingGroup ? "group" : "country");
  const territoryOptions = Object.entries(refs.territoryLabel).map(([code, label]) => ({ value: code, label }));
  const groupOptions = Object.entries(refs.territoryGroupLabel).map(([code, label]) => ({ value: code, label }));

  function toggle(code) {
    onChange(value.includes(code) ? value.filter((item) => item !== code) : [...value, code]);
  }

  return (
    <div className="upload-territory-editor">
      <div className="mx-seg upload-territory-mode" role="group" aria-label="지역 선택 방식">
        <button type="button" className={`mx-seg-opt${selectionMode === "country" ? " active" : ""}`} onClick={() => setSelectedMode("country")}>개별 국가</button>
        <button type="button" className={`mx-seg-opt${selectionMode === "group" ? " active" : ""}`} onClick={() => setSelectedMode("group")}>지역 그룹</button>
      </div>
      {selectionMode === "group" && (
        <CustomSelect
          ariaLabel="지역 그룹"
          value={matchingGroup}
          options={groupOptions}
          placeholder="지역 그룹을 선택하세요"
          onChange={(code) => onChange([...(refs.territoryGroupMembers[code] ?? [])])}
        />
      )}
      <div className="upload-territory-chips">
        {territoryOptions.map((option) => {
          const selected = value.includes(option.value);
          if (selectionMode === "group" && !selected) return null;
          return (
            <button key={option.value} type="button" className={`upload-territory-chip${selected ? "" : " upload-territory-chip--excluded"}`} onClick={() => toggle(option.value)}>
              {option.label}
            </button>
          );
        })}
      </div>
      <div className="mx-text-xs mx-muted">{value.length}개국 · 저장 시 국가별 권리 행 생성</div>
    </div>
  );
}

function EvidenceCell({ evidence = {}, field, onChange }) {
  const [open, setOpen] = useState(false);
  const entry = firstEvidenceEntry(evidence, field);
  const update = (patch) => onChange(updateFirstEvidenceEntry(evidence, field, patch));
  return (
    <>
      <button type="button" className="upload-inline-evidence-trigger" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span>{entry.clause || "근거조항 확인"}</span>
        <span className="upload-inline-evidence-chevron" aria-hidden="true">▴</span>
      </button>
      {open && <div className="upload-inline-evidence-fields">
        <div className="upload-inline-evidence-label">근거조항 원문 (수정 가능)</div>
        <textarea className="mx-input" aria-label={`${field} 근거 원문`} rows={4} placeholder="근거 원문" value={entry.quote ?? ""} onChange={(event) => update({ quote: event.target.value })} />
      </div>}
    </>
  );
}

function sameCodes(left = [], right = []) {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((code) => rightSet.has(code));
}

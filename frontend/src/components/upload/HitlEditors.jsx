import { useState } from "react";
import CustomSelect from "../CustomSelect.jsx";
import Tooltip from "../Tooltip.jsx";
import { EXCLUSIVITY_OPTIONS } from "../../labels.js";
import { firstEvidenceEntry, updateFirstEvidenceEntry } from "../../lib/evidence.js";
import { useRefs } from "../../lib/useRefs.js";
import IpMatchPanel from "./IpMatchPanel.jsx";

const REGISTRATION_MODE_LABEL = {
  new: "신규 계약",
  revision: "버전 계약",
  final: "최종 계약",
};
const REGISTRATION_MODE_HELP = "등록 유형은 진입 경로에서 확정됩니다. 버전/최종 계약은 계약 상세에서 시작한 경우에만 기존 계약에 연결됩니다.";

export function RegistrationContextEditor({ mode }) {
  return (
    <section className="upload-hitl-section upload-registration-context">
      <div className="ipform-field-label">
        최종 등록 유형
        <Tooltip label={REGISTRATION_MODE_HELP} />
      </div>
      <div className="mx-seg upload-mode-selector" role="group" aria-label="최종 등록 유형">
        {Object.entries(REGISTRATION_MODE_LABEL).map(([key, label]) => (
          <button key={key} type="button" className={`mx-seg-opt${mode === key ? " active" : ""}`} disabled>
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}

// 값(or 근거조항)이 원본 추출 결과와 달라졌는지 — 편집 이력이 아니라 현재값 대 원본값
// 비교라서, 지웠다가 다시 원래 값으로 되돌리면 자동으로 꺼진다. originalRight가 없으면
// (비교 기준선을 못 뜬 경우) 비교 자체를 생략한다.
function evidenceQuote(evidence, field) {
  return firstEvidenceEntry(evidence, field)?.quote?.trim() ?? "";
}
function fieldNeedsReview(originalRight, right, field, valuesEqual) {
  if (!originalRight) return false;
  return !valuesEqual || evidenceQuote(originalRight.evidence, field) !== evidenceQuote(right.evidence, field);
}

export function HitlReviewEditor({ contractInfo, setContractInfo, rights, originalRights, onUpdateRight, ipMatch, setIpMatch, ipLocked = false }) {
  const refs = useRefs();
  const updateContract = (key, next) => setContractInfo((previous) => ({ ...previous, [key]: next }));
  const assets = ipMatch?.ip?.assets ?? [];
  const assetOptions = assets.map((asset) => ({ value: String(asset.contentAssetId), label: `${asset.title || "권리 대상"} · ${asset.scopeType ?? "범위 미지정"} (#${asset.contentAssetId})` }));
  const selectedAssetId = rights.find((right) => right.contentAssetId != null)?.contentAssetId ?? null;
  const updateContentAsset = (next) => {
    const contentAssetId = Number(next);
    rights.forEach((_, index) => onUpdateRight(index, { contentAssetId }));
  };

  return (
    <section className="upload-hitl-section upload-hitl-review" aria-label="AI 추출 결과 수정">
      <CollapsibleCard title="IP 및 권리 대상" className="upload-review-section">
        <div className="upload-review-basic-table">
          <BasicReviewRow
            label="대상 IP"
            required
            value={<IpMatchPanel ipMatch={ipMatch} setIpMatch={setIpMatch} showHeading={false} disabled={ipLocked} />}
          />
          <BasicReviewRow
            label="권리 대상"
            required
            value={<CustomSelect ariaLabel="권리 대상" value={selectedAssetId == null ? "" : String(selectedAssetId)} onChange={updateContentAsset} options={assetOptions} placeholder={assets.length ? "권리 대상을 선택하세요" : "IP를 먼저 선택하세요"} disabled={!assets.length || rights.length === 0} />}
          />
        </div>
      </CollapsibleCard>

      <CollapsibleCard title="계약 기본 정보" className="upload-review-section">
        <div className="upload-review-basic-table">
          <BasicReviewRow label="권리 허락자" required value={<ReviewInput ariaLabel="권리 허락자" value={contractInfo.grantor} onChange={(next) => updateContract("grantor", next)} />} />
          <BasicReviewRow label="권리 이용자" required value={<ReviewInput ariaLabel="권리 이용자" value={contractInfo.grantee} onChange={(next) => updateContract("grantee", next)} />} />
          <BasicReviewRow label="계약 체결일" value={<ReviewInput ariaLabel="계약 체결일" type="date" value={contractInfo.signedDate} onChange={(next) => updateContract("signedDate", next)} />} />
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
          {rights.slice(0, 1).map((right, index) => {
            const originalRight = originalRights?.[index];
            return (
            <div className="upload-review-right" key={index}>
              <ReviewRow
                label="이용지역"
                required
                needsReview={fieldNeedsReview(originalRight, right, "territory", sameCodes(originalRight?.territories ?? [], right.territories ?? []))}
                value={<TerritoryEditor value={right.territories ?? []} refs={refs} onChange={(territories) => onUpdateRight(index, { territories })} />}
                evidence={<EvidenceCell evidence={right.evidence} field="territory" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="법적 권리"
                required
                needsReview={fieldNeedsReview(originalRight, right, "legalRight", originalRight?.legalRight === right.legalRight)}
                value={<CustomSelect ariaLabel={`법적 권리 ${index + 1}`} value={right.legalRight} onChange={(next) => onUpdateRight(index, { legalRight: next })} options={refs.legalRightOptions} />}
                evidence={<EvidenceCell evidence={right.evidence} field="legalRight" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="사업적 이용형태"
                required
                needsReview={fieldNeedsReview(originalRight, right, "exploitationMode", originalRight?.exploitationMode === right.exploitationMode)}
                value={<CustomSelect ariaLabel={`사업적 이용형태 ${index + 1}`} value={right.exploitationMode} onChange={(next) => onUpdateRight(index, { exploitationMode: next })} options={refs.exploitationModeOptions} />}
                evidence={<EvidenceCell evidence={right.evidence} field="exploitationMode" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="독점 형태"
                required
                needsReview={fieldNeedsReview(originalRight, right, "exclusivity", originalRight?.exclusivity === right.exclusivity)}
                value={<CustomSelect ariaLabel={`독점 형태 ${index + 1}`} value={right.exclusivity} onChange={(next) => onUpdateRight(index, { exclusivity: next })} options={EXCLUSIVITY_OPTIONS} />}
                evidence={<EvidenceCell evidence={right.evidence} field="exclusivity" onChange={(evidence) => onUpdateRight(index, { evidence })} />}
              />
              <ReviewRow
                label="라이선스 유효 기간"
                required
                needsReview={fieldNeedsReview(originalRight, right, "period", originalRight?.period?.start === right.period?.start && originalRight?.period?.end === right.period?.end)}
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
            );
          })}
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

function BasicReviewRow({ label, value, required = false }) {
  return (
    <div className="upload-review-basic-row">
      <div className="upload-review-label">{label}{required && <span className="upload-required-mark">*</span>}</div>
      <div className="upload-review-value">{value}</div>
    </div>
  );
}

function ReviewRow({ label, value, evidence = null, required = false, needsReview = false }) {
  return (
    <div className="upload-review-row">
      <div className="upload-review-label">
        {label}
        {required && <span className="upload-required-mark">*</span>}
        {needsReview && (
          <span className="upload-review-flag" title="값 또는 근거조항이 원본 추출 결과와 달라졌습니다 — 서로 일치하는지 확인해주세요.">
            ⚠ 확인 필요
          </span>
        )}
      </div>
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

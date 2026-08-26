import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import CustomSelect from "../CustomSelect.jsx";
import ConflictBadge from "../ConflictBadge.jsx";
import DownloadIcon from "../icons/DownloadIcon.jsx";
import { useRefs } from "../../lib/useRefs.js";
import { EVIDENCE_FIELDS, groupEvidenceByQuote } from "../../lib/evidence.js";
import { ASSET_SCOPE_LABEL, EXCLUSIVITY_LABEL, STATUS_LABEL, TERMINATED_REASON_LABEL, LANG_LABEL, exclusivityTagClass } from "../../labels.js";

const ContractPdfPreview = lazy(() => import("./ContractPdfPreview.jsx"));
const CANCEL_REASON_DEFS = [
  { value: "cancelled", label: "해지" },
  { value: "expired", label: "만료" },
  { value: "waiver", label: "권리포기" },
];
const HISTORY_DATE_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function usePdfObjectUrl(source) {
  const [url, setUrl] = useState(typeof source === "string" ? source : null);
  useEffect(() => {
    if (!source || typeof source === "string") { setUrl(source ?? null); return; }
    const objectUrl = URL.createObjectURL(source);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [source]);
  return url;
}

function usePdfSource(contractId, activeHistory) {
  const [source, setSource] = useState(null);
  useEffect(() => {
    if (!contractId) return;
    let cancelled = false;
    api.fetchContractFile(contractId, { historyId: activeHistory?.historyId })
      .then((blob) => { if (!cancelled) setSource(blob); })
      .catch(() => { if (!cancelled) setSource(null); });
    return () => { cancelled = true; };
  }, [contractId, activeHistory]);
  return source;
}

export default function ContractDetailContent({ contract, onContractUpdate }) {
  const uploadContext = new URLSearchParams({ contractId: String(contract.id), ipId: String(contract.ipId) });
  const registerHref = `/upload?mode=revision&${uploadContext}`;
  // 이미 서명 완료(signed)된 계약을 다시 "최종계약 등록"하는 건 기간 연장이다 —
  // 연장은 기존 계약의 새 버전이 아니라 법적으로 별개인 신규 계약이라 contractId를
  // 넘기지 않고 mode=new로 보낸다(IP는 그대로 이어받는다).
  const isRenewal = contract.status === "signed";
  const finalHref = isRenewal
    ? `/upload?${new URLSearchParams({ mode: "new", ipId: String(contract.ipId) })}`
    : `/upload?mode=final&${uploadContext}`;
  // 세대(histories[])가 여러 개면 드롭다운으로 골라 볼 수 있다 — 기본값은 currentVersion.
  // API 명세서 §8 기준: histories[]는 historyId·isCurrent를 갖고, currentHistory라는
  // 별도 객체는 없다 — "현재 세대"는 isCurrent===true인 항목을 찾아서 판단한다.
  const [selectedVersion, setSelectedVersion] = useState(contract.currentVersion ?? null);
  const activeHistory =
    contract.histories?.find((h) => h.version === selectedVersion) ?? contract.histories?.find((h) => h.isCurrent) ?? null;
  const pdfUrl = usePdfObjectUrl(usePdfSource(contract.id, activeHistory));
  const [historyContract, setHistoryContract] = useState(null);
  const [historyError, setHistoryError] = useState(null);
  useEffect(() => {
    if (!activeHistory?.historyId || activeHistory.isCurrent) {
      setHistoryContract(null);
      setHistoryError(null);
      return;
    }
    let cancelled = false;
    setHistoryContract(null);
    setHistoryError(null);
    api
      .getContract(contract.id, { historyId: activeHistory.historyId })
      .then((snapshot) => {
        if (!cancelled) setHistoryContract(snapshot);
      })
      .catch((err) => {
        if (!cancelled) setHistoryError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [contract.id, activeHistory?.historyId, activeHistory?.isCurrent]);
  // 이력 상세 응답을 현재 계약과 같은 표시 모델로 합친다.
  const snapshot = historyContract ?? contract;
  const displayContract = {
    ...snapshot,
    selectedHistory: activeHistory,
    title: activeHistory?.title ?? snapshot.title,
    grantor: activeHistory?.grantor ?? snapshot.grantor,
    grantee: activeHistory?.grantee ?? snapshot.grantee,
    signedDate: activeHistory?.signedDate ?? snapshot.signedDate,
    rightsGrants: activeHistory?.rightsGrants ?? snapshot.rightsGrants,
  };
  // 좁은 화면에서는 PDF 뷰어가 상세 정보를 밀어내려서 접었다 펼 수 있게 한다
  // (버튼 자체는 CSS가 좁은 화면에서만 보여준다 — 넓은 화면에서는 이 상태와 무관하게 항상 펼침).
  const [pdfPanelOpen, setPdfPanelOpen] = useState(true);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("cancelled");
  const [cancelNote, setCancelNote] = useState("");
  const [cancelSaving, setCancelSaving] = useState(false);
  const [cancelError, setCancelError] = useState(null);
  const statusLabel = STATUS_LABEL[contract.status];

  function handleCancelContract() {
    setCancelSaving(true);
    setCancelError(null);
    api
      .cancelContract(contract.id, { reason: cancelReason, note: cancelNote.trim() || undefined })
      .then(() => api.getContract(contract.id))
      .then((updated) => {
        onContractUpdate?.(updated);
        setCancelModalOpen(false);
      })
      .catch((err) => setCancelError(err.message))
      .finally(() => setCancelSaving(false));
  }
  // contract 자체엔 exclusivity 컬럼이 없다 — 목록 페이지와 같은 규칙으로 대표
  // grant(배열 마지막 항목)의 독점 여부를 상단 태그에 보여준다.
  const primaryExclusivity = displayContract.rightsGrants?.at(-1)?.exclusivity;

  // PDF 뷰어가 오른쪽 상세 영역보다 훨씬 길어지지 않도록, 상세 영역 높이를 측정해 뷰어 높이를 맞춘다.
  const sidebarRef = useRef(null);
  const [sidebarHeight, setSidebarHeight] = useState(null);
  useEffect(() => {
    const el = sidebarRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setSidebarHeight(entry.contentRect.height));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div>
      <div className="detail-tags">
        {primaryExclusivity && (
          <span className={`mx-tag ${exclusivityTagClass(primaryExclusivity)}`}>
            {EXCLUSIVITY_LABEL[primaryExclusivity] ?? primaryExclusivity}
          </span>
        )}
        {statusLabel && <span className="mx-tag mx-tag-outline">{statusLabel}</span>}
        {activeHistory && <span className="mx-tag mx-tag-outline">버전 {activeHistory.version}</span>}
      </div>
      <div className="mx-page-header">
        <div>
          <h2 className="mx-heading-lg detail-title">
            {displayContract.title ?? `계약 #${contract.id}`} — {displayContract.grantee ?? "—"}
          </h2>
          <div className="detail-subtitle mx-text-sm mx-muted">계약 ID: {contract.id}</div>
        </div>
        <div className="detail-actions">
          {contract.status !== "cancelled" && (
            <button type="button" className="mx-btn mx-btn-secondary" onClick={() => setCancelModalOpen(true)}>
              계약 종료
            </button>
          )}
          <Link to={registerHref} className="mx-btn mx-btn-secondary" aria-disabled={!contract.ipId} onClick={(event) => { if (!contract.ipId) event.preventDefault(); }} title={!contract.ipId ? "계약 상세 응답의 ipId가 필요합니다." : undefined}>
            버전계약 등록
          </Link>
          <Link to={finalHref} className="mx-btn mx-btn-primary" aria-disabled={!contract.ipId} onClick={(event) => { if (!contract.ipId) event.preventDefault(); }} title={!contract.ipId ? "계약 상세 응답의 ipId가 필요합니다." : undefined}>
            {isRenewal ? "계약 연장(신규 등록)" : "최종계약 등록"}
          </Link>
        </div>
      </div>

      {cancelModalOpen && (
        <div className="detail-pin-wrap detail-extend-overlay" onClick={() => !cancelSaving && setCancelModalOpen(false)}>
          <div className="mx-card mx-card-pad detail-pin-modal" onClick={(e) => e.stopPropagation()}>
            <h4 className="mx-heading-card">계약을 종료할까요?</h4>
            <p className="mx-text-sm mx-muted">
              상태가 {CANCEL_REASON_DEFS.find((d) => d.value === cancelReason)?.label}로 바뀌고, 살아있는 권리가 전부 종료 처리됩니다.
            </p>
            <label className="ipform-field-label" style={{ marginTop: 12 }}>사유</label>
            <CustomSelect ariaLabel="종료 사유" value={cancelReason} onChange={setCancelReason} options={CANCEL_REASON_DEFS} />
            <label className="ipform-field-label" style={{ marginTop: 12 }}>메모 (선택)</label>
            <textarea
              className="mx-input"
              rows={2}
              value={cancelNote}
              onChange={(e) => setCancelNote(e.target.value)}
              placeholder="자유 입력 메모"
            />
            {cancelError && <div className="mx-text-xs" style={{ color: "var(--mx-alert-text)", marginTop: 8 }}>{cancelError}</div>}
            <div className="detail-pin-actions">
              <button type="button" className="mx-btn mx-btn-secondary" disabled={cancelSaving} onClick={() => setCancelModalOpen(false)}>
                취소
              </button>
              <button type="button" className="mx-btn mx-btn-primary" disabled={cancelSaving} onClick={handleCancelContract}>
                {cancelSaving ? "처리 중…" : "계약 종료"}
              </button>
            </div>
          </div>
        </div>
      )}

      {(activeHistory?.status === "conflicted" || displayContract.conflictReport) && (
        <ConflictReportBanner report={activeHistory?.conflictReport ?? displayContract.conflictReport} />
      )}
      {historyError && <div className="mx-alert-banner mx-mb-20">선택한 버전의 상세 정보를 불러오지 못했습니다: {historyError}</div>}

      <button type="button" className="mx-link-btn mx-collapse-toggle detail-panel-toggle" onClick={() => setPdfPanelOpen((v) => !v)}>
        {pdfPanelOpen ? "PDF 접기" : "PDF 펼치기"}
      </button>

      <div className="detail-grid">
        <div
          className={`mx-card mx-dark-panel preview-panel${pdfPanelOpen ? "" : " detail-preview-panel--collapsed"}`}
          style={sidebarHeight ? { height: sidebarHeight } : undefined}
        >
          <div className="mx-mono preview-header">
            <span>
              원본 문서 미리보기{pdfUrl ? "" : " (react-pdf)"}
              {activeHistory?.fileName && <span className="mx-muted"> · {activeHistory.fileName}</span>}
            </span>
            <div className="preview-header-actions">
              {contract.histories?.length > 1 && (
                <CustomSelect
                  ariaLabel="버전 선택"
                  value={selectedVersion}
                  onChange={setSelectedVersion}
                  options={contract.histories.map((h) => ({
                    value: h.version,
                    label: `버전 ${h.version} · ${h.documentKind === "final" ? "최종" : "초안"}`,
                  }))}
                />
              )}
              <a
                className="preview-header-btn"
                href={pdfUrl ?? undefined}
                download={activeHistory?.fileName}
                aria-disabled={!pdfUrl}
                title={pdfUrl ? undefined : "PDF 원본 연동 후 활성화됩니다"}
                onClick={(e) => {
                  if (!pdfUrl) e.preventDefault();
                }}
              >
                <DownloadIcon /> 다운로드
              </a>
              <button
                type="button"
                className="preview-header-btn"
                disabled={!pdfUrl}
                title={pdfUrl ? undefined : "PDF 원본 연동 후 활성화됩니다"}
                onClick={() => window.open(pdfUrl, "_blank", "noopener")}
              >
                ⤢ 새 탭에서 크게 보기
              </button>
            </div>
          </div>
          <div className="preview-body">
            <div className="preview-unlocked-title">보안 세션 인증됨 — 전체 문서 미리보기</div>
            <Suspense fallback={<p className="preview-fallback-text">PDF 뷰어 불러오는 중…</p>}><ContractPdfPreview pdfUrl={pdfUrl} rawText={activeHistory?.rawText} /></Suspense>
          </div>
        </div>

        <div className="detail-sidebar" ref={sidebarRef}>
          <RightsGrantGroups contract={displayContract} />
        </div>
      </div>

      <div className="mx-mt-20">
        <Link to="/" className="mx-btn mx-btn-secondary">목록으로 돌아가기</Link>
      </div>
    </div>
  );
}

// contract_history.status='conflicted'일 때만 존재하는 conflict_report(jsonb) —
// save_rights_batch()가 남기는 판정 결과를 그대로 화면에 보여준다. 이 세대는
// rights_grant가 실제로 생성되지 않으므로(all-or-nothing), 여기 말고는 이 계약이
// 왜 막혔는지 알 방법이 없다.
function ConflictReportBanner({ report }) {
  const { territoryLabel, legalRightLabel, exploitationModeLabel } = useRefs();
  return (
    <div className="mx-alert-banner mx-mb-20">
      <b>이 버전은 충돌로 등록되지 않았습니다.</b>
      {report?.constraintName && (
        <>
          {" "}
          — 제약: <code>{report.constraintName}</code>
        </>
      )}
      {(report?.conflicts ?? []).map((c, i) => (
        <div key={i} style={{ marginTop: 6 }}>
          기존 <Link to={`/contracts/${c.existing?.contractId ?? c.existingContractId}`}>계약 #{c.existing?.contractId ?? c.existingContractId}</Link>의 권리
          (#{c.existing?.rightsGrantId ?? c.existingGrantId})와{" "}
          {territoryLabel[c.incoming?.territory] ?? c.incoming?.territory} ·{" "}
          {legalRightLabel[c.incoming?.legalRight] ?? c.incoming?.legalRight} ·{" "}
          {exploitationModeLabel[c.incoming?.exploitationMode] ?? c.incoming?.exploitationMode} 구간이 {formatConflictOverlap(c.overlap ?? c.overlapPeriod)}에서 겹칩니다.
        </div>
      ))}
    </div>
  );
}

function formatConflictOverlap(overlap) {
  if (!overlap) return "—";
  if (typeof overlap === "string") return overlap;
  return `${overlap.start ?? "…"} ~ ${overlap.end ?? "…"}${overlap.days != null ? ` (${overlap.days}일)` : ""}`;
}

// API에 없는 필드는 "—"로 비워 둔다.
function RightsGrantGroups({ contract }) {
  const { territoryLabel, scopeTypeLabel, legalRightLabel, exploitationModeLabel } = useRefs();
  return (
    <>
      <div className="mx-card mx-card-pad">
        <h5 className="mx-heading-panel">계약 기본 정보</h5>
        <MetaRow label="계약 명칭" value={contract.title ?? "—"} />
        <MetaRow label="계약 체결일" value={contract.signedDate ?? "—"} />
        <MetaRow label="최근 수정" value={formatUploadedAt(activeHistoryForDisplay(contract))} />
        <MetaRow label="원문 언어" value={LANG_LABEL[contract.lang] ?? contract.lang ?? "—"} />
        <MetaRow label="계약 당사자 (갑)" value={contract.grantor ?? "—"} />
        <MetaRow label="계약 상대방 (을)" value={contract.grantee ?? "—"} last />
      </div>

      <div className="mx-card mx-card-pad">
        <h5 className="mx-heading-panel">Payment</h5>
        <MetaRow label="통화 코드" value={contract.currency ?? "—"} />
        <MetaRow label="계약 금액" value={formatAmount(contract.amount)} last />
      </div>

      <div className="mx-card mx-card-pad">
        <h5 className="mx-heading-panel">권리(grant) 관련</h5>
        {(contract.rightsGrants ?? []).length === 0 && <p className="mx-empty-state">등록된 권리 조항이 없습니다.</p>}
        {(contract.rightsGrants ?? []).map((r) => {
          const terminated = r.status === "terminated";
          return (
            <div key={r.id} className={`rights-card${terminated ? " rights-card--terminated" : ""}`}>
              <div className="rights-card-tags">
                <span className="mx-tag mx-tag-neutral">{r.territoryLabel ?? territoryLabel[r.territory] ?? r.territory}</span>
                <span className={`mx-tag ${exclusivityTagClass(r.exclusivity)}`}>{EXCLUSIVITY_LABEL[r.exclusivity] ?? r.exclusivity}</span>
                {terminated && (
                  <span className="mx-tag mx-tag-neutral">
                    종료됨{r.terminatedReason ? ` · ${TERMINATED_REASON_LABEL[r.terminatedReason] ?? r.terminatedReason}` : ""}
                  </span>
                )}
                <ConflictBadge conflict={r.conflict} />
              </div>
              <div className="rights-card-title">
                {r.legalRightLabel ?? legalRightLabel[r.legalRight] ?? r.legalRight} · {r.exploitationModeLabel ?? exploitationModeLabel[r.exploitationMode] ?? r.exploitationMode}
              </div>
              <div className="rights-card-meta">
                권리 대상: {r.contentAssetTitle ?? "—"} · {scopeTypeLabel[r.scopeType] ?? ASSET_SCOPE_LABEL[r.scopeType] ?? r.scopeType ?? "—"}
              </div>
              <div className="rights-card-meta">기간: {formatPeriod(r.period)}</div>
              {terminated && r.terminationNote && <div className="rights-card-meta">종료 메모: {r.terminationNote}</div>}
              {r.conditionsRaw && (
                <div className="rights-card-meta" title={JSON.stringify(r.conditionsRaw)}>
                  부가조건: {formatConditions(r.conditionsRaw)}
                </div>
              )}
              <EvidenceList evidence={r.evidence} />
            </div>
          );
        })}
      </div>

      <div className="mx-card mx-card-pad">
        <h5 className="mx-heading-panel">재허락 권한</h5>
        <MetaRow label="제3자 재허락 가능 여부" value={formatBoolean(contract.authority?.sublicensable)} />
        <MetaRow label="재허락 허용 상대방 유형" value={formatList(contract.authority?.allowedPartyTypes)} />
        <MetaRow label="대상 수령자 유형" value={formatAuthorityValue(contract.authority?.targetRecipientType)} last />
      </div>

    </>
  );
}

function EvidenceList({ evidence }) {
  const groups = groupEvidenceByQuote(evidence);
  if (groups.length === 0) return <div className="rights-card-meta" style={{ marginTop: 4 }}>근거: —</div>;
  return (
    <>
      {groups.map((group) => (
        <div key={group.quote} className="rights-card-meta" style={{ marginTop: 4 }} title={group.quote}>
          근거({group.fields.map((field) => EVIDENCE_FIELDS[field] ?? field).join("·")}): {group.clauses[0] ?? "—"}
        </div>
      ))}
    </>
  );
}

function formatBoolean(value) {
  if (value == null) return "—";
  return value ? "가능" : "불가";
}

function formatList(value) {
  if (value == null) return "—";
  return Array.isArray(value) ? (value.length ? value.join(", ") : "—") : String(value);
}

function formatAuthorityValue(value) {
  return value == null || value === "" ? "—" : String(value);
}

function formatConditions(conditions) {
  const values = [];
  if (conditions.sublicense === "prior_written_consent") values.push("재허락 시 사전 서면 동의 필요");
  else if (conditions.sublicense) values.push(`재허락: ${conditions.sublicense}`);
  if (conditions.marketingClipAllowed != null) values.push(`마케팅 클립 사용 ${conditions.marketingClipAllowed ? "허용" : "불가"}`);
  if (conditions.note) values.push(conditions.note);
  return values.length ? values.join(" · ") : JSON.stringify(conditions);
}

function activeHistoryForDisplay(contract) {
  const histories = contract.histories ?? [];
  if (contract.selectedHistory?.uploadedAt) return contract.selectedHistory;
  const selectedVersion = contract.currentVersion;
  return (
    histories.find((history) => history.version === selectedVersion)
    ?? histories.find((history) => history.isCurrent)
    ?? [...histories].reverse().find((history) => history.documentKind === "final")
    ?? histories.at(-1)
  );
}

function formatUploadedAt(history) {
  const value = history?.uploadedAt;
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : HISTORY_DATE_FORMATTER.format(date);
}

function MetaRow({ label, value, last }) {
  return (
    <div className={`detail-meta-row${last ? " detail-meta-row--last" : ""}`}>
      <span className="detail-meta-label mx-muted">{label}</span>
      <b className="detail-meta-value" title={typeof value === "string" ? value : undefined}>
        {value}
      </b>
    </div>
  );
}

function formatPeriod(period) {
  if (!period?.start) return "—";
  return `${period.start} ~ ${period.end ?? "미정"}`;
}

// 통화 구분은 옆 "통화 코드" 행이 맡는다 — 여기선 기호 없이 숫자만 보여준다.
function formatAmount(amount) {
  return amount != null ? amount.toLocaleString() : "—";
}

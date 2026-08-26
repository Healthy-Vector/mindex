import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import ConflictTimeline from "../components/ConflictTimeline.jsx";
import { EXCLUSIVITY_LABEL } from "../labels.js";
import { hasActivePinSession, setPinSessionExpiresAt, setPinSessionToken } from "../lib/pinSession.js";
import { useRefs } from "../lib/useRefs.js";
import "../styles/conflict-check-page.css";

// 독점 계열끼리는 EXCLUDE, 독점 계열과 비독점의 중첩은 DB trigger가 판정한다.
// 양쪽이 모두 non_exclusive인 경우만 충돌이 아니다.
const SEVERITY_META = {
  EXCLUSIVE_VS_EXCLUSIVE: { cls: "critical", label: "독점 × 독점 — 최고 심각도", ringVar: "--mx-alert" },
  EXCLUSIVE_VS_SOLE: { cls: "serious", label: "독점 × 단독 — 심각도 높음", ringVar: "--mx-warn3" },
  SOLE_VS_SOLE: { cls: "moderate", label: "단독 × 단독 — 심각도 중간", ringVar: "--mx-warn2" },
  EXCLUSIVE_VS_NON_EXCLUSIVE: { cls: "serious", label: "독점 계열 × 비독점 — 충돌", ringVar: "--mx-warn3" },
  CONFLICT: { cls: "serious", label: "권리 범위 충돌", ringVar: "--mx-warn3" },
};

// 문구는 labels.js의 STATUS_LABEL(초안/서명 완료)과 같은 어휘를 쓴다 — "드래프트"/
// "최종 계약" 같은 별도 표현을 섞지 않는다.
function saveToast(saved, isFinal) {
  if (saved.hasConflict || saved.batchResult === "CONFLICTED" || saved.historyStatus === "conflicted") {
    return "충돌이 발견되어 초안 상태로 저장되었습니다. 충돌을 해소한 뒤 다시 등록을 진행하세요.";
  }
  return isFinal ? "충돌 없이 서명 완료 상태로 저장되었습니다." : "충돌 없이 초안 상태로 저장되었습니다.";
}

export default function ConflictCheckPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { payload, ip, verifyResult: initialResult } = location.state ?? {};
  const { mode = "new" } = payload ?? {};
  const isFinal = mode === "final";
  const [result] = useState(initialResult ?? { hasConflict: false, checkedRows: 0, conflicts: [], candidate: null });
  const [quoteModal, setQuoteModal] = useState(null); // { label, quotes } | null
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const conflicts = result.conflicts ?? [];
  const hasConflict = result.hasConflict ?? conflicts.length > 0;
  const candidate = result.candidate ?? ip;
  const [enrichedConflicts, setEnrichedConflicts] = useState(conflicts);

  // "기존 계약" 비교값 보강 — POST /contracts/verify 응답(API 설계서 #5)은
  // existingGrantId/existingContractId 참조만 주고 그 권리의 실제 지역·법적권리·기간·
  // 독점여부 값은 안 준다. GET /contracts/{id}(#8)로 따로 조회해서 채운다.
  // #8은 PIN 세션이 필요한데 업로드→충돌검사 플로우엔 PIN 절차가 없다 — 로컬 테스트
  // 전용으로 VITE_TEST_PIN이 설정돼 있으면 그 PIN으로 자동 인증한다. 실 배포 환경에는
  // 이 env가 없으므로 조용히 스킵되고 기존처럼 "—"만 보인다.
  useEffect(() => {
    if (!conflicts.length) return undefined;
    let cancelled = false;
    (async () => {
      if (!hasActivePinSession() && import.meta.env.VITE_TEST_PIN) {
        try {
          const session = await api.verifyPin(import.meta.env.VITE_TEST_PIN);
          setPinSessionToken(session?.sessionToken ?? null);
          setPinSessionExpiresAt(session?.expiresAt ?? Date.now() + (session?.ttlSeconds ?? 900) * 1000);
        } catch {
          return;
        }
      }
      if (!hasActivePinSession() || cancelled) return;
      const contractCache = new Map();
      const results = await Promise.all(
        conflicts.map(async (c) => {
          if (c.existing?.territory || !c.existing?.contractId) return c;
          try {
            let contract = contractCache.get(c.existing.contractId);
            if (!contract) {
              contract = await api.getContract(c.existing.contractId);
              contractCache.set(c.existing.contractId, contract);
            }
            const match = contract.rightsGrants?.find((r) => r.id === c.existing.rightsGrantId);
            if (!match) return c;
            return {
              ...c,
              existing: {
                ...c.existing,
                title: contract.title ?? c.existing.title,
                grantee: contract.grantee,
                territory: match.territory,
                legalRight: match.legalRight,
                exploitationMode: match.exploitationMode,
                period: match.period,
                exclusivity: match.exclusivity,
              },
            };
          } catch {
            return c;
          }
        }),
      );
      if (!cancelled) setEnrichedConflicts(results);
    })();
    return () => {
      cancelled = true;
    };
  }, [conflicts]);

  if (!payload?.tmpId || !initialResult) {
    return <Navigate to="/upload" replace />;
  }

  // 저장은 전용 페이지 대신, 목록으로 이동한 뒤 그 화면에서 알럿 배너로 결과를 알린다.
  function handleSave() {
    setSaving(true);
    setSaveError(null);
    if (!payload) {
      setSaveError("저장할 계약 데이터가 없습니다. 업로드 화면에서 다시 충돌검사를 실행하세요.");
      setSaving(false);
      return;
    }
    api
      .saveContract(payload)
      .then((saved) => navigate("/", { replace: true, state: { toast: saveToast(saved, isFinal) } }))
      .catch((err) => {
        // API 명세서 #6 "구현 시 주의" — 같은 tmpid로 두 번째 저장 요청이 오면 409
        // ALREADY_CONFIRMED와 함께 첫 저장 결과를 그대로 돌려준다. 에러로 취급하지 않고
        // "이미 저장됐다"는 걸 그대로 알려준 뒤 목록으로 보낸다.
        if (err.status === 409 && err.body?.code === "ALREADY_CONFIRMED") {
          navigate("/", { replace: true, state: { toast: `이미 저장된 계약입니다 — ${saveToast(err.body, isFinal)}` } });
          return;
        }
        setSaveError(err.message);
      })
      .finally(() => setSaving(false));
  }

  return (
    <div>
      <div className="mx-page-header">
        <div>
          <h2 className="mx-heading-lg">충돌 검사 결과</h2>
          <div className="mx-text-sm mx-muted">
            {candidate?.title} {candidate?.ip && `· ${candidate.ip}`}
          </div>
        </div>
      </div>

      {hasConflict ? (
        <div className="mx-alert-banner conflict-summary-banner">
          충돌 {conflicts.length}건이 발견되었습니다. 저장은 계속 진행되지만 <b>초안</b>으로만 저장됩니다.
        </div>
      ) : (
        <div className="conflict-clean-banner">충돌사항이 없습니다.</div>
      )}

      {enrichedConflicts.map((c, i) => {
        const severity = SEVERITY_META[c.severity] ?? SEVERITY_META.CONFLICT;
        const existingTitle = c.existing?.title ?? (c.existingContractId ? `기존 계약 #${c.existingContractId}` : "기존 계약");
        const canShowTimeline = c.existing?.period && c.incoming?.period && c.overlap;
        return (
          <div key={i} className="conflict-group mx-mb-24">
            <div className="mx-flex-between mx-mb-20">
              <h4 className="mx-heading-card" style={{ margin: 0 }}>
                {existingTitle}
                {c.existing?.grantee && <span className="mx-muted mx-text-sm"> — {c.existing.grantee}</span>}
              </h4>
              <span className={`mx-tag conflict-severity-tag conflict-severity-tag--${severity.cls}`}>{severity.label}</span>
            </div>

            {canShowTimeline && (
              <div className="mx-card mx-card-pad mx-mb-20">
                <ConflictTimeline
                  existing={c.existing.period}
                  incoming={c.incoming.period}
                  existingTitle={existingTitle}
                  incomingTitle={c.incoming.title ?? candidate?.title ?? "검토중인 계약"}
                  overlap={c.overlap}
                  severityVar={severity.ringVar}
                />
              </div>
            )}

            <div className="mx-card mx-card-pad">
              <CompareTable match={c} onShowQuote={setQuoteModal} />
            </div>
          </div>
        );
      })}

      {quoteModal && <QuoteCompareModal {...quoteModal} onClose={() => setQuoteModal(null)} />}

      {saveError && <div className="mx-alert-banner mx-mb-20">{saveError}</div>}

      <div className="mx-card mx-card-pad mx-flex-between conflict-save-bar">
        <div className="mx-text-sm mx-muted">
          충돌 여부와 무관하게 저장은 항상 진행됩니다. 충돌 리포트는 이력 컬럼에 함께 저장되어 상세에서 조회할 수 있습니다.
        </div>
        <div className="conflict-save-actions">
          <button type="button" className="mx-btn mx-btn-secondary" disabled={saving} onClick={() => setShowCancelConfirm(true)}>
            취소
          </button>
          <button type="button" className="mx-btn mx-btn-primary" disabled={saving} onClick={handleSave}>
            {saving ? "저장 중…" : isFinal && !hasConflict ? "서명 완료로 저장" : "초안으로 저장"}
          </button>
        </div>
      </div>

      {showCancelConfirm && (
        <div className="detail-pin-wrap detail-extend-overlay">
          <div className="mx-card mx-card-pad detail-pin-modal">
            <h4 className="mx-heading-card">저장하지 않고 나가시겠습니까?</h4>
            <p className="mx-text-sm mx-muted">지금까지 확인한 충돌검사 결과는 저장되지 않고 목록으로 이동합니다.</p>
            <div className="detail-pin-actions">
              <button type="button" className="mx-btn mx-btn-secondary" onClick={() => setShowCancelConfirm(false)}>
                계속 검토
              </button>
              <button type="button" className="mx-btn mx-btn-primary" onClick={() => navigate("/", { replace: true })}>
                나가기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// 기존 rights_grant(existing) vs 검토중인 신규 조건(incoming)을 지역/법적 권리/
// 사업적 이용형태/기간/독점여부로 나란히 보여준다. evidence가 있는 행은 클릭하면
// 원문 비교 팝업이 뜬다.
function CompareTable({ match, onShowQuote }) {
  const { territoryLabel, legalRightLabel, exploitationModeLabel } = useRefs();
  const existing = match.existing ?? {};
  const incoming = match.incoming ?? {};
  const existingTerritory = existing.territory ?? match.territory;
  const incomingTerritory = incoming.territory ?? match.territory;
  const existingLegalRight = existing.legalRight ?? match.legalRight;
  const incomingLegalRight = incoming.legalRight ?? match.legalRight;
  const existingExploitationMode = existing.exploitationMode ?? match.exploitationMode;
  const incomingExploitationMode = incoming.exploitationMode ?? match.exploitationMode;
  const rows = [
    {
      key: "territory",
      label: "지역",
      existing: territoryLabel[existingTerritory] ?? existingTerritory,
      incoming: territoryLabel[incomingTerritory] ?? incomingTerritory,
    },
    {
      key: "legalRight",
      label: "법적 권리",
      existing: legalRightLabel[existingLegalRight] ?? existingLegalRight,
      incoming: legalRightLabel[incomingLegalRight] ?? incomingLegalRight,
    },
    {
      key: "exploitationMode",
      label: "사업적 이용형태",
      existing: exploitationModeLabel[existingExploitationMode] ?? existingExploitationMode,
      incoming: exploitationModeLabel[incomingExploitationMode] ?? incomingExploitationMode,
    },
    { key: "period", label: "기간", existing: formatRange(existing.period), incoming: formatRange(incoming.period) },
    {
      key: "exclusivity",
      label: "독점 여부",
      existing: EXCLUSIVITY_LABEL[existing.exclusivity] ?? existing.exclusivity,
      incoming: EXCLUSIVITY_LABEL[incoming.exclusivity] ?? incoming.exclusivity,
    },
  ];

  return (
    <div className="mx-table-scroll">
      <table className="mx-table conflict-compare-table">
        <colgroup>
          <col style={{ width: "16%" }} />
          <col style={{ width: "38%" }} />
          <col style={{ width: "38%" }} />
          <col style={{ width: "8%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>비교 항목</th>
            <th>기존 계약</th>
            <th>검토중인 신규 계약</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const quotes = (row.key === "territory" || row.key === "exclusivity") && existing.evidence && incoming.evidence
              ? { existing: existing.evidence, incoming: incoming.evidence }
              : null;
            return (
              <tr
                key={row.key}
                className={quotes ? "conflict-compare-row--clickable" : undefined}
                onClick={quotes ? () => onShowQuote({ label: row.label, quotes }) : undefined}
                title={quotes ? "클릭하면 원문 비교" : undefined}
              >
                <td>{row.label}</td>
                <td>{row.existing || "—"}</td>
                <td>{row.incoming || "—"}</td>
                <td>{quotes && <span className="mx-link-btn mx-text-xs">원문 ›</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatRange(period) {
  return period?.start && period?.end ? `${period.start} ~ ${period.end}` : null;
}

function QuoteCompareModal({ label, quotes, onClose }) {
  return (
    <div className="detail-pin-wrap detail-extend-overlay" onClick={onClose}>
      <div className="mx-card mx-card-pad conflict-quote-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mx-flex-between mx-mb-16">
          <h4 className="mx-heading-card" style={{ margin: 0 }}>
            {label} — 원문 비교
          </h4>
          <button type="button" className="mx-link-btn" onClick={onClose}>
            닫기
          </button>
        </div>
        <div className="mx-two-col">
          <div>
            <div className="conflict-quote-label">기존 계약 원문</div>
            <div className="mx-quote-box">"{quotes.existing}"</div>
          </div>
          <div>
            <div className="conflict-quote-label">검토중인 신규 계약 원문</div>
            <div className="mx-quote-box">"{quotes.incoming}"</div>
          </div>
        </div>
      </div>
    </div>
  );
}

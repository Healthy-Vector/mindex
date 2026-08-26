import { computeContractStatus } from "../lib/contractStatus.js";
import { DISPLAY_STATE_LABEL } from "../labels.js";

const TIER_CLASS = { 90: "mx-status-warn1", 60: "mx-status-warn2", 30: "mx-status-warn3" };

// key는 API displayState를 소문자로 바꾼 값과 클라이언트 계산값을 함께 받는다.
const STATE_META = {
  unknown: { cls: "mx-status-muted", label: "기간 정보 없음" },
  pre_contract: { cls: "mx-status-muted", label: DISPLAY_STATE_LABEL.PRE_CONTRACT },
  before_term: { cls: "mx-status-muted" },
  in_term: { cls: "mx-status-good" },
  conflicted: { cls: "mx-status-critical", label: "충돌" },
  expired: { cls: "mx-status-critical" },
};

// 만료임박 3단계는 90일 창 안에서 얼마나 지났는지 컨링(conic-gradient)으로도 보여준다.
export default function StatusBadge({ signedDate, periodStart, periodEnd, today, status: precomputed }) {
  const status = precomputed ?? computeContractStatus({ signedDate, periodStart, periodEnd }, today ?? new Date());

  if (status.key === "expiring") {
    const pct = Math.max(0, Math.min(100, ((90 - status.daysToExpiry) / 90) * 100));
    const label = status.label ?? DISPLAY_STATE_LABEL.EXPIRING;
    return (
      <span className={`mx-status ${TIER_CLASS[status.tier]}`}>
        <span className="mx-status-ring" style={{ "--mx-ring-pct": pct }} aria-hidden="true" />
        {label}{status.daysToExpiry == null ? "" : ` (D-${status.daysToExpiry})`}
      </span>
    );
  }

  const meta = STATE_META[status.key] ?? STATE_META.unknown;
  const apiLabel = DISPLAY_STATE_LABEL[status.key?.toUpperCase()];
  return (
    <span className={`mx-status ${meta.cls}`}>
      <span className="mx-status-dot" aria-hidden="true" />
      {status.label ?? apiLabel ?? meta.label}
    </span>
  );
}

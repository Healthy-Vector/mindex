import { DISPLAY_STATE_LABEL } from "../labels.js";

// 계약 상태값을 계약체결일/권리시작일/권리종료일로 계산한다 — API 명세서(§7 displayState)의
// BEFORE_TERM/IN_TERM/EXPIRING/EXPIRED 4단계에 맞춘다. 계약체결 전(before_signing)과 서명은
// 됐지만 권리기간이 아직 안 시작(before_effective)은 둘 다 "권리기간 전"이라는 점에서
// BEFORE_TERM 하나로 합친다. 만료임박은 D-90/60/30.
const DAY_MS = 86400000;

function toDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function diffDays(a, b) {
  return Math.round((a.getTime() - b.getTime()) / DAY_MS);
}

// signedDate=계약체결일(contract.agreement_date), periodStart/End=권리시작일/권리종료일.
export function computeContractStatus({ signedDate, periodStart, periodEnd }, today = new Date()) {
  const signed = toDate(signedDate);
  const start = toDate(periodStart);
  const end = toDate(periodEnd);

  if (!start || !end) {
    return { key: "unknown", label: "기간 정보 없음", tier: null, daysToExpiry: null };
  }
  if (signed && today < signed) {
    return { key: "before_term", label: "계약 전", tier: null, daysToExpiry: null };
  }
  if (today < start) {
    return { key: "before_term", label: "유효기간 전", tier: null, daysToExpiry: diffDays(start, today) };
  }
  if (today > end) {
    return { key: "expired", label: DISPLAY_STATE_LABEL.EXPIRED, tier: null, daysToExpiry: diffDays(today, end) };
  }

  const daysToExpiry = diffDays(end, today);
  if (daysToExpiry >= 90) {
    return { key: "in_term", label: DISPLAY_STATE_LABEL.IN_TERM, tier: null, daysToExpiry };
  }
  const tier = daysToExpiry <= 30 ? 30 : daysToExpiry <= 60 ? 60 : 90;
  return { key: "expiring", label: DISPLAY_STATE_LABEL.EXPIRING, tier, daysToExpiry };
}

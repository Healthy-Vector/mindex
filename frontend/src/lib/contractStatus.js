import { DISPLAY_STATE_LABEL } from "../labels.js";

// 계약 상태값을 계약체결일/권리시작일/권리종료일로 계산한다 — API 명세서(§7 displayState)의
// PRE_CONTRACT/BEFORE_TERM/IN_TERM/EXPIRING/EXPIRED 5단계에 맞춘다. API는 계약 체결 전을
// PRE_CONTRACT로 따로 내려주고 BEFORE_TERM은 "유효기간 전"만 뜻한다. 이 파일은 날짜만
// 가진 화면(목록 응답을 못 쓰는 곳)에서 같은 경계를 재현하며, 계약 전은 key를
// before_term으로 두되 라벨로 구분한다. 만료임박은 D-90/60/30.
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

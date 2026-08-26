// legalRight/exploitationMode를 포함한 참조 코드는 GET /refs에서 받는다. 이 파일에는
// 화면 자체의 고정 UI 어휘만 둔다.

export const EXCLUSIVITY_LABEL = {
  exclusive: "독점",
  sole: "단독",
  non_exclusive: "비독점",
};

// "단독"(sole)은 제3자에게는 배타적이나 라이선서 본인은 계속 이용 가능한 형태라 완전
// 독점(exclusive)과 다르다 — 충돌 판정에서도 SOLE_VS_SOLE/EXCLUSIVE_VS_SOLE로 구분해서
// 심각도를 매긴다(mock/verify.js). non_exclusive가 하나라도 있으면 애초에 충돌이 아니다.
export function exclusivityTagClass(exclusivity) {
  if (exclusivity === "exclusive") return "mx-tag-accent";
  if (exclusivity === "sole") return "mx-tag-outline";
  return "mx-tag-neutral";
}

// contract.status(D-31) — 계약 업무 상태 3단계. 초안(draft)도 rights_grant는
// active라 권리를 예약한다 — 이 라벨은 업무 진행 상태 표시용이지 권리 점유 여부가 아니다.
export const STATUS_LABEL = {
  draft: "초안",
  signed: "서명 완료",
  cancelled: "취소/해지",
};

// GET /contracts의 displayState — 날짜가 없는 목록 응답에서도 항상 표시할 공통 문구.
// 계약 체결 전(PRE_CONTRACT)과 권리 유효기간 전(BEFORE_TERM)은 API가 별도 코드로
// 내려주므로 각각의 문구를 쓴다 — 예전엔 BEFORE_TERM 하나로 합쳐 받았다.
export const DISPLAY_STATE_LABEL = {
  PRE_CONTRACT: "계약 전",
  BEFORE_TERM: "유효기간 전",
  IN_TERM: "계약 기간중",
  EXPIRING: "만료임박",
  EXPIRED: "기간만료",
};

// rights_grant.terminated_reason — 권리가 종료된 사유.
export const TERMINATED_REASON_LABEL = {
  superseded: "새 세대로 대체됨",
  expired: "이용기간 만료",
  waiver: "권리 포기",
  cancelled: "계약 취소",
};

// ip_alias.lang / contract.lang — 언어 구분 (한 벌의 어휘를 공유한다).
export const LANG_LABEL = { ko: "한국어", en: "영어", ja: "일본어" };

function labelMapToOptions(labels) {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

export const EXCLUSIVITY_OPTIONS = labelMapToOptions(EXCLUSIVITY_LABEL);
export const LANG_OPTIONS = labelMapToOptions(LANG_LABEL);

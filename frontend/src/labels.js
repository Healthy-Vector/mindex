// legalRight/exploitationMode를 포함한 참조 코드는 GET /refs에서 받는다. 이 파일에는
// 화면 자체의 고정 UI 어휘만 둔다.

export const EXCLUSIVITY_LABEL = {
  exclusive: "독점",
  sole: "단독",
  non_exclusive: "비독점",
};

// "단독"(sole)은 제3자에게는 배타적이나 라이선서 본인은 계속 이용 가능한 형태라 완전
// 독점(exclusive)과 다르다 — 충돌 판정에서도 SOLE_VS_SOLE/EXCLUSIVE_VS_SOLE로 구분해서
// 충돌 심각도는 실 API의 reason/severity 값을 기준으로 표시한다.
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
// BEFORE_TERM은 계약 체결 전과 권리 유효기간 전을 하나의 코드로 합친 값이므로,
// 날짜가 없을 때는 어느 한쪽으로 단정하지 않는 문구를 사용한다.
// PRE_CONTRACT(초안, 계약 자체가 아직 확정 전)는 ContractListPage의 draft 표시("미적용")와
// 같은 뜻이라 같은 문구를 쓴다.
export const DISPLAY_STATE_LABEL = {
  PRE_CONTRACT: "미적용",
  BEFORE_TERM: "계약/유효기간 전",
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

// Back API에서 별도 ref로 제공하지 않는 권리 대상 범위 UI 어휘.
// 값은 DB asset_scope_kind enum과 정확히 맞춘다.
export const ASSET_SCOPE_LABEL = {
  SERIES_ALL: "시리즈 전체",
  SEASON: "시즌",
  EPISODE: "에피소드",
  EDITION: "에디션",
};
export const ASSET_SCOPE_OPTIONS = labelMapToOptions(ASSET_SCOPE_LABEL);

function labelMapToOptions(labels) {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

export const EXCLUSIVITY_OPTIONS = labelMapToOptions(EXCLUSIVITY_LABEL);
export const LANG_OPTIONS = labelMapToOptions(LANG_LABEL);

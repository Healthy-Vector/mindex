import { ApiError } from "../api/ApiError.js";

// 충돌 검사(API 명세서 #5 POST /contracts/verify) + 확정 저장(#6 POST /contracts) mock.
// 예전엔 이 두 단계가 이름 없는 "POST /confirm" 하나로 뭉뚱그려져 있었는데, 명세서가
// 나오면서 실제로는 이렇게 둘로 나뉜다는 게 확인됐다 — /confirm이라는 엔드포인트 자체가
// 명세서엔 없다. 사용자가 HITL 화면에서 고친 값은 서버에 저장하지 않고 화면 상태로만
// 들고 있다가, 충돌검사·저장 이 두 호출에만 실어 보낸다.
//
// mock 서버가 없는 동안에는 데모 시나리오 고정값으로 충돌 유무를 재현한다. 응답 형태는
// 실제 API가 반영할 P2 권리 모델(legalRight × exploitationMode)과 동일하게 유지한다.

// exclusivity는 boolean이 아니라 exclusive/sole/non_exclusive 3단계다 — EXCLUDE 제약은
// 둘 중 하나라도 non_exclusive면 걸리지 않는다(비독점은 원래 여러 계약이 겹쳐도 되는
// 권리다). 그래서 심각도도 EXCLUSIVE_VS_EXCLUSIVE/EXCLUSIVE_VS_SOLE/SOLE_VS_SOLE
// 3종류뿐이고, "비독점 상호 중복"은 애초에 충돌 후보가 아니다.
function conflictSeverity(existingExclusivity, incomingExclusivity) {
  if (existingExclusivity === "non_exclusive" || incomingExclusivity === "non_exclusive") return null;
  if (existingExclusivity === "exclusive" && incomingExclusivity === "exclusive") return "EXCLUSIVE_VS_EXCLUSIVE";
  if (existingExclusivity === "sole" && incomingExclusivity === "sole") return "SOLE_VS_SOLE";
  return "EXCLUSIVE_VS_SOLE";
}

const CANDIDATE = {
  title: "Fintrex 게임화 라이선스 (검토중)",
  ip: "Fintrex App Suite v3",
  territory: "JP",
  legalRight: "DISTRIBUTION",
  exploitationMode: "TVOD",
  period: { start: "2025-01-01", end: "2027-12-31" },
  exclusivity: "exclusive",
};

// scenario별로 검토중인 건(candidate)과 겹치는 기존 rights_grant 후보. quotes는 원문
// 인용 팝업(충돌 칩 클릭)에 쓴다.
const SCENARIOS = {
  conflict: [
    {
      existing: {
        contractId: 103,
        title: "Fintrex App Suite v3 배포권 계약",
        grantee: "Fintrex Inc.",
        rightsGrantId: 10131,
        territory: "JP",
        legalRight: "DISTRIBUTION",
        exploitationMode: "TVOD",
        period: { start: "2024-10-01", end: "2029-09-30" },
        exclusivity: "exclusive",
        evidence: "제 5조 [권리의 독점] 갑은 을에게 배포에 관한 독점적 권리를 부여한다.",
      },
      incomingEvidence: "제 4조 [권리의 범위] 권리 유형: 독점적 배포권",
    },
  ],
  clean: [],
};

function overlapRange(a, b) {
  const start = new Date(a.start) > new Date(b.start) ? a.start : b.start;
  const end = new Date(a.end) < new Date(b.end) ? a.end : b.end;
  if (new Date(start) > new Date(end)) return null;
  const days = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86400000) + 1;
  return { start, end, days };
}

function buildConflicts(scenario) {
  return SCENARIOS[scenario]
    .map(({ existing, incomingEvidence }) => {
      if (existing.territory !== CANDIDATE.territory) return null;
      const overlap = overlapRange(existing.period, CANDIDATE.period);
      if (!overlap) return null;
      const severity = conflictSeverity(existing.exclusivity, CANDIDATE.exclusivity);
      if (!severity) return null;
      return {
        severity,
        territory: existing.territory,
        legalRight: existing.legalRight,
        exploitationMode: existing.exploitationMode,
        overlap,
        incoming: { ...CANDIDATE, evidence: incomingEvidence },
        existing,
      };
    })
    .filter(Boolean);
}

// scenario는 실제로는 tmpid/rights[]로 서버가 판정할 값 — 백엔드가 없어 데모 토글로
// 대신 받는다(ConflictCheckPage의 "데모: 충돌 있음/없음" 버튼).
export function mockVerifyContract({ scenario = "conflict" } = {}) {
  const conflicts = buildConflicts(scenario);
  return { hasConflict: conflicts.length > 0, checkedRows: SCENARIOS[scenario].length, conflicts, candidate: CANDIDATE };
}

// tmpid → 첫 저장 결과. API 명세서 #6 "구현 시 주의" — 같은 tmpid로 두 번째 요청이 오면
// 409 ALREADY_CONFIRMED와 함께 첫 결과를 그대로 돌려준다(중복 확정 방지).
const confirmedByTmpId = new Map();

export function mockSaveContract({ tmpId, mode, scenario = "conflict" } = {}) {
  if (tmpId && confirmedByTmpId.has(tmpId)) {
    throw new ApiError(409, { code: "ALREADY_CONFIRMED", ...confirmedByTmpId.get(tmpId) });
  }
  const conflicts = buildConflicts(scenario);
  const hasConflict = conflicts.length > 0;
  const isFinal = mode === "final";
  const result = {
    contractId: 1000 + Math.floor(Math.random() * 1000),
    version: isFinal ? "final" : "v1",
    contractStatus: isFinal && !hasConflict ? "signed" : "draft",
    historyStatus: hasConflict ? "conflicted" : "applied",
    savedRights: hasConflict
      ? []
      : [
          {
            territory: CANDIDATE.territory,
            legalRight: CANDIDATE.legalRight,
            exploitationMode: CANDIDATE.exploitationMode,
            status: "active",
          },
        ],
    conflicts,
    stagingCleared: true,
  };
  if (tmpId) confirmedByTmpId.set(tmpId, result);
  return result;
}

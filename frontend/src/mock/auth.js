import { ApiError } from "../api/ApiError.js";

// 팀 PIN 인증 mock — 실 team.pin_hash 대조는 백엔드에 아직 없어 데모 PIN으로 대신한다.
// x-api-key 헤더로 이미 팀이 식별되므로(요청 전체 공통), 실 엔드포인트도 pin 하나만 받으면 된다.
// 응답 shape은 API 명세서 #1 POST /auth/pin 기준(sessionToken/expiresAt/ttlSeconds) —
// ttlSeconds는 초 단위다(예전엔 expiresInMs로 밀리초를 썼었다).
export const DEMO_PIN = "1234";
const DEMO_SESSION_SEC = 15 * 60;

export function mockVerifyPin(pin) {
  // 상태 코드 표 — 401 PIN 세션 없음 또는 만료(여기선 PIN 자체 불일치도 401로 취급).
  if (pin !== DEMO_PIN) throw new ApiError(401, "PIN이 일치하지 않습니다 (데모 데이터).");
  return {
    sessionToken: "mock-session-token",
    expiresAt: new Date(Date.now() + DEMO_SESSION_SEC * 1000).toISOString(),
    ttlSeconds: DEMO_SESSION_SEC,
  };
}

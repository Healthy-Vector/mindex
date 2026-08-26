// PIN 세션 토큰을 컴포넌트 트리 밖에서도 꺼내 쓰기 위한 모듈 스코프 저장소 — api/client.js의
// fetchContractFile()처럼 React 컴포넌트가 아닌 곳에서 Authorization 헤더에 실어야 할 때 쓴다.
// sliding expiration 응답 헤더를 API 계층에서 받고 상세 화면 카운트다운에 알리기 위해
// 토큰과 만료 시각을 함께 보관한다. URL 쿼리에 토큰을 실으면 브라우저 히스토리·로그에
// 남으므로 반드시 Authorization 헤더로만 보낸다.
let token = null;
let expiresAt = null;
const expiryListeners = new Set();

export function getPinSessionToken() {
  return token;
}

export function setPinSessionToken(next) {
  token = next;
}

export function getPinSessionExpiresAt() {
  return expiresAt;
}

export function setPinSessionExpiresAt(next) {
  const parsed = typeof next === "number" ? next : Date.parse(next);
  expiresAt = Number.isFinite(parsed) ? parsed : null;
  for (const listener of expiryListeners) listener(expiresAt);
}

export function clearPinSession() {
  token = null;
  setPinSessionExpiresAt(null);
}

export function hasActivePinSession() {
  return Boolean(token && expiresAt && expiresAt > Date.now());
}

export function subscribePinSessionExpiresAt(listener) {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

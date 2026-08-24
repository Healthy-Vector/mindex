import { useSyncExternalStore } from "react";

// PIN 세션 잔여 시간을 상단 네비 배지에 보여주기 위한 공유 스토어. 세션 상태 자체는
// ContractDetailPage의 PinGate 안에만 존재하므로(새로고침 시 재잠금), 배지 문구만 여기로 올려보낸다.
let label = null; // string | null — null이면 배지 자체를 숨긴다.
const listeners = new Set();

function notify() {
  for (const fn of listeners) fn();
}
function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function getSnapshot() {
  return label;
}

export function useSecuritySessionLabel() {
  return useSyncExternalStore(subscribe, getSnapshot);
}

export function setSecuritySessionLabel(next) {
  label = next;
  notify();
}

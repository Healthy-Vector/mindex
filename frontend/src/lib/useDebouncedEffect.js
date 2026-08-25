import { useEffect } from "react";

// deps가 바뀔 때마다 delay(ms) 후에 effect를 실행한다. 그 전에 deps가 다시 바뀌면 예약된
// 실행은 취소된다 — 검색어 입력처럼 매 변경마다 요청을 보내면 안 되는 곳에 쓴다.
export function useDebouncedEffect(effect, deps, delay = 300) {
  useEffect(() => {
    let cleanup;
    const timer = setTimeout(() => {
      cleanup = effect();
    }, delay);
    return () => {
      clearTimeout(timer);
      cleanup?.();
    };
  }, deps);
}

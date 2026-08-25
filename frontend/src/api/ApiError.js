// 상태 코드·파싱된 응답 바디를 그대로 들고 있는 에러 — 호출부가 err.message 문자열
// 파싱 없이 err.status/err.body로 분기할 수 있어야 409(중복) 같은 특정 코드에 맞는
// 복구 동작(예: "기존 IP 사용하기")을 붙일 수 있다. client.js와 mock/* 양쪽에서
// 공유해야 해서(순환 import를 피하려고) 별도 파일로 뺐다.
export class ApiError extends Error {
  constructor(status, body) {
    // body가 문자열이면 그대로, {message} 필드가 있는 구조화 바디면 그 문구를 쓴다 —
    // 화면에 err.message를 그대로 띄우는 곳(계약 종료 모달, IP 관리 에러 배너 등)이
    // 있어서 사람이 읽을 문장이 아니면 JSON 덩어리가 그대로 노출된다. DUPLICATE_IP처럼
    // message 필드가 없는 바디(호출부가 err.body를 직접 읽어 복구 UI를 만드는 경우)만
    // JSON.stringify로 대체한다.
    const text = typeof body === "string" ? body : (body?.message ?? JSON.stringify(body));
    super(`API 오류 ${status}: ${text}`);
    this.status = status;
    this.body = body;
  }
}

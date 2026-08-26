// status/body를 그대로 보존해 호출부가 err.status·err.body로 분기해 409(중복) 등
// 상태 코드별 복구 동작을 붙일 수 있게 한다.
export class ApiError extends Error {
  constructor(status, body) {
    // message 필드가 있으면 그 문구를, 없으면(예: DUPLICATE_IP) JSON.stringify로 대체 —
    // err.message를 그대로 화면에 띄우는 곳에서 JSON 덩어리가 노출되지 않게 한다.
    const text = typeof body === "string" ? body : (body?.message ?? JSON.stringify(body));
    super(`API 오류 ${status}: ${text}`);
    this.status = status;
    this.body = body;
  }
}

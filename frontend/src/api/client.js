// FastAPI 백엔드 연동. 개발 중에는 vite.config.js의 프록시(/api → :8000)를 탄다.

const BASE_URL = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API 오류 ${res.status}: ${body}`);
  }
  return res.json();
}

// TODO: 백엔드 app/api/contracts.py 라우터가 완성되면 경로를 맞춘다.
export const api = {
  listContracts: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/contracts${qs ? `?${qs}` : ""}`);
  },
  getContract: (id) => request(`/contracts/${id}`),
  search: (query) => request(`/search?q=${encodeURIComponent(query)}`),
};

import { clearPinSession, getPinSessionToken, setPinSessionExpiresAt } from "../lib/pinSession.js";
import { ApiError } from "./ApiError.js";
import {
  normalizeContract,
  normalizeContractListItem,
  normalizeIp,
  normalizeJob,
  normalizeVerifyResult,
} from "../lib/apiNormalizers.js";
import { buildConfirmPayload, buildVerifyPayload } from "../lib/contractPayload.js";

// 실 백엔드 주소가 정해지면 그 환경(Vercel 등)에 VITE_API_BASE_URL을 설정한다 — 코드
// 수정 없이 배포 환경변수만 바꾸면 된다. 안 정해져 있으면 "/api"로 남아있고, 이건
// vite.config.js의 dev 프록시(java-backend :8081)를 그대로 탄다. vercel.json은 SPA
// 라우팅용 rewrite만 있고 /api를 실 백엔드로 넘기는 규칙이 없으므로, prod 배포 환경에서는
// VITE_API_BASE_URL을 반드시 실제 API 주소로 설정한다.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";
const API_KEY = import.meta.env.VITE_API_KEY ?? "";
export { ApiError };

// PIN 세션이 필요한 엔드포인트(#8 상세·#9 파일·#10 이력·#11 종료)만 골라 헤더를 다르게
// 짜는 대신, 토큰이 있으면 항상 실어 보낸다 — PIN 불필요 엔드포인트는 서버가 이 헤더를
// 그냥 무시하면 되고, 호출부마다 "이 엔드포인트는 PIN 필요던가?"를 기억할 필요가 없다.
function authHeaders() {
  const token = getPinSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function withQuery(path, values = {}) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function contractFileUrl(id, { historyId, disposition } = {}) {
  return `${BASE_URL}${withQuery(`/contracts/${id}/file`, { historyId, disposition })}`;
}

// sliding expiration의 표준 응답 헤더. 전환 중인 백엔드와의 호환을 위해 짧은 별칭도
// 읽지만 신규 구현은 X-Pin-Session-Expires-At(ISO-8601)을 사용한다.
function syncPinSessionExpiry(res) {
  const value = res.headers.get("X-Pin-Session-Expires-At") ?? res.headers.get("X-Session-Expires-At");
  if (value) setPinSessionExpiresAt(value);
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "x-api-key": API_KEY,
      ...authHeaders(),
    },
    ...options,
  });
  syncPinSessionExpiry(res);
  if (!res.ok) {
    if (res.status === 401 && getPinSessionToken()) clearPinSession();
    const text = await res.text().catch(() => "");
    let body = text;
    try {
      body = JSON.parse(text);
    } catch {
      // 바디가 JSON이 아니면(예: HTML 에러 페이지) 원문 텍스트를 그대로 둔다.
    }
    throw new ApiError(res.status, body);
  }
  return res.json();
}

export const api = {
  listContracts: async ({ includeProcessing = true, page, size } = {}) => {
    const res = await request(withQuery("/contracts", { include_processing: includeProcessing, page, size }));
    return { ...res, items: (res.items ?? []).map(normalizeContractListItem) };
  },
  getContract: async (id, { historyId } = {}) => {
    return normalizeContract(await request(withQuery(`/contracts/${id}`, { historyId })));
  },
  // 계약 종료 — API 명세서 #11 POST /contracts/{id}/cancel. reason은
  // cancelled(해지)/expired(만료)/waiver(권리포기) 중 하나(필수).
  cancelContract: async (id, { reason, note }) => {
    return request(`/contracts/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason, note }) });
  },
  // 원본 PDF — API 명세서 #9 GET /contracts/{id}/file. historyId 생략 시 현재 유효 버전.
  // PIN 세션이 필요한 엔드포인트라 <a href>/<img src>로 바로 못 건다 — 쿼리에 토큰을
  // 실으면 브라우저 히스토리·서버 로그에 남으므로, Authorization 헤더로 인증한 뒤
  // Blob으로 받는다.
  fetchContractFile: async (id, { historyId, disposition } = {}) => {
    const res = await fetch(contractFileUrl(id, { historyId, disposition }), {
      headers: { "x-api-key": API_KEY, ...authHeaders() },
    });
    syncPinSessionExpiry(res);
    if (!res.ok) {
      if (res.status === 401 && getPinSessionToken()) clearPinSession();
      throw new ApiError(res.status, "원본 PDF를 불러오지 못했습니다.");
    }
    return res.blob();
  },
  // 팀 공유 PIN 인증 — team.pin_hash와 대조해 세션을 발급하는 흐름을 프론트가 제안한다.
  // 실패 시(PIN 불일치) request()가 던지는 에러를 호출부(ContractDetailPage)가 그대로 잡는다.
  verifyPin: async (pin) => {
    return request(`/auth/pin`, { method: "POST", body: JSON.stringify({ pin }) });
  },
  // API 명세서 #15 — GET이 아니라 POST다(질의문이 길고 필터 객체가 중첩되기 때문).
  // 화면엔 자연어/교차언어 모드 구분이 없어졌으니(Notion §0) mode 파라미터도 안 보낸다 —
  // 교차언어 여부는 결과 카드별 sourceLang으로만 판단한다.
  search: (query, { filters, limit } = {}) => {
    return request(`/search`, { method: "POST", body: JSON.stringify({ query, filters, limit }) });
  },
  // OCR/AI 추출 파이프라인(k8s 워커 파드가 비동기로 처리):
  //   POST /extract            (multipart, PDF 파일) → 202 { tmpid, status: "QUEUED" }
  //   GET  /extract/{tmpid}    → 200 { tmpid, status: "RUNNING", stage: "OCR" | "LLM" }
  //                            → 200 { tmpid, status: "DONE", result: {...} }     (Rich Extraction)
  //                            → 200 { tmpid, status: "FAILED", reason: "OCR_TIMEOUT" }
  // normalizeJob이 status/stage를 UI 단계 이름(queued/ocr/llm/extract/failed)으로 맞춘다.
  // mode(new/revision/final)는 필수다. HTML 명세 #2에 따라 revision·final은 기존
  // contractId와 ipId를 모두 보낸다.
  startUploadJob: async (file, { mode = "new", contractId, ipId } = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    if (contractId) form.append("contractId", contractId);
    if (ipId) form.append("ipId", ipId);
    const res = await fetch(`${BASE_URL}/extract`, { method: "POST", headers: { "x-api-key": API_KEY, ...authHeaders() }, body: form });
    syncPinSessionExpiry(res);
    if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => ""));
    return normalizeJob(await res.json());
  },
  // 폴링 응답엔 fileName이 없다 — 새로고침 후 tmpId로 복원해도 파일명을 보여주려면
  // 업로드 시점부터 프론트가 별도로 들고 있어야 한다.
  getUploadJob: async (tmpId) => {
    return normalizeJob(await request(`/extract/${tmpId}`));
  },
  // HITL 검증 화면 → "충돌검사 실행" 클릭 시 호출. API 명세서 #5 POST /contracts/verify —
  // master 스키마에 실제로 INSERT를 시도해보고 무조건 롤백한다(결과만 받고 아무것도 안 남음).
  // HITL에서 고친 값은 서버에 저장하지 않고 화면 상태로만 들고 있다가 이 호출과
  // saveContract 호출에만 실어 보낸다.
  verifyContract: async (payload) => {
    // 화면 상태는 그대로 유지하고, 실제 요청 직전에 API가 요구하는 grantor/grantee와
    // 파일 메타데이터 중심의 스키마로 변환한다.
    const result = await request(`/contracts/verify`, { method: "POST", body: JSON.stringify(buildVerifyPayload(payload)) });
    return normalizeVerifyResult(result, payload);
  },
  // "저장" 버튼 → API 명세서 #6 POST /contracts. 충돌 여부와 무관하게 항상 커밋된다
  // (충돌이면 draft/conflicted로, 아니면 mode에 따라 draft·signed/applied로).
  saveContract: async (payload) => {
    return request(`/contracts`, { method: "POST", body: JSON.stringify(buildConfirmPayload(payload)) });
  },

  // IP 관리 — API 명세서 #12 GET /ips 기준. 쿼리 파라미터는 includeInactive(기본 false) —
  // activeOnly가 아니다. ip.activity 자체는 boolean이 아니라 ENUM('active'|'deactive')이라
  // lib/ip.js의 isIpActive()로 판정한다.
  searchIps: async (query, { includeInactive, page, size } = {}) => {
    const res = await request(withQuery("/ips", { q: query, includeInactive, page, size }));
    const items = Array.isArray(res) ? res : (res.items ?? []);
    return {
      ...(Array.isArray(res) ? {} : res),
      items: items.map(normalizeIp),
      total: Array.isArray(res) ? items.length : (res.total ?? items.length),
    };
  },
  getIp: async (id) => {
    return normalizeIp(await request(`/ips/${id}`));
  },
  createIp: async (form) => {
    return normalizeIp(await request(`/ips`, { method: "POST", body: JSON.stringify(form) }));
  },
  updateIp: async (id, patch) => {
    return normalizeIp(await request(`/ips/${id}`, { method: "PATCH", body: JSON.stringify(patch) }));
  },
  // API 명세서 #4 GET /ips/match — 업로드 화면 IP 매칭 콤보박스 전용(#12 GET /ips와는
  // 다른 엔드포인트). score/matchedAlias/matchedBy/assets/relations가 같이 온다. 추출
  // 완료 직후의 자동 매칭은 이 API를 또 부르지 않는다 — result.ipCandidates에 이미
  // 같은 shape으로 실려있다(UploadPage.jsx 참고).
  matchIps: async (query, { limit, includeInactive } = {}) => {
    const res = await request(withQuery("/ips/match", { q: query, limit, includeInactive }));
    return (res.items ?? res).map(normalizeIp);
  },

  // 참조 코드 — API 명세서 #16 GET /refs. 지역·지역그룹·IP유형·범위유형·관계유형·충돌코드는
  // 이 호출로 받는다. 값이 자주 안 바뀌므로 useRefs()가 모듈 스코프로 캐시해서 페이지마다
  // 다시 부르지 않는다.
  getRefs: async ({ types, lang = "ko" } = {}) => {
    return request(withQuery("/refs", { types: types?.length ? types.join(",") : undefined, lang }));
  },
};

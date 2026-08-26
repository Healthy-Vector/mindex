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
  // 204 No Content(#18 DELETE)는 바디가 비어 있어 res.json()이 파싱 에러를 던진다.
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // displayStates — 권리 유효 상태 필터(PRE_CONTRACT/BEFORE_TERM/IN_TERM/EXPIRING/EXPIRED,
  // 콤마로 복수 지정 가능). feat/staging-verify-merge에서 추가된 파라미터로, alias가
  // camelCase라 include_processing과 달리 그대로 displayStates로 보낸다.
  listContracts: async ({ includeProcessing = true, displayStates, page, size } = {}) => {
    const res = await request(withQuery("/contracts", { include_processing: includeProcessing, displayStates, page, size }));
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
  // 화면은 등록 유형을 신규/버전/최종 3가지로 보여주지만, API의 mode는 draft/final
  // 2값이다 — "신규냐 개정이냐"는 contractId 유무로 이미 구분되기 때문이다(D-37).
  // 그래서 신규·버전 계약은 모두 draft로, 최종 계약만 final로 보낸다.
  startUploadJob: async (file, { mode = "new", contractId, ipId } = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode === "final" ? "final" : "draft");
    if (contractId) form.append("contractId", contractId);
    if (ipId) form.append("ipId", ipId);
    const res = await fetch(`${BASE_URL}/extract`, { method: "POST", headers: { "x-api-key": API_KEY, ...authHeaders() }, body: form });
    syncPinSessionExpiry(res);
    if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => ""));
    return normalizeJob(await res.json());
  },
  // 폴링 응답은 tmpId로 업로드 맥락(mode/contractId/ipId)과 추출 결과를 복원한다.
  // 검증 이후에는 서버 staging에 저장된 사용자 수정본이 result로 돌아온다.
  getUploadJob: async (tmpId) => {
    return normalizeJob(await request(`/extract/${tmpId}`));
  },
  // HITL 검증 화면 → "충돌검사 실행" 클릭 시 호출. API 명세서 #5 POST /contracts/verify —
  // tmpId와 patch를 보내면 서버가 사용자 수정본을 staging에 저장한 뒤 그 값으로 판정한다.
  // 이 단계는 예상 충돌검사라 최종 계약/권리 INSERT는 하지 않는다.
  verifyContract: async (payload) => {
    const result = await request(`/contracts/verify`, { method: "POST", body: JSON.stringify(buildVerifyPayload(payload)) });
    return normalizeVerifyResult(result, payload);
  },
  // "저장" 버튼 → API 명세서 #6 POST /contracts. 서버가 staging 수정본과 원본 PDF를 읽어
  // contract_history를 먼저 남기고, 가능한 경우 rights_grant를 확정한다.
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
  // 권리 대상(content_asset) — API 명세서 #18. IP 본체(#14)와 달리 배열 전체 교체가
  // 아니라 행 단위다: 통째로 보내는 경로 자체가 없어야 "빈 배열로 저장해 기존 권리
  // 대상을 지우는" 사고가 구조적으로 불가능해진다. 응답은 IP가 아니라 권리 대상 한
  // 건이라 normalizeIp를 태우지 않는다.
  // 권리가 걸린 대상의 수정·삭제, IP의 마지막 대상 삭제는 409 ASSET_IN_USE로 막히고,
  // err.body.error.details(rightsGrantCount / assetCount)로 두 경우를 구분한다.
  // mock(ipDirectory.js)에는 대응 구현이 없다 — 편집 UI를 켤 때 함께 채운다.
  createIpAsset: async (ipId, asset) => {
    return request(`/ips/${ipId}/assets`, { method: "POST", body: JSON.stringify(asset) });
  },
  // 보낸 필드만 반영된다. scopeType을 넓힐 때는 남는 seasonNo/episodeNo/editionCode를
  // 함께 null로 보내야 한다 — 서버가 기존 행과 병합한 뒤 검증해서 400을 돌려준다.
  updateIpAsset: async (ipId, assetId, patch) => {
    return request(`/ips/${ipId}/assets/${assetId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  },
  // 204 No Content — 반환값 없음.
  deleteIpAsset: async (ipId, assetId) => {
    return request(`/ips/${ipId}/assets/${assetId}`, { method: "DELETE" });
  },

  // API 명세서 #4 GET /ips/match — 업로드 화면 IP 매칭 콤보박스 전용(#12 GET /ips와는
  // 다른 엔드포인트). score/matchedAlias/matchedBy/assets/relations가 같이 온다. 추출
  // 완료 직후의 자동 매칭은 이 API를 또 부르지 않는다 — result.ipCandidates에 이미
  // 같은 shape으로 실려있다(UploadPage.jsx 참고).
  matchIps: async (query, { limit, includeInactive } = {}) => {
    const res = await request(withQuery("/ips/match", { q: query, limit, includeInactive }));
    return (res.matches ?? res).map(normalizeIp);
  },

  // 참조 코드 — API 명세서 #16 GET /refs. 지역·지역그룹·IP유형·범위유형·관계유형·충돌코드는
  // 이 호출로 받는다. 값이 자주 안 바뀌므로 useRefs()가 모듈 스코프로 캐시해서 페이지마다
  // 다시 부르지 않는다.
  getRefs: async ({ types, lang = "ko" } = {}) => {
    return request(withQuery("/refs", { types: types?.length ? types.join(",") : undefined, lang }));
  },
};

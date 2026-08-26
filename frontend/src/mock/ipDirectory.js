// IP 마스터 데이터 인메모리 스토어. IP 관리 화면과 업로드 화면의 IP 매칭이 공유한다.
// api/client.js가 이 파일을 호출하며, 실 API가 붙으면 api/client.js 쪽 분기만 바뀐다
// (mock/contracts.js, mock/uploadJobs.js와 같은 패턴).
import { isIpActive } from "../lib/ip.js";
import { ApiError } from "../api/ApiError.js";

function normalize(text) {
  return (text ?? "").toString().trim().toLowerCase().replace(/\s+/g, "");
}

let nextId = 5;
let nextAssetId = 104;
let ips = [
  {
    id: 1,
    title: "Fintrex App Suite v3",
    kind: "MOBILE_APP",
    activity: "active",
    assets: [{ contentAssetId: 100, scopeType: "SERIES_ALL", title: "Fintrex App Suite v3" }],
    updatedAt: "2026-07-02",
    aliases: [
      { lang: "ko", aliasType: "정식명", text: "핀트렉스 앱 스위트" },
      { lang: "en", aliasType: "정식명", text: "Fintrex App Suite" },
      { lang: "ja", aliasType: "정식명", text: "フィントレックス・アプリ・スイート" },
    ],
  },
  {
    id: 2,
    title: "Mirage Game Engine Pro",
    kind: "GAME_SOFTWARE",
    activity: "active",
    assets: [{ contentAssetId: 101, scopeType: "SERIES_ALL", title: "Mirage Game Engine Pro" }],
    updatedAt: "2026-06-18",
    aliases: [
      { lang: "ko", aliasType: "정식명", text: "미라지 게임 엔진 프로" },
      { lang: "en", aliasType: "정식명", text: "Mirage Game Engine Pro" },
      { lang: "en", aliasType: "약칭", text: "MGE Pro" },
      { lang: "ja", aliasType: "정식명", text: "ミラージュ・ゲームエンジン・プロ" },
    ],
  },
  {
    id: 3,
    title: "노을빛 소년단",
    kind: "DRAMA",
    activity: "active",
    assets: [{ contentAssetId: 102, scopeType: "SERIES_ALL", title: "노을빛 소년단" }],
    updatedAt: "2026-08-11",
    aliases: [
      { lang: "ko", aliasType: "정식명", text: "노을빛 소년단" },
      { lang: "en", aliasType: "정식명", text: "Boys of the Afterglow" },
      { lang: "ja", aliasType: "정식명", text: "残照の少年団" },
    ],
  },
  {
    id: 4,
    title: "Fintrex OST Collection",
    kind: "MUSIC_OST",
    activity: "deactive",
    assets: [{ contentAssetId: 103, scopeType: "EDITION", title: "Fintrex OST Collection" }],
    updatedAt: "2025-02-04",
    aliases: [
      { lang: "ko", aliasType: "정식명", text: "핀트렉스 OST 컬렉션" },
      { lang: "en", aliasType: "정식명", text: "Fintrex OST Collection" },
    ],
  },
];

// includeInactive 기본값은 API 명세서 #12 기준 false(활성만) — activeOnly(반대 극성)가 아니다.
export function mockSearchIps(query, { includeInactive = false, page = 1, size = 20 } = {}) {
  const q = normalize(query);
  const matches = ips.filter((ip) => {
    if (!includeInactive && !isIpActive(ip)) return false;
    if (!q) return true;
    const haystacks = [ip.title, ...ip.aliases.map((a) => a.text)].map(normalize);
    return haystacks.some((h) => h.includes(q));
  });
  const start = (page - 1) * size;
  return { items: matches.slice(start, start + size), total: matches.length, page, size };
}

// API 명세서 #4 GET /ips/match — 업로드 화면의 IP 매칭 콤보박스 전용. #12(GET /ips, IP
// 관리 목록)와 달리 유사도 점수·매칭 근거(제목/별칭)를 같이 내려준다. title이 정확히
// 일치하면 1.0, 별칭이 정확히 일치하면 0.95, 부분 일치는 그보다 낮게 — 실제 임베딩 유사도
// 계산이 아니라 데모용 근사치다.
export function mockMatchIps(query, { limit = 10, includeInactive = false } = {}) {
  const q = normalize(query);
  const scored = ips
    .filter((ip) => includeInactive || isIpActive(ip))
    .map((ip) => {
      if (!q) return { ip, matchedAlias: null, matchedBy: null, score: 1 };
      const titleNorm = normalize(ip.title);
      if (titleNorm.includes(q)) return { ip, matchedAlias: null, matchedBy: "title", score: titleNorm === q ? 1 : 0.85 };
      const aliasHit = ip.aliases.find((a) => normalize(a.text).includes(q));
      if (aliasHit) {
        const aliasNorm = normalize(aliasHit.text);
        return { ip, matchedAlias: aliasHit.text, matchedBy: "alias", score: aliasNorm === q ? 0.95 : 0.75 };
      }
      return null;
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
  return scored.map(({ ip, matchedAlias, matchedBy, score }) => ({
    ipId: ip.id,
    title: ip.title,
    kind: ip.kind,
    matchedAlias,
    matchedBy,
    score,
    assets: ip.assets ?? [],
    relations: [],
  }));
}

export function mockGetIp(id) {
  return ips.find((ip) => String(ip.id) === String(id)) ?? null;
}

// API 명세서 #13 "구현 시 주의" — 같은 정규화 키(제목을 normalize()한 값)의 IP가 이미
// 있으면 409와 기존 ipId를 함께 돌려준다. 중복 생성 대신 기존 걸 고를 수 있게 하려는
// 목적이라, 호출부는 이 ApiError를 잡아서 "기존 IP 사용" 복구 동작을 붙여야 한다.
export function mockCreateIp({ title, kind, aliases, assets }) {
  const key = normalize(title);
  const existing = ips.find((ip) => normalize(ip.title) === key);
  if (existing) {
    throw new ApiError(409, { code: "DUPLICATE_IP", ipId: existing.id, title: existing.title });
  }
  // assets 생략 시 SERIES_ALL 하나만 자동 생성(명세서 #13 payload 설명 그대로).
  const resolvedAssets =
    assets?.length > 0
      ? assets.map((a) => ({ contentAssetId: nextAssetId++, scopeType: a.scopeType, title: a.title || title }))
      : [{ contentAssetId: nextAssetId++, scopeType: "SERIES_ALL", title }];
  const ip = {
    id: nextId++,
    title,
    kind,
    activity: "active",
    updatedAt: new Date().toISOString().slice(0, 10),
    aliases,
    assets: resolvedAssets,
  };
  ips = [ip, ...ips];
  return ip;
}

export function mockUpdateIp(id, patch) {
  ips = ips.map((ip) => (String(ip.id) === String(id) ? { ...ip, ...patch, updatedAt: new Date().toISOString().slice(0, 10) } : ip));
  return mockGetIp(id);
}

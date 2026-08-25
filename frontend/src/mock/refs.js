// 참조 코드 mock — API 명세서 #16 GET /refs. 지역/지역그룹/IP유형/범위유형/관계유형은
// 여기서 서버가 내려주는 값으로 취급한다(예전엔 labels.js에 하드코딩된 JS 상수였다).
// 실 API 명세가 legalRight/exploitationMode 두 축을 추가하는 동안 mock도 같은 응답 구조를
// 제공한다. 화면은 mock/real 여부와 관계없이 useRefs()만 사용한다.

// sql/init/03_reference_data.sql 시드 국가 16개 — in_scope(WORLDWIDE 전개 대상) 8개
// (KR·JP·US·CN·TW·TH·VN·SG) + 전개 대상 밖이지만 계약서에 등장할 수 있어 어휘로
// 유지되는 8개(GB·FR·DE·ID·MY·PH·HK·AU).
const IN_SCOPE = new Set(["KR", "JP", "US", "CN", "TW", "TH", "VN", "SG"]);
const COUNTRY = [
  ["KR", "한국"], ["JP", "일본"], ["US", "미국"], ["CN", "중국"], ["TW", "대만"], ["TH", "태국"],
  ["VN", "베트남"], ["SG", "싱가포르"], ["GB", "영국"], ["FR", "프랑스"], ["DE", "독일"],
  ["ID", "인도네시아"], ["MY", "말레이시아"], ["PH", "필리핀"], ["HK", "홍콩"], ["AU", "호주"],
].map(([code, label]) => ({ code, label, inScope: IN_SCOPE.has(code) }));

const TERRITORY_GROUP = [
  { code: "WORLDWIDE", label: "전 세계", countries: ["KR", "JP", "US", "CN", "TW", "TH", "VN", "SG"] },
  { code: "APAC", label: "아시아·태평양", countries: ["KR", "JP", "CN", "TW", "TH", "VN", "SG", "HK", "ID", "MY", "PH", "AU"] },
  { code: "SEA", label: "동남아시아", countries: ["TH", "VN", "SG", "ID", "MY", "PH"] },
  { code: "NA", label: "북미", countries: ["US"] },
  { code: "EU", label: "유럽", countries: ["GB", "FR", "DE"] },
];

const IP_KIND = [
  { code: "DRAMA", label: "TV/OTT 시리즈" },
  { code: "FILM", label: "영화" },
  { code: "ANIMATION", label: "애니메이션" },
  { code: "GAME_SOFTWARE", label: "게임 엔진/소프트웨어" },
  { code: "MOBILE_APP", label: "모바일 애플리케이션" },
  { code: "MUSIC_OST", label: "음원/OST (related_asset)" },
];

const SCOPE_TYPE = [
  { code: "SERIES_ALL", label: "시리즈 전체" },
  { code: "SEASON", label: "시즌" },
  { code: "EPISODE", label: "에피소드" },
  { code: "EDITION", label: "에디션" },
];

const RELATION_TYPE = [
  { code: "OST", label: "OST" },
  { code: "REMAKE", label: "리메이크" },
  { code: "SEQUEL", label: "속편" },
  { code: "SPINOFF", label: "스핀오프" },
];

const LEGAL_RIGHT = [
  ["PUBLIC_TRANSMISSION", "공중송신권"],
  ["BROADCAST", "방송권"],
  ["TRANSMISSION", "전송권"],
  ["PUBLIC_PERFORMANCE", "공연·상영권"],
  ["DISTRIBUTION", "배포권"],
  ["REPRODUCTION", "복제권"],
  ["DERIVATIVE_WORK_CREATION", "2차적저작물작성권"],
].map(([code, label]) => ({ code, label }));

const EXPLOITATION_MODE = [
  ["VOD", "주문형 VOD 전반"],
  ["SVOD", "구독형 VOD"],
  ["AVOD", "광고형 VOD"],
  ["TVOD", "건별 과금 VOD"],
  ["TV_LINEAR", "선형 TV 방송"],
  ["THEATRICAL", "극장 상영·배급"],
  ["AUDIO_STREAMING", "오디오 스트리밍"],
].map(([code, label]) => ({ code, label }));

const CONFLICT_CODE = [
  { code: "no_exclusive_overlap", template: "동일 지역·권리유형·기간이 겹치는 독점/단독 권리가 이미 있습니다." },
];

const ALL_REFS = {
  country: COUNTRY,
  territoryGroup: TERRITORY_GROUP,
  ipKind: IP_KIND,
  scopeType: SCOPE_TYPE,
  relationType: RELATION_TYPE,
  legalRight: LEGAL_RIGHT,
  exploitationMode: EXPLOITATION_MODE,
  conflictCode: CONFLICT_CODE,
};

export function mockGetRefs({ types } = {}) {
  if (!types?.length) return ALL_REFS;
  return Object.fromEntries(types.filter((t) => t in ALL_REFS).map((t) => [t, ALL_REFS[t]]));
}

// 업로드 화면(S02)의 AI 추출 결과 데모 데이터.
//
// API 명세서 #3 GET /extract/{tmpid} 응답의 result.ipCandidates — OCR·LLM 추출을
// k8s 워커가 하는 김에 IP 매칭 후보까지 서버가 계산해서 같이 내려준다. 그래서 프론트가
// 따로 "정확히 일치하는 IP 찾기" API를 또 부를 필요가 없다(예전엔 findExactIp로 따로
// 불렀는데, 이 필드의 존재를 몰라서 그랬다 — 중복 호출이었다).
export const MOCK_IP_CANDIDATES = [
  {
    ipId: 1,
    title: "Fintrex App Suite v3",
    kind: "MOBILE_APP",
    matchedAlias: "Fintrex App Suite",
    matchedBy: "alias",
    score: 0.94,
    assets: [{ contentAssetId: 100, scopeType: "SERIES_ALL" }],
    relations: [],
  },
];

export const MOCK_CONTRACT_INFO = {
  title: "Fintrex App Suite v3 게임화 라이선스",
  counterparty: "Contra Labs Co., Ltd.",
  signedDate: "2024-10-01",
  lang: "ko",
  amount: 120000000,
  currency: "KRW",
};

const evidence = (clause, quote, confidence = 0.96) => [{ location: "본문", page: 1, clause, quote, confidence }];

export const MOCK_RIGHTS = [
  {
    contentAssetId: 100,
    territories: ["KR", "JP", "CN", "TW", "TH", "VN", "SG", "HK", "ID", "MY", "PH", "AU"],
    legalRight: "TRANSMISSION",
    exploitationMode: "SVOD",
    exclusivity: "exclusive",
    period: { start: "2024-10-01", end: "2029-09-30" },
    conditionsRaw: null,
    evidence: {
      legalRight: evidence("제 4조 [권리의 범위]", "을은 본 저작물에 대한 독점적 전송권을 갖는다."),
      exploitationMode: evidence("제 4조 [권리의 범위]", "구독형 주문형 비디오 서비스를 통해 이용할 수 있다."),
      territory: evidence("제 3조 [이용허락 지역]", "을은 아시아·태평양 전역에서 권리를 행사할 수 있다."),
      period: evidence("제 7조 [계약 기간]", "유효기간은 2024년 10월 1일부터 2029년 9월 30일까지로 한다."),
      exclusivity: evidence("제 4조 [권리의 범위]", "을은 본 저작물에 대한 독점적 권리를 갖는다."),
    },
  },
];

export const MOCK_RAW_TEXT = [
  "본 계약은 MINDEX IP Management Corp.(이하 '갑')과 Contra Labs Co., Ltd.(이하 '을') 간에 체결한다.",
  "갑은 을에게 'Fintrex App Suite v3'(이하 '본 저작물')에 대한 권리를 양도한다.",
  "을은 '아시아·태평양 전역'에서 본 저작물에 대한 전송권을 행사할 수 있다.",
  "을은 본 저작물에 대한 독점적 전송권 및 2차적 저작물 작성권을 갖는다.",
  "본 계약의 유효기간은 2024년 10월 1일부터 2029년 9월 30일까지 5년으로 한다.",
].join("\n");

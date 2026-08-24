// 통합검색(S06) 데모 데이터 — API 명세서 #15 POST /search 응답 shape.
// 자연어 검색/교차언어 검색은 화면상 모드가 따로 없다 — 같은 목록 안에서 원문 언어가
// 한국어가 아닌 결과에만 카드별로 "교차언어 매칭" 배지를 붙인다(Notion §0 설계).
export const mockSearchResponse = {
  interpreted: {
    territories: ["ID", "VN"],
    exclusivity: "exclusive",
    signedFrom: "2024-01-01",
  },
  stages: ["SQL_FILTER", "VECTOR_RANK", "MAPPED"],
  avgConfidence: 0.924,
  results: [
    {
      contractId: 1,
      title: "Fintrex App Suite v3",
      grantor: "MINDEX Platform",
      grantee: "Contra Labs Co., Ltd.",
      sourceLang: "ko",
      similarity: 0.987,
      matchedFilters: [
        { key: "territoryScope", label: "지역", value: "인도네시아, 베트남" },
        { key: "exclusivity", label: "독점 여부", value: "독점" },
      ],
      snippets: [
        {
          chunkId: "c1-01",
          page: 4,
          clauseNo: "제5조",
          text: "을은 인도네시아 공화국 및 아시아 영토 내에서 본 앱의 독점적 게임 패키징 및 모바일 배포권의 2차 라이선싱을 소유한다.",
          similarity: 0.987,
        },
      ],
    },
    {
      contractId: 3,
      title: "겨울의 신호 SVOD 스트리밍 라이선스",
      grantor: "루미나 픽처스 주식회사",
      grantee: "해솔미디어 주식회사",
      sourceLang: "en",
      similarity: 0.968,
      matchedFilters: [
        { key: "territoryScope", label: "지역", value: "일본" },
        { key: "exclusivity", label: "독점 여부", value: "독점" },
      ],
      snippets: [
        {
          chunkId: "c3-01",
          page: 2,
          clauseNo: "Article 3",
          text: "Licensee shall be granted the exclusive right to distribute and transmit the Work via streaming and online transmission within the Territory of Japan.",
          similarity: 0.968,
        },
      ],
    },
    {
      contractId: 2,
      title: "Mirage Game Engine Pro",
      grantor: "MINDEX Games",
      grantee: "CyberNexus Studio",
      sourceLang: "ko",
      similarity: 0.912,
      matchedFilters: [{ key: "territoryScope", label: "지역", value: "인도네시아" }],
      snippets: [
        {
          chunkId: "c2-01",
          page: 3,
          clauseNo: "제4조",
          text: "본 저작권 범위 내에서 모바일 게임 플랫폼 구축을 위한 제한적이고 철회 가능한 전송 실시 권한을 배분한다.",
          similarity: 0.912,
        },
      ],
    },
    {
      contractId: 4,
      title: "Mirage Game Engine Pro 리메이크 서브라이선스",
      grantor: "MINDEX Games",
      grantee: "CyberNexus Studio",
      sourceLang: "ja",
      similarity: 0.892,
      matchedFilters: [{ key: "territoryScope", label: "지역", value: "일본" }],
      snippets: [
        {
          chunkId: "c4-01",
          page: 1,
          clauseNo: "第2条",
          text: "本Mirage Engineの非独占サブライセンス及び二次ゲーム化開発の有効期間は2025年01月満了予定である。",
          similarity: 0.892,
        },
      ],
    },
  ],
};

export const mockMcpTranscript = {
  command: 'claude-mcp-client call mindex_search_contracts --query "2027 expiration JP streaming"',
  entries: [
    { id: "CTR-2024-01", territory: "JP", rights: "STREAMING (Exclusive)", expiration: "2029-09-30", match: "96.8%" },
    { id: "CTR-2024-02", territory: "JP", rights: "REMAKE (Non-Exclusive)", expiration: "2025-01-15", match: "89.2%" },
  ],
};

export function mockSearch(query) {
  return { query, ...mockSearchResponse };
}

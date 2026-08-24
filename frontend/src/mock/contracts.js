import { ApiError } from "../api/ApiError.js";
import { computeContractStatus } from "../lib/contractStatus.js";

// 계약 목록/상세용 데모 데이터. 날짜는 "오늘로부터 N일"로 계산해서
// 상태값들이 항상 골고루 보이게 한다.
//
// 필드 shape은 P2-DB 브랜치(sql/init/*.sql) 기준이다:
// - title은 contract가 아니라 ip.title(단일 컬럼)에서 온다 — API가 응답에 denormalize
//   해서 내려준다고 가정하고 여기서도 편의상 contract.title로 둔다.
// - 갑/을은 contract.grantor / contract.grantee 플랫 컬럼으로 다룬다 — 예전엔
//   contract.counterparty(을 전용) 하나뿐이라 갑을 저장할 자리가 없었는데(열린 이슈),
//   API 명세서 §7·§8 응답이 이미 grantor/grantee로 되어 있어 그 방향으로 스키마를
//   확정했다(2026-08-24). parties[] 배열 shape은 더 이상 쓰지 않는다.
// - pdfUrl/rawText/file_hash/mime_type/conflict_report(jsonb)/uploaded_at은 contract가
//   아니라 contract_history(PDF 세대)에 속한다 — conflict_report는
//   status='conflicted'일 때만 채워진다(CHECK 제약).
// - rights_grant는 legalRight × exploitationMode(2축) 판정에 evidence(JSONB, 필드별
//   원문 인용)를 곁들이고, content_asset_id(→scopeType으로 단순화해 반영)/lineage_id/
//   terminated_at·terminated_reason·termination_note/conditions_raw를 갖는다.
function daysFromNow(n) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

// extra로 개별 필드를 덮어쓸 수 있다 — 대부분은 기본값(활성/시리즈 전체)이면 충분하고,
// 종료된 권리·특정 시즌 범위 등 몇 건만 데모로 다르게 표시한다.
function grant(id, territory, legalRight, exploitationMode, exclusivity, startOffset, endOffset, clause, extra = {}) {
  const placeholder = { clause, quote: "데모 데이터 — 실제 원문 인용 아님." };
  return {
    id,
    territory,
    legalRight,
    exploitationMode,
    exclusivity,
    period: { start: daysFromNow(startOffset), end: daysFromNow(endOffset) },
    // evidence — P-3(원문 인용 필수) 원칙에 따라 5개 판정 필드 전부 근거가 있어야 한다.
    evidence: {
      legalRight: placeholder,
      exploitationMode: placeholder,
      territory: placeholder,
      period: placeholder,
      exclusivity: placeholder,
    },
    scopeType: "SERIES_ALL", // content_asset.scope_type 단순화 반영 — SERIES_ALL·SEASON·EPISODE·EDITION
    lineageId: id, // 최초 등록 시 자기 id로 시작(default_lineage_id() 트리거와 같은 규칙)
    status: "active", // active | terminated
    terminatedAt: null,
    terminatedReason: null, // superseded | expired | waiver | cancelled
    terminationNote: null,
    conditionsRaw: null, // 원문의 비정형 부가조건
    ...extra,
  };
}

const MOCK_CONTRACTS = [
  {
    id: 101,
    ipId: 1,
    title: "노을빛 소년단 스트리밍 라이선스",
    grantor: "MINDEX Studios",
    grantee: "Contra Labs Co., Ltd.",
    signedDate: daysFromNow(30), // 계약 전
    status: "draft",
    amount: 320000000,
    currentHistory: {
      version: 1,
      documentKind: "draft",
      status: "applied",
      fileName: "CTR-101.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr101",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(30),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Studios, 을 Contra Labs Co., Ltd. ...",
    },
    rightsGrants: [
      grant(10111, "KR", "TRANSMISSION", "SVOD", "exclusive", 45, 45 + 900, "제3조 [스트리밍 전송권]"),
      grant(10112, "JP", "BROADCAST", "TV_LINEAR", "non_exclusive", 45, 45 + 500, "제5조 [TV 방영권]"),
    ],
  },
  {
    id: 102,
    ipId: 2,
    title: "Mirage Game Engine Pro 게임화 라이선스",
    grantor: "MINDEX Games",
    grantee: "CyberNexus Studio",
    signedDate: daysFromNow(-20),
    status: "signed",
    amount: 95000000,
    currentHistory: {
      version: 1,
      documentKind: "final",
      status: "applied",
      fileName: "CTR-102.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr102",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(-20),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Games, 을 CyberNexus Studio ...",
    },
    rightsGrants: [grant(10121, "TW", "TRANSMISSION", "AVOD", "non_exclusive", 25, 25 + 900, "제4조 [게임화 권리]")], // 유효기간 전
  },
  {
    id: 103,
    ipId: 1,
    title: "Fintrex App Suite v3 배포권 계약",
    grantor: "MINDEX Platform",
    grantee: "Fintrex Inc.",
    signedDate: daysFromNow(-500),
    status: "signed",
    amount: 210000000,
    currentHistory: {
      version: 1,
      documentKind: "final",
      status: "applied",
      fileName: "CTR-103.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr103",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(-500),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Platform, 을 Fintrex Inc. ...",
    },
    rightsGrants: [
      // conditionsRaw 데모 — 5축 판정에 안 들어가는 원문 부가조건(비정형 jsonb)이 실제로 있다.
      grant(10131, "ID", "TRANSMISSION", "TVOD", "exclusive", -400, 500, "제2조 [권리 양도 대상]", {
        conditionsRaw: { note: "앱 내 인앱결제 프로모션 화면에는 별도 표기 없이 노출 가능(제2조 단서)." },
      }),
    ], // 계약 기간중
  },
  {
    id: 104,
    ipId: 3,
    title: "핀트렉스 OST 컬렉션 음원 사용권",
    grantor: "MINDEX Music",
    grantee: "Aurora Sound Ltd.",
    signedDate: daysFromNow(-900),
    status: "signed",
    amount: 40000000,
    currentHistory: {
      version: 1,
      documentKind: "final",
      status: "applied",
      fileName: "CTR-104.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr104",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(-900),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Music, 을 Aurora Sound Ltd. ...",
    },
    rightsGrants: [grant(10141, "JP", "TRANSMISSION", "AVOD", "non_exclusive", -800, 76, "제6조 [음원 사용권]", { scopeType: "EDITION" })], // D-90, OST 단품이라 EDITION 범위
  },
  {
    id: 105,
    ipId: 1,
    title: "노을빛 소년단 극장판 배급 계약",
    grantor: "MINDEX Studios",
    grantee: "Silverlake Pictures",
    signedDate: daysFromNow(-600),
    status: "signed",
    amount: 780000000,
    currentHistory: {
      version: 1,
      documentKind: "final",
      status: "applied",
      fileName: "CTR-105.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr105",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(-600),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Studios, 을 Silverlake Pictures ...",
    },
    rightsGrants: [grant(10151, "US", "PUBLIC_PERFORMANCE", "THEATRICAL", "sole", -550, 50, "제3조 [극장 상영권]")], // D-60
  },
  {
    id: 106,
    ipId: 2,
    title: "Mirage Game Engine Pro 동남아 재라이선스",
    grantor: "MINDEX Games",
    grantee: "Fintrex Inc.",
    signedDate: daysFromNow(-100),
    status: "signed",
    amount: 60000000,
    currentHistory: {
      version: 1,
      documentKind: "final",
      status: "applied",
      fileName: "CTR-106.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr106",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(-100),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Games, 을 Fintrex Inc. ...",
    },
    rightsGrants: [grant(10161, "VN", "TRANSMISSION", "TVOD", "exclusive", -90, 18, "제4조 [게임화 권리]")], // D-30
  },
  {
    id: 107,
    ipId: 1,
    title: "노을빛 소년단 구 시즌 방영권 계약",
    grantor: "MINDEX Studios",
    grantee: "CyberNexus Studio",
    signedDate: daysFromNow(-1200),
    status: "signed", // 기간만료는 날짜 계산값이지 계약 취소가 아니다 — cancelled와 다른 축(D-31)
    amount: 55000000,
    currentHistory: {
      version: 1,
      documentKind: "final",
      status: "applied",
      fileName: "CTR-107.pdf",
      filePath: null,
      fileHash: "sha256:demo-ctr107",
      mimeType: "application/pdf",
      parsedAt: daysFromNow(-1200),
      conflictReport: null,
      rawText: "제 1조 [당사자 정의] 갑 MINDEX Studios, 을 CyberNexus Studio ...",
    },
    rightsGrants: [
      // terminated 데모 — 실 스키마는 만료를 날짜 계산이 아니라 명시적 종료로도 기록한다.
      // "구 시즌" 타이틀에 맞춰 scopeType도 SEASON으로 좁혀서 보여준다.
      grant(10171, "TH", "BROADCAST", "TV_LINEAR", "non_exclusive", -1100, -40, "제5조 [TV 방영권]", {
        scopeType: "SEASON",
        status: "terminated",
        terminatedAt: daysFromNow(-40),
        terminatedReason: "expired",
        terminationNote: "이용기간 만료로 자동 종료.",
      }),
    ], // 기간만료
  },
  {
    id: 108,
    ipId: 3,
    title: "Fintrex OST Collection 신규 검토 건",
    grantor: "MINDEX Music",
    grantee: "Fintrex Inc.",
    signedDate: null,
    status: "draft",
    amount: null,
    currentHistory: null, // 아직 업로드된 세대(PDF)가 없다 — contract.currentHistoryId가 NULL인 경우
    rightsGrants: [], // 기간 정보 없음
  },
  {
    // 실제 PDF 2건(public/mock-pdfs/CTR-KO-9004.pdf, CTR-KO-0001.pdf) 기반 — react-pdf 미리보기 +
    // 버전 드롭다운 데모용. 두 PDF가 서로 다른 딜(당사자·IP·조건)이라, v2(최종)에 title/grantor/
    // grantee/rightsGrants를 따로 얹어서 드롭다운으로 전환하면 PDF뿐 아니라 상세 정보도 같이 바뀐다.
    // 최상위 title/grantor/grantee/rightsGrants는 "현재(최신 세대)"를 대표하므로 v2 값을 그대로 쓴다.
    id: 109,
    ipId: 4,
    title: "겨울의 신호 SVOD 스트리밍 라이선스 (KO-2025-001-002)",
    grantor: "루미나 픽처스 주식회사",
    grantee: "해솔미디어 주식회사",
    signedDate: "2025-08-05",
    status: "signed",
    amount: 688000, // v2 원문 "총 계약대가는 688,000.00 USD" 그대로 반영
    currency: "USD", // §1.4 — contract.currency 반영 전엔 ₩로 잘못 표시되던 문제 수정
    history: [
      {
        version: 1,
        documentKind: "draft",
        status: "applied",
        fileName: "CTR-KO-9004_v1_draft.pdf",
        filePath: "/mock-pdfs/CTR-KO-9004.pdf",
        fileHash: "sha256:demo-ctrko9004v1",
        mimeType: "application/pdf",
        parsedAt: "2026-07-05",
        conflictReport: null,
        title: "SPRING_MEMORIES SVOD 스트리밍 라이선스 (KO-2026-003-004) — 초안",
        grantor: "온웨이브 플랫폼 주식회사",
        grantee: "노을콘텐츠 유한회사",
        signedDate: null, // 협의 중 — 아직 체결 전
        rightsGrants: [],
        rawText:
          "저작재산권 이용허락 계약서 — 초안 (합성데이터 검토본 — 실제 계약으로 사용할 수 없음)\n\n" +
          "문서 참조번호: KO-2026-003-004 (v1 초안) · 초안 작성일: 2026년 7월 5일\n" +
          "허락자: 온웨이브 플랫폼 주식회사(대표 박지후) · 이용자: 노을콘텐츠 유한회사(대표 이하린)\n\n" +
          "[전문] 양 당사자는 콘텐츠의 이용허락 및 배급에 관한 조건을 협의 중이며, 이용기간·이용지역 등 " +
          "세부 조건은 최종 서명 전까지 변경될 수 있다.\n\n" +
          "제3조 (이용허락, 협의안) 허락자는 이용자에게 '별지에서 특정할 대상 콘텐츠'에 관한 전송권을 " +
          "구독형 주문형 영상(SVOD) 방식으로 비독점적으로 허락하는 안을 제시한다. 이용기간은 협의 중이다.",
      },
      {
        // 실제 PDF(public/mock-pdfs/CTR-KO-0001.pdf) 원문 그대로 — 사용자 제공 파일.
        version: 2,
        documentKind: "final",
        status: "applied",
        fileName: "CTR-KO-0001.pdf",
        filePath: "/mock-pdfs/CTR-KO-0001.pdf",
        fileHash: "sha256:demo-ctrko0001",
        mimeType: "application/pdf",
        parsedAt: "2025-08-05",
        conflictReport: null,
        title: "겨울의 신호 SVOD 스트리밍 라이선스 (KO-2025-001-002)",
        grantor: "루미나 픽처스 주식회사",
        grantee: "해솔미디어 주식회사",
        signedDate: "2025-08-05",
        rightsGrants: [
          (() => {
            const quote =
              "허락자는 이용자에게 '겨울의 신호'에 관한 전송권을 구독형 주문형 영상(SVOD) 방식으로 행사할 수 있도록 " +
              "독점적으로 허락한다. '겨울의 신호'의 구독형 주문형 영상(SVOD) 이용지역은 일본이고, 이용기간은 " +
              "2026년 1월 1일부터 2027년 12월 31일까지이며 양 끝 날짜를 포함한다.";
            const evidenceEntry = { clause: "제3조 [이용허락]", quote };
            return {
              id: 10192,
              territory: "JP",
              legalRight: "TRANSMISSION",
              exploitationMode: "SVOD",
              exclusivity: "exclusive",
              period: { start: "2026-01-01", end: "2027-12-31" },
              evidence: {
                legalRight: evidenceEntry,
                exploitationMode: evidenceEntry,
                territory: evidenceEntry,
                period: evidenceEntry,
                exclusivity: evidenceEntry,
              },
              scopeType: "SERIES_ALL",
              lineageId: 10192,
              status: "active",
              terminatedAt: null,
              terminatedReason: null,
              terminationNote: null,
              conditionsRaw: null,
            };
          })(),
        ],
        rawText:
          "『겨울의 신호』 저작재산권 이용허락 계약서 (합성데이터 검토본 — 실제 계약으로 사용할 수 없음)\n\n" +
          "문서 참조번호: KO-2025-001-002 · 계약 체결일: 2025년 8월 5일\n" +
          "허락자: 루미나 픽처스 주식회사(대표 한서진) · 이용자: 해솔미디어 주식회사(대표 김도윤)\n\n" +
          "[전문] 루미나 픽처스 주식회사(이하 '허락자')와 해솔미디어 주식회사(이하 '이용자')는 2025년 8월 5일 " +
          "콘텐츠의 이용허락 및 배급에 관한 조건을 명확히 하기 위하여 이 계약을 체결한다.\n\n" +
          "제3조 (이용허락) 구독형 주문형 영상(SVOD) 이용을 위한 본 개별 이용허락의 권리대상은 '겨울의 신호'로 " +
          "한정한다. 허락자는 이용자에게 '겨울의 신호'에 관한 전송권을 구독형 주문형 영상(SVOD) 방식으로 행사할 " +
          "수 있도록 독점적으로 허락한다. 이용지역은 일본이고, 이용기간은 2026년 1월 1일부터 2027년 12월 31일까지" +
          "이며 양 끝 날짜를 포함한다.\n\n" +
          "제7조 (계약대가 및 지급) 총 계약대가는 688,000.00 USD이며 지급통화도 USD로 한다.",
      },
      {
        // current_history_id 독립 FK 데모 — v2가 아직 active인 상태에서 겹치는 기간으로 연장을
        // 시도하다 충돌로 막힌 세대. 배열상 마지막이지만 conflicted라 "현재"가 되지 못하고,
        // v2가 계속 현재 세대로 남는다(아래 정규화 루프 참고).
        version: 3,
        documentKind: "final",
        status: "conflicted",
        fileName: "CTR-KO-0001_v3_renewal.pdf",
        filePath: null,
        fileHash: "sha256:demo-ctrko0001v3",
        mimeType: "application/pdf",
        parsedAt: "2026-08-20",
        title: "겨울의 신호 SVOD 스트리밍 라이선스 연장 (KO-2025-001-002-R1)",
        grantor: "루미나 픽처스 주식회사",
        grantee: "해솔미디어 주식회사",
        signedDate: null,
        rightsGrants: [],
        rawText:
          "『겨울의 신호』 저작재산권 이용허락 연장 계약서 (합성데이터 검토본 — 실제 계약으로 사용할 수 없음)\n\n" +
          "제2조 (연장) 허락자는 이용자에게 기존 이용허락 기간 만료 전 2027년 6월 1일부터 2029년 12월 31일까지 " +
          "동일한 조건으로 이용기간을 연장한다.",
        conflictReport: {
          batchResult: "CONFLICTED",
          constraintName: "no_exclusive_overlap",
          conflicts: [
            {
              incoming: {
                legalRight: "TRANSMISSION",
                exploitationMode: "SVOD",
                territory: "JP",
                period: "[2027-06-01,2029-12-31)",
                exclusivity: "exclusive",
              },
              existingGrantId: 10192,
              existingContractId: 109,
              overlapPeriod: "[2027-06-01,2027-12-31)",
              legalRightRelation: "same",
              exploitationModeRelation: "same",
              blockingLayer: "no_exclusive_overlap",
            },
          ],
        },
      },
    ],
    rightsGrants: [], // 아래 정규화 루프가 현재 세대(current)의 rightsGrants로 덮어씀
  },
  {
    // conflict_report(jsonb) 데모 — contract_history.status='conflicted'일 때만 채워지는
    // 실 컬럼을 실제로 보여주기 위한 케이스. 노을빛 소년단 KR·SVOD·독점 구간이 계약#101
    // (grant 10111)과 겹쳐서 막힌 시나리오 — save_rights_batch()의 no_exclusive_overlap
    // EXCLUDE 제약과 같은 모양의 리포트를 재현했다(실제 함수 출력 원문은 아님).
    id: 110,
    title: "노을빛 소년단 아시아 스트리밍 재라이선스 (충돌 사례)",
    grantor: "MINDEX Studios",
    grantee: "Vantage Stream Co., Ltd.",
    signedDate: null, // 충돌로 막혀 서명까지 못 감
    status: "draft",
    amount: null,
    history: [
      {
        version: 1,
        documentKind: "draft",
        status: "conflicted",
        fileName: "CTR-110_v1.pdf",
        filePath: null,
        fileHash: "sha256:demo-ctr110v1",
        mimeType: "application/pdf",
        parsedAt: daysFromNow(-5),
        rawText: "제 1조 [당사자 정의] 갑 MINDEX Studios, 을 Vantage Stream Co., Ltd. ...",
        // conflicted면 rights_grant가 실제로 생성되지 않는다 — 판정 결과만 남는다.
        rightsGrants: [],
        conflictReport: {
          batchResult: "CONFLICTED",
          constraintName: "no_exclusive_overlap",
          conflicts: [
            {
              incoming: {
                legalRight: "TRANSMISSION",
                exploitationMode: "SVOD",
                territory: "KR",
                period: "[2026-09-25,2029-04-19)",
                exclusivity: "exclusive",
              },
              existingGrantId: 10111,
              existingContractId: 101,
              overlapPeriod: "[2026-09-25,2029-04-19)",
              legalRightRelation: "same",
              exploitationModeRelation: "same",
              blockingLayer: "no_exclusive_overlap",
            },
          ],
        },
      },
    ],
    rightsGrants: [],
  },
];

// 대부분의 계약은 세대(history)가 1개뿐이라 위에서 currentHistory 하나만 적어뒀다 —
// 여기서 API 명세서 §8 GET /contracts/{id} 응답 shape인 histories[](historyId·isCurrent
// 포함)·currentVersion으로 통일한다. 109번처럼 여러 세대가 있는 계약은 위에서 이미
// history 배열로 직접 정의했으니 그대로 쓰고, 나머지는 currentHistory 하나를 배열로 감싼다.
// ContractDetailPage의 버전 드롭다운은 항상 contract.histories를 본다.
for (const c of MOCK_CONTRACTS) {
  const rawHistories = c.history ?? (c.currentHistory ? [c.currentHistory] : []);
  // contract.current_history_id는 배열 마지막이 아니라 "가장 최근에 성공적으로 applied된
  // 세대"를 가리키는 독립 FK다 — 최신 업로드가 conflicted면(계약#109 v3처럼) 그 이전 applied
  // 세대가 계속 현재로 남는다. applied가 하나도 없으면(계약#110처럼 첫 업로드부터 막힌 경우)
  // 보여줄 게 없으니 마지막 세대(대개 conflicted)로 대체한다.
  const latestApplied = [...rawHistories].reverse().find((h) => h.status === "applied");
  const current = latestApplied ?? rawHistories.at(-1) ?? null;
  c.histories = rawHistories.map((h, i) => ({ ...h, historyId: c.id * 10 + (i + 1), isCurrent: h === current }));
  delete c.history;
  delete c.currentHistory;
  c.currentVersion = current?.version ?? null;
  c.rightsGrants = current?.rightsGrants ?? c.rightsGrants ?? [];
  // 실 스키마엔 contract.updated_at이 있다 — 계약 자체 행이 마지막으로 바뀐 시각.
  // 새 세대(버전)가 current_history_id로 올라올 때가 이 값이 갱신되는 대표적인
  // 시점이라, 데모에서는 "최신 세대가 파싱된 시각"으로 근사한다.
  c.updatedAt = current?.parsedAt ?? c.signedDate ?? null;
  // 실 스키마엔 contract.currency(char4)도 있다 — §1.4, 명시 안 한 계약은 원화로 가정.
  c.currency = c.currency ?? "KRW";
  c.lang = c.lang ?? "ko";
}

function toListItem(c) {
  const primary = (c.rightsGrants ?? []).at(-1);
  const currentHistory = c.histories?.find((history) => history.isCurrent) ?? c.histories?.at(-1);
  const listRight = getListRight(c);
  const display = computeContractStatus({
    signedDate: c.signedDate,
    periodStart: listRight?.period?.start,
    periodEnd: listRight?.period?.end,
  });
  return {
    kind: "contract",
    contractId: c.id,
    ipId: c.ipId,
    ipTitle: c.ipTitle ?? c.title,
    serviceTitle: c.title,
    grantor: c.grantor,
    grantee: c.grantee,
    status: c.status,
    agreementDate: c.signedDate,
    displayState: display.key.toUpperCase(),
    displayStateLabel: display.label,
    daysToExpiry: display.daysToExpiry,
    territories: listRight?.territory ? [listRight.territory] : [],
    mainLegalRights: listRight?.legalRight ? [listRight.legalRight] : [],
    mainExploitationModes: listRight?.exploitationMode ? [listRight.exploitationMode] : [],
    period: listRight?.period ?? null,
    isExclusive: listRight ? listRight.exclusivity !== "non_exclusive" : false,
    hasConflict: currentHistory?.status === "conflicted" || Boolean(primary?.conflict),
    updatedAt: c.updatedAt,
  };
}

// 충돌로 rights_grant 저장이 거절된 계약도 목록에서 검증 대상을 확인할 수 있게 한다.
// 이 대체값은 확정 권리가 아니라 conflict_report에 남은 입력값이며, 충돌 배지로 구분한다.
function getListRight(contract) {
  const primary = (contract.rightsGrants ?? []).at(-1);
  if (primary) return primary;
  const currentHistory = contract.histories?.find((history) => history.isCurrent) ?? contract.histories?.at(-1);
  const incoming = currentHistory?.conflictReport?.conflicts?.[0]?.incoming;
  return incoming
    ? {
        legalRight: incoming.legalRight,
        exploitationMode: incoming.exploitationMode,
        territory: incoming.territory,
        period: parsePeriodRange(incoming.period),
        exclusivity: incoming.exclusivity,
      }
    : null;
}

function parsePeriodRange(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  const normalized = String(value).trim();
  const [start, end] = normalized.slice(1, -1).split(",");
  return start && end ? { start, end } : null;
}

// 명세서 #7의 서버 검색·필터·정렬·페이지네이션을 mock에서도 같은 방식으로 적용한다.
export function mockListContracts({ q, ipId, status, exclusiveOnly, territory, sort = "recent", page = 1, size = 20 } = {}) {
  const needle = (q ?? "").trim().toLowerCase();
  let items = MOCK_CONTRACTS.filter((c) => {
    if (ipId && String(c.ipId) !== String(ipId)) return false;
    if (needle) {
      const haystack = `${c.title} ${c.grantor ?? ""} ${c.grantee ?? ""}`.toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    if (status?.length && !status.includes(c.status)) return false;
    // 리스트 행은 대표 grant(배열 마지막 항목)만 보여주므로, 필터도 같은 grant 기준으로 맞춘다 —
    // 안 그러면 "독점 라이선스"로 걸러졌는데 화면엔 비독점 grant가 보이는 식으로 어긋난다.
    const listRight = getListRight(c);
    if (exclusiveOnly && (!listRight || listRight.exclusivity === "non_exclusive")) {
      return false;
    }
    if (territory && listRight?.territory !== territory) {
      return false;
    }
    return true;
  });
  items = [...items].sort((a, b) => {
    if (sort === "expiring") {
      const aEnd = a.rightsGrants?.at(-1)?.period?.end ?? "9999-12-31";
      const bEnd = b.rightsGrants?.at(-1)?.period?.end ?? "9999-12-31";
      return aEnd.localeCompare(bEnd);
    }
    return String(b.updatedAt ?? "").localeCompare(String(a.updatedAt ?? ""));
  });
  const total = items.length;
  const start = (page - 1) * size;
  items = items.slice(start, start + size).map(toListItem);
  return { items, total };
}

// 계약 종료 — API 명세서 #11 POST /contracts/{id}/cancel. 상태만 cancelled로 바꾸고 권리를
// 그대로 두면 EXCLUDE 인덱스에 남아 다른 계약을 계속 막으므로, 살아있는 권리를 전부
// terminated로 같이 내린다(명세서 "구현 시 주의" 그대로).
export function mockCancelContract(id, { reason, note }) {
  const contract = MOCK_CONTRACTS.find((c) => String(c.id) === String(id));
  // 상태 코드 표 — 404 대상 없음, 422 처리 가능하나 업무 규칙 위반(이미 취소된 계약을
  // 또 취소하는 건 요청 자체는 유효하지만 업무 규칙에 걸린다).
  if (!contract) throw new ApiError(404, `계약 #${id}을 찾을 수 없습니다 (데모 데이터).`);
  if (contract.status === "cancelled") throw new ApiError(422, { code: "ALREADY_CANCELLED", message: "이미 취소된 계약입니다 (데모 데이터)." });
  const terminatedAt = new Date().toISOString().slice(0, 10);
  let terminatedRights = 0;
  for (const grant of contract.rightsGrants ?? []) {
    if (grant.status === "active") {
      grant.status = "terminated";
      grant.terminatedAt = terminatedAt;
      grant.terminatedReason = reason;
      grant.terminationNote = note ?? null;
      terminatedRights += 1;
    }
  }
  contract.status = "cancelled";
  contract.updatedAt = terminatedAt;
  return { contractId: contract.id, status: "cancelled", terminatedRights, terminatedAt };
}

export function mockGetContract(id) {
  const contract = MOCK_CONTRACTS.find((c) => String(c.id) === String(id));
  if (!contract) throw new ApiError(404, `계약 #${id}을 찾을 수 없습니다 (데모 데이터).`);
  return contract;
}

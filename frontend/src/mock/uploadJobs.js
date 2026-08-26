import { MOCK_CONTRACT_INFO, MOCK_IP_CANDIDATES, MOCK_RAW_TEXT, MOCK_RIGHTS } from "./upload.js";
import { ApiError } from "../api/ApiError.js";

// 업로드 잡(tmpId 기준 OCR/추출 진행상태) mock. 다른 mock(ipDirectory.js, contracts.js)과
// 같은 방식으로 모듈 스코프 인메모리 저장소를 쓴다 — localStorage를 쓰지 않는다.
// api/client.js가 이 파일을 호출하며, 실 API가 붙으면 api/client.js 쪽 분기만 바뀌고
// 이 파일과 UploadPage.jsx 호출부는 그대로다.
//
// 인메모리라 진짜 새로고침(풀 리로드)에는 살아남지 못한다 — 실제로 진행상태가 새로고침에도
// 살아남으려면 그건 서버(DB)가 상태를 들고 있어야 가능한 일이고, 그게 진짜 API가 필요한
// 이유다. mock이 localStorage로 그걸 흉내내면 "클라이언트가 상태를 들고 있다"는 잘못된
// 모델을 코드에 남기게 된다 — 여기서는 그 흉내를 내지 않는다.
//
// 실 백엔드(k8s, GET /api/extract/{tmpid})는 QUEUED → RUNNING(stage=OCR) → RUNNING(stage=LLM)
// → DONE(json 포함) | FAILED(reason 포함) 순으로 상태가 바뀐다. mock은 같은 순서를
// QUEUED→OCR→LLM→(DONE|FAILED)로 시간에 따라 흉내내되, UI 쪽 stage 이름은 소문자
// (queued/ocr/llm/extract/failed)로 맞춰 반환한다 — api/client.js가 실 API 응답도 같은
// 이름으로 정규화하므로 UploadPage.jsx는 이 값만 보면 된다. DONE이 "extract"인 이유는
// 이 시점부터 화면이 "AI 추출 결과 검증" 단계로 넘어가기 때문이다.
const QUEUED_MS = 500;
const OCR_MS = 1100;
const LLM_MS = 1100;
// 실 API 응답에 대기 인원 필드가 아직 없다 — 데모용 고정값(P1/P2 확인 필요).
const DEMO_QUEUE_POSITION = 2;
const jobs = new Map();

// OCR·LLM 둘 다 실패 지점이 될 수 있어 mock에서도 파일명으로 두 실패 사유를 재현할 수
// 있게 해둔다(데모/테스트 목적) — 실 API는 워커가 판단한 사유를 그대로 내려준다.
function failReasonFor(fileName) {
  // macOS는 한글 파일명을 NFD(자모 분리형)로 넘겨줄 수 있어 NFC로 정규화 후 비교한다.
  const normalized = fileName.normalize("NFC");
  if (normalized.includes("읽기불가")) return "UNREADABLE_PDF";
  if (normalized.includes("재시도초과")) return "MAX_ATTEMPTS";
  if (normalized.includes("llm실패")) return "LLM_TIMEOUT";
  if (normalized.includes("실패")) return "OCR_TIMEOUT";
  return null;
}

export function mockStartUploadJob(fileName) {
  const id = `tmp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  jobs.set(id, { id, fileName, startedAt: Date.now(), failReason: failReasonFor(fileName) });
  return mockGetUploadJob(id);
}

export function mockGetUploadJob(tmpId) {
  const job = jobs.get(tmpId);
  if (!job) throw new ApiError(404, `업로드 잡 ${tmpId}을 찾을 수 없습니다 (데모 데이터).`);
  const base = { id: job.id, fileName: job.fileName };
  const elapsed = Date.now() - job.startedAt;
  const isOcrFail = job.failReason === "OCR_TIMEOUT" || job.failReason === "UNREADABLE_PDF";
  const isLlmFail = job.failReason === "LLM_TIMEOUT" || job.failReason === "MAX_ATTEMPTS";

  if (elapsed < QUEUED_MS) return { ...base, stage: "queued", queuePosition: DEMO_QUEUE_POSITION };
  if (elapsed < QUEUED_MS + OCR_MS) return { ...base, stage: "ocr" };
  if (isOcrFail) return { ...base, stage: "failed", reason: job.failReason };
  if (elapsed < QUEUED_MS + OCR_MS + LLM_MS) return { ...base, stage: "llm" };
  if (isLlmFail) return { ...base, stage: "failed", reason: job.failReason };
  // DONE result는 잡당 한 번만 복제해서 캐시한다. 같은 tmpId 재조회에는 같은 결과를 주되,
  // 다른 잡끼리 HITL 데이터 객체를 공유하지 않는다.
  if (!job.ipCandidates) job.ipCandidates = structuredClone(MOCK_IP_CANDIDATES);
  if (!job.result) {
    job.result = {
      contractInfo: structuredClone(MOCK_CONTRACT_INFO),
      rights: structuredClone(MOCK_RIGHTS),
      ipCandidates: job.ipCandidates,
      rawText: MOCK_RAW_TEXT,
      confidence: 0.96,
    };
  }
  return { ...base, stage: "extract", result: job.result, ...job.result };
}

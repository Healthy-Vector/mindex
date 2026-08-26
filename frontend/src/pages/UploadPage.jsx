import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client.js";
import { buildContractPayload, contractPayloadViolations } from "../lib/contractPayload.js";
import { normalizeIp } from "../lib/apiNormalizers.js";
import UploadVerificationView, { CheckingView, FailedView } from "../components/upload/UploadVerificationView.jsx";
import "../styles/upload-page.css";

// PDF 업로드 → OCR/AI 추출 → HITL(사람) 검증 → 충돌 검사. 충돌이 있을 때만 충돌 페이지로 이동한다.
// "완료"는 별도 트래커 단계가 아니라 충돌검사 이후 도달하는 종료 상태라 목록에서 뺐다 —
// stage==="done"일 때 activeIndex를 마지막 단계 다음으로 넘겨 전부 완료 표시되게 한다.
const PIPELINE_STEPS = ["업로드", "파싱/OCR", "AI 추출", "HITL 검증", "충돌 검사"];
// queued는 아직 "파싱/OCR" 단계에 들어가지도 못한 상태지만, 트래커에 전용 칸이 없어
// 같은 인덱스(1)에 "대기"로 얹는다 — 실제 진행 문구는 VerifyBody 쪽 큰 카드가 보여준다.
const STAGE_INDEX = { idle: 0, queued: 1, ocr: 1, llm: 2, extract: 3, checking: 4 };
// OCR/추출 진행 상태는 tmpId로 조회한다 — 폴링 주기.
const JOB_POLL_DELAYS = [2000, 4000, 8000, 16000, 30000];
const MAX_PDF_BYTES = 100 * 1024 * 1024;
// 폴링을 계속해야 하는(아직 안 끝난) 상태들.
const POLLING_STAGES = ["queued", "ocr", "llm"];

// 실 백엔드(k8s 폴링)는 OCR·LLM 추출 둘 다 실패 지점이 될 수 있다 — 실패한 사유에 따라
// 파이프라인의 어느 단계에서 멈췄는지도 다르다(OCR 단계 vs AI 추출 단계).
const FAILED_STEP_INDEX = { OCR_TIMEOUT: 1, UNREADABLE_PDF: 1, LLM_TIMEOUT: 2, MAX_ATTEMPTS: 2, UPLOAD_FAILED: 0 };
const ENTRY_CONTEXT = {
  new: {
    tag: "신규 등록",
    desc: "새 계약 그룹을 생성합니다. IP는 OCR 자동매칭 또는 신규 등록으로 결정하고, 초안으로 시작합니다.",
  },
  revision: {
    tag: "버전계약 등록",
    desc: "기존 계약 그룹·IP가 이미 확정되어 있습니다. 같은 그룹에 새 초안이 추가됩니다.",
  },
  final: {
    tag: "최종계약 등록",
    desc: "기존 계약 그룹·IP가 이미 확정되어 있습니다. 충돌이 없으면 최종 계약(서명 완료)으로 저장되고, 충돌이 있으면 등록되지 않고 충돌 내역만 기록됩니다.",
  },
};

function StepTracker({ activeIndex, failed }) {
  return (
    <div className="upload-steps">
      {PIPELINE_STEPS.map((label, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        const errored = active && failed;
        return (
          <div key={label} style={{ display: "contents" }}>
            {i > 0 && <div className={`upload-step-connector${i <= activeIndex ? " upload-step-connector--done" : ""}`} />}
            <div className={`upload-step${i > activeIndex ? " upload-step--pending" : ""}`}>
              <span className={`upload-step-badge${done || active ? " upload-step-badge--active" : ""}${errored ? " upload-step-badge--error" : ""}`}>
                {done ? "✓" : errored ? "✕" : i + 1}
              </span>
              <div>
                <div className="upload-step-label">{label}</div>
                <div className={`upload-step-status${active ? " upload-step-status--active" : ""}${errored ? " upload-step-status--error" : ""}`}>
                  {done ? "완료" : errored ? "실패" : active ? "진행 중" : "대기"}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function UploadPage() {
  const [searchParams] = useSearchParams();
  const { tmpId: pathTmpId } = useParams();
  const entryMode = ["new", "revision", "final"].includes(searchParams.get("mode")) ? searchParams.get("mode") : "new";
  const entryContractId = searchParams.get("contractId");
  const entryIpId = searchParams.get("ipId");
  const tmpId = pathTmpId;
  const [mode, setMode] = useState(entryMode);
  const [selectedContractId, setSelectedContractId] = useState(entryContractId);

  const [stage, setStage] = useState("idle"); // idle | queued | ocr | llm | extract | checking | failed
  const [fileName, setFileName] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [failReason, setFailReason] = useState(null); // HTML 명세의 extract_job 실패 사유 코드
  const [queuePosition, setQueuePosition] = useState(null); // queued 단계에서만 값이 있음
  const [ipMatch, setIpMatch] = useState(null); // { status: "auto" | "manual", ip }
  const [contractInfo, setContractInfo] = useState({});
  const [fileMeta, setFileMeta] = useState({});
  const [rights, setRights] = useState([]);
  const [validationErrors, setValidationErrors] = useState([]);
  const [pollError, setPollError] = useState(null);
  const [verifyError, setVerifyError] = useState(null);
  // API 명세서 #3 result.ipCandidates — OCR·LLM 추출과 같은 응답에 IP 매칭 후보가 이미
  // 실려온다. 추출 완료 후 별도 매칭 API를 다시 호출할 필요가 없다.
  const [ipCandidates, setIpCandidates] = useState([]);
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);
  const navigate = useNavigate();
  // 자동매칭은 문서당 한 번만 시도한다 — 이게 없으면 "다른 IP로 변경"으로 ipMatch를
  // null로 비우자마자 이 값이 다시 true라 매칭 이펙트가 즉시 재실행돼서 원래 자동
  // 매칭값으로 도로 튀어버린다(사용자가 목록을 볼 새도 없이).
  const autoMatchedRef = useRef(false);
  // 이탈 가드 history entry는 단계 진입당 한 번만 쌓는다 — stage가 바뀔 때마다(ocr→extract 등)
  // 매번 pushState하면 history가 계속 불어나 뒤로가기를 여러 번 눌러야 실제로 빠져나가진다.
  const guardPushedRef = useRef(false);
  // URL의 tmpId로 진행 중인 잡을 복원하는 건 마운트 시 1회면 된다 — 이후 searchParams가
  // 우리 스스로의 setSearchParams 호출로 바뀔 때마다 다시 복원 시도하면 안 된다.
  const resumedRef = useRef(false);
  const pollAttemptRef = useRef(0);

  useEffect(() => {
    if (validationErrors.length === 0) return undefined;
    const timer = window.setTimeout(() => setValidationErrors([]), 3500);
    return () => window.clearTimeout(timer);
  }, [validationErrors]);

  // revision/final 진입은 계약 상세에서 ipId를 이미 받는다. HITL에서 IP를 항상 명시하기
  // 위해 실제 IP 정보를 조회해 동일한 IP 패널 모델로 맞춘다. final은 화면에서 읽기 전용이다.
  useEffect(() => {
    if (!entryIpId) return;
    let cancelled = false;
    api.getIp(entryIpId).then((ip) => {
      if (!cancelled && ip) setIpMatch({ status: "context", ip });
    });
    return () => {
      cancelled = true;
    };
  }, [entryIpId]);

  function updateRight(index, patch) {
    setRights((prev) => prev.map((right, i) => (i === index ? { ...right, ...patch } : right)));
  }

  function setTmpId(nextId) {
    const query = searchParams.toString();
    navigate(`${nextId ? `/upload/${nextId}` : "/upload"}${query ? `?${query}` : ""}`, { replace: true });
  }

  // 최초 복원과 폴링 완료가 같은 job shape을 처리하므로 한곳에서 화면 상태로 반영한다.
  const applyJobState = useCallback((job) => {
    if (job.fileName) setFileName(job.fileName);
    setStage(job.stage);
    setQueuePosition(job.stage === "queued" ? job.queuePosition : null);
    if (job.stage === "failed") setFailReason(job.reason);
    if (job.stage !== "extract") return;
    setFileMeta(job.fileMeta ?? {});
    setContractInfo(job.contractInfo ?? {});
    setRights(job.rights ?? []);
    setIpCandidates(job.ipCandidates ?? []);
  }, []);

  // 탭을 닫았다 tmpId로 다시 들어오거나 새로고침해도, 서버가 지금 어디까지 처리했는지를
  // 마운트 시 한 번 조회해서 이어서 보여준다.
  // 새로고침에는 살아남지 못한다 — 이 부분은 실 API가 붙어야 완전해진다.
  useEffect(() => {
    if (resumedRef.current) return;
    resumedRef.current = true;
    if (!tmpId) return;
    api
      .getUploadJob(tmpId)
      .then(applyJobState)
      .catch(() => {
        // 잡을 찾을 수 없음(만료·존재하지 않음) — 처음부터 다시 시작.
        setTmpId(null);
      });
  }, [tmpId, applyJobState]);

  // QUEUED/OCR/LLM 동안은 tmpId로 잡 상태를 폴링해서 서버 쪽 진행 상황과 동기화한다.
  // FAILED도 이 폴링으로 감지한다 — OCR·LLM 추출 둘 다 실패 지점이 될 수 있다.
  useEffect(() => {
    if (!POLLING_STAGES.includes(stage) || !tmpId) return;
    let cancelled = false;
    let timer;
    function schedule() {
      const delay = JOB_POLL_DELAYS[Math.min(pollAttemptRef.current, JOB_POLL_DELAYS.length - 1)];
      timer = setTimeout(() => {
      api
        .getUploadJob(tmpId)
        .then((job) => {
          if (cancelled) return;
          setPollError(null);
          pollAttemptRef.current += 1;
          if (job.stage !== stage) pollAttemptRef.current = 0;
          applyJobState(job);
          if (POLLING_STAGES.includes(job.stage)) schedule();
        })
        .catch((err) => {
          if (cancelled) return;
          setPollError(err.message || "처리 상태를 확인하지 못했습니다. 자동으로 다시 시도합니다.");
          pollAttemptRef.current += 1;
          schedule();
        });
      }, delay);
    }
    schedule();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [stage, tmpId, applyJobState]);

  // 신규 등록일 때만, extract 단계 진입 시 딱 한 번 IP 후보 중 1순위를 자동 매칭한다.
  // 별도 API 호출이 필요 없다 — ipCandidates가 이미 점수순으로 추출 결과에 실려온다.
  useEffect(() => {
    // 계약 연장(mode=new + ipId 전달)처럼 IP가 이미 정해진 상태로 들어온 경우엔
    // OCR 후보로 덮어쓰지 않는다.
    if (stage !== "extract" || entryMode !== "new" || autoMatchedRef.current || ipMatch) return;
    if (ipCandidates.length === 0) return;
    autoMatchedRef.current = true;
    const top = [...ipCandidates].sort((a, b) => b.score - a.score)[0];
    setIpMatch({ status: "auto", ip: normalizeIp(top) });
  }, [stage, entryMode, ipCandidates]);

  // 충돌 검사 — API 명세서 #5 POST /contracts/verify를 호출해 결과를 들고 충돌 페이지로
  // 넘어간다. 충돌이 없다고 자동으로 저장해버리지 않는다 — 사람이 결과를 보고 직접
  // "저장" 버튼을 눌러야 실제로 저장된다(ConflictCheckPage의 저장 버튼이 그 확인 지점).
  useEffect(() => {
    if (stage !== "checking") return;
    let cancelled = false;
    const payload = buildContractPayload({ tmpId, mode, contractId: selectedContractId, ipId: ipMatch?.ip?.id, contractInfo, rights, fileMeta });
    setVerifyError(null);
    api
      .verifyContract(payload)
      .then((verifyResult) => {
        if (cancelled) return;
        navigate("/upload/conflict", {
          state: { payload, ip: mode === "new" ? ipMatch?.ip : undefined, verifyResult },
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setVerifyError(err.message || "충돌검사 요청에 실패했습니다.");
        setStage("extract");
      });
    return () => {
      cancelled = true;
    };
  }, [stage, mode, ipMatch, selectedContractId, tmpId, contractInfo, rights, fileMeta, navigate]);

  // 새로고침/탭닫기(beforeunload)는 브라우저 네이티브 확인창을, 뒤로가기(popstate)는
  // 눈에 잘 띄도록 앱 자체 커스텀 모달(showLeaveConfirm)을 띄운다.
  useEffect(() => {
    // failed는 실패로 끝난 시도라 잃을 작업이 없다 — idle과 같은 취급으로 가드를 걸지 않는다.
    if (stage === "idle" || stage === "failed") return;
    function handleBeforeUnload(e) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);

    if (!guardPushedRef.current) {
      guardPushedRef.current = true;
      window.history.pushState({ mxLeaveGuard: true }, "");
    }
    function handlePopState() {
      setShowLeaveConfirm(true);
    }
    window.addEventListener("popstate", handlePopState);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      window.removeEventListener("popstate", handlePopState);
    };
  }, [stage]);

  function stayOnPage() {
    window.history.pushState({ mxLeaveGuard: true }, "");
    setShowLeaveConfirm(false);
  }

  function confirmLeave() {
    setShowLeaveConfirm(false);
    navigate("/");
  }

  function handleFile(file) {
    if (!file) return;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      setFileError("PDF 파일만 업로드할 수 있습니다.");
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setFileError("PDF 파일은 최대 100MB까지 업로드할 수 있습니다.");
      return;
    }
    setFileError(null);
    setFileName(file.name);
    setFailReason(null);
    setPollError(null);
    setVerifyError(null);
    setStage("queued");
    api
      .startUploadJob(file, { mode: entryMode, contractId: entryContractId, ipId: entryIpId })
      .then((job) => setTmpId(job.id))
      .catch(() => {
        setFailReason("UPLOAD_FAILED");
        setStage("failed");
      });
  }

  function reset() {
    setTmpId(null);
    setStage("idle");
    setFileName(null);
    setFileError(null);
    setFailReason(null);
    setQueuePosition(null);
    setIpMatch(null);
    if (entryIpId) {
      api.getIp(entryIpId).then((ip) => {
        if (ip) setIpMatch({ status: "context", ip });
      });
    }
    setContractInfo({});
    setFileMeta({});
    setRights([]);
    setValidationErrors([]);
    setPollError(null);
    setVerifyError(null);
    setMode(entryMode);
    setSelectedContractId(entryContractId);
    autoMatchedRef.current = false;
    guardPushedRef.current = false;
    pollAttemptRef.current = 0;
  }

  const selectedIpId = ipMatch?.ip?.id;
  const selectedContentAssetIds = new Set((ipMatch?.ip?.assets ?? []).map((asset) => Number(asset.contentAssetId)));
  const payloadPreview = buildContractPayload({ tmpId, mode, contractId: selectedContractId, ipId: selectedIpId, contractInfo, rights, fileMeta });
  const validationContext = { contentAssetIds: selectedContentAssetIds };
  const canSubmit = stage === "extract";
  const ctx = ENTRY_CONTEXT[mode];

  return (
    <div>
      <h2 className="mx-heading-lg">지능형 파싱 및 분석 파이프라인</h2>
      <div className="upload-context-banner">
        <span className="mx-tag mx-tag-accent">{ctx.tag}</span>
        <span className="mx-text-sm">{ctx.desc}</span>
        {(selectedContractId || selectedIpId) && (
          <span className="mx-text-xs mx-muted">
            {selectedContractId && `계약 #${selectedContractId}`}
            {selectedContractId && selectedIpId && " · "}
            {selectedIpId && `IP #${selectedIpId}`}
          </span>
        )}
      </div>

      <StepTracker
        activeIndex={stage === "failed" ? FAILED_STEP_INDEX[failReason] ?? 1 : STAGE_INDEX[stage]}
        failed={stage === "failed"}
      />

      {stage === "checking" && <CheckingView />}
      {stage === "failed" && (
        <FailedView fileName={fileName} reason={failReason} onRetry={reset} onCancel={() => navigate("/")} />
      )}
      {(stage === "idle" || stage === "queued" || stage === "ocr" || stage === "llm" || stage === "extract") && (
        <UploadVerificationView
          mode={mode}
          entryMode={entryMode}
          selectedContractId={selectedContractId}
          onModeChange={(nextMode) => {
            if (entryMode === "final") return;
            setMode(nextMode);
            if (nextMode === "new") setSelectedContractId(null);
          }}
          onContractChange={setSelectedContractId}
          stage={stage}
          fileName={fileName}
          queuePosition={queuePosition}
          fileError={fileError}
          contractInfo={contractInfo}
          setContractInfo={setContractInfo}
          rights={rights}
          onUpdateRight={updateRight}
          ipMatch={ipMatch}
          setIpMatch={(nextMatch) => {
            const changedIp = nextMatch?.ip?.id !== ipMatch?.ip?.id;
            setIpMatch(nextMatch);
            if (changedIp) setRights((prev) => prev.map((right) => ({ ...right, contentAssetId: null })));
            if (mode === "revision") setSelectedContractId(null);
          }}
          canSubmit={canSubmit}
          onFile={handleFile}
          onReset={reset}
          validationErrors={validationErrors}
          pollError={pollError}
          verifyError={verifyError}
          onSubmit={() => {
            const errors = contractPayloadViolations(payloadPreview, validationContext);
            setValidationErrors(errors);
            if (errors.length === 0) setStage("checking");
          }}
          onCancel={() => navigate("/")}
        />
      )}

      {showLeaveConfirm && (
        <div className="detail-pin-wrap detail-extend-overlay">
          <div className="mx-card mx-card-pad detail-pin-modal">
            <h4 className="mx-heading-card">이 페이지를 벗어나시겠습니까?</h4>
            <p className="mx-text-sm mx-muted">등록 중인 내용이 저장되지 않습니다.</p>
            <div className="detail-pin-actions">
              <button type="button" className="mx-btn mx-btn-secondary" onClick={stayOnPage}>
                취소
              </button>
              <button type="button" className="mx-btn mx-btn-primary" onClick={confirmLeave}>
                나가기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { useRef, useState } from "react";
import { HitlReviewEditor, RegistrationContextEditor } from "./HitlEditors.jsx";

const FAIL_REASON_LABEL = {
  UPLOAD_FAILED: "PDF 업로드 요청에 실패했습니다.",
  OCR_TIMEOUT: "OCR 처리 시간이 초과되었습니다.",
  LLM_TIMEOUT: "AI 추출 처리 시간이 초과되었습니다.",
  UNREADABLE_PDF: "PDF에서 읽을 수 있는 텍스트를 찾지 못했습니다.",
  MAX_ATTEMPTS: "최대 재시도 횟수를 초과했습니다.",
};

export default function UploadVerificationView({ mode, entryMode, selectedContractId, onModeChange, onContractChange, stage, fileName, queuePosition, fileError, contractInfo, setContractInfo, rights, onUpdateRight, ipMatch, setIpMatch, canSubmit, validationErrors, pollError, verifyError, onFile, onReset, onSubmit, onCancel }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [filePanelOpen, setFilePanelOpen] = useState(false);
  const idle = stage === "idle";
  function onDrop(event) {
    event.preventDefault();
    setDragging(false);
    if (idle) onFile(event.dataTransfer.files?.[0]);
  }
  return (
    <>
      {pollError && <div className="mx-alert-banner mx-mb-20">{pollError}</div>}
      {verifyError && <div className="mx-alert-banner mx-mb-20">충돌검사 실패: {verifyError} 입력값을 확인한 뒤 다시 시도하세요.</div>}
      {!idle && <button type="button" className="mx-link-btn mx-collapse-toggle upload-panel-toggle" onClick={() => setFilePanelOpen((value) => !value)}>{filePanelOpen ? "파일 정보 접기" : "파일 정보 펼치기"}</button>}
      <div className="upload-grid">
        <div className={`mx-card upload-dropzone${dragging ? " upload-dropzone--dragging" : ""}${idle ? " upload-dropzone--clickable" : ""}${idle || filePanelOpen ? "" : " upload-dropzone--collapsed"}`} onClick={() => { if (idle) inputRef.current?.click(); }} onDragOver={(event) => { event.preventDefault(); if (idle) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
          <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => onFile(event.target.files?.[0])} />
          {stage === "idle" && <><div className="upload-dropzone-icon">↑</div><div className="upload-dropzone-title">PDF 파일을 이 영역에 끌어다 놓으세요</div><div className="upload-dropzone-sub">또는 클릭해서 컴퓨터에서 파일 선택</div><span className="mx-tag mx-tag-outline">지원 형식: PDF 전용 (최대 100MB)</span>{fileError && <div className="upload-file-error">{fileError}</div>}</>}
          {stage === "queued" && <><div className="upload-spinner" /><div className="upload-dropzone-title">{fileName}</div><div className="upload-dropzone-sub">대기 중{queuePosition != null ? ` (앞에 ${queuePosition}건)` : ""}</div></>}
          {stage === "ocr" && <><div className="upload-spinner" /><div className="upload-dropzone-title">{fileName}</div><div className="upload-dropzone-sub">파싱 중…</div></>}
          {stage === "llm" && <><div className="upload-spinner" /><div className="upload-dropzone-title">{fileName}</div><div className="upload-dropzone-sub">추출 중…</div></>}
          {stage === "extract" && <><div className="upload-dropzone-icon upload-dropzone-icon--done">✓</div><div className="upload-dropzone-title">{fileName}</div><div className="upload-dropzone-sub">파싱 완료 · 아래에서 AI 추출 결과를 확인하세요</div><button type="button" className="mx-link-btn upload-replace-file-btn" onClick={(event) => { event.stopPropagation(); setConfirmReplace(true); }}>다른 파일 업로드</button></>}
        </div>
        <div className={stage === "extract" ? "upload-result-column" : "mx-card mx-card-pad"}>
          {stage !== "extract" ? <><div className="upload-panel-header"><h4 className="mx-heading-card" style={{ margin: 0 }}>AI 추출 결과 검증</h4></div><p className="mx-empty-state">{["queued", "ocr", "llm"].includes(stage) ? "처리가 끝나면 여기에 AI 추출 결과가 표시됩니다." : "왼쪽에 PDF를 업로드하면 AI 추출 결과가 여기에 표시됩니다."}</p></> : (
            <>
              <div className="mx-card mx-card-pad upload-review-intro">
                <div className="upload-panel-header"><h4 className="mx-heading-card" style={{ margin: 0 }}>AI 추출 결과 검증</h4></div>
                <div className="upload-panel-desc">OCR 파싱을 거쳐 분석된 계약 정보와 권리 조건입니다. 각 값과 근거 원문을 직접 수정할 수 있습니다.</div>
              </div>
              <RegistrationContextEditor mode={mode} entryMode={entryMode} ipMatch={ipMatch} selectedContractId={selectedContractId} onModeChange={onModeChange} onContractChange={onContractChange} />
              <HitlReviewEditor contractInfo={contractInfo} setContractInfo={setContractInfo} rights={rights} onUpdateRight={onUpdateRight} ipMatch={ipMatch} setIpMatch={setIpMatch} ipLocked={entryMode === "final"} />
            </>
          )}
        </div>
      </div>
      <div className="upload-actions"><button className="mx-btn mx-btn-secondary" onClick={onCancel}>취소 및 목록으로</button><button className="mx-btn mx-btn-primary" disabled={!canSubmit} onClick={onSubmit}>충돌검사 실행</button></div>
      {validationErrors.length > 0 && <div className="mx-alert-banner">{validationErrors.map((error) => <div key={error}>{error}</div>)}</div>}
      {confirmReplace && <div className="detail-pin-wrap detail-extend-overlay"><div className="mx-card mx-card-pad detail-pin-modal"><h4 className="mx-heading-card">다른 파일을 업로드하시겠습니까?</h4><p className="mx-text-sm mx-muted">지금까지 확인·수정한 AI 추출 결과와 IP 매칭이 모두 사라집니다.</p><div className="detail-pin-actions"><button type="button" className="mx-btn mx-btn-secondary" onClick={() => setConfirmReplace(false)}>취소</button><button type="button" className="mx-btn mx-btn-primary" onClick={() => { setConfirmReplace(false); onReset(); }}>네, 다른 파일 선택</button></div></div></div>}
    </>
  );
}

export function CheckingView() {
  return <div className="mx-card mx-card-pad upload-checking"><div className="upload-spinner" /><div className="upload-dropzone-title">기존 계약과의 충돌 여부를 확인하는 중입니다…</div><div className="upload-dropzone-sub">동일 IP + 기간 + 국가 + 권리가 전부 겹치는 기존 계약이 있는지 검사합니다.</div></div>;
}

export function FailedView({ fileName, reason, onRetry, onCancel }) {
  return <><div className="mx-alert-banner upload-failed-banner"><b>{fileName}</b> — {FAIL_REASON_LABEL[reason] ?? "처리 중 알 수 없는 오류가 발생했습니다."}</div><div className="mx-card mx-card-pad"><div className="mx-text-sm mx-muted">업로드는 다시 시도할 수 있습니다. 문제가 반복되면 원본 PDF의 스캔 품질(해상도·기울기)을 확인하거나 관리자에게 문의하세요.</div><div className="mx-text-xxs mx-muted upload-failed-code">사유 코드: {reason ?? "UNKNOWN"}</div></div><div className="upload-actions"><button type="button" className="mx-btn mx-btn-secondary" onClick={onCancel}>취소 및 목록으로</button><button type="button" className="mx-btn mx-btn-primary" onClick={onRetry}>다시 시도</button></div></>;
}

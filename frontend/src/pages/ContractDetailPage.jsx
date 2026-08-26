import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import ContractDetailContent from "../components/contract/ContractDetailContent.jsx";
import { setSecuritySessionLabel } from "../lib/securitySession.js";
import {
  clearPinSession,
  getPinSessionExpiresAt,
  hasActivePinSession,
  setPinSessionExpiresAt,
  setPinSessionToken,
  subscribePinSessionExpiresAt,
} from "../lib/pinSession.js";
import "../styles/contract-detail-page.css";

const SESSION_MS = 15 * 60 * 1000;

export default function ContractDetailPage() {
  const { id } = useParams();
  return <PinGate id={id} />;
}

function PinGate({ id }) {
  const [pinUnlocked, setPinUnlocked] = useState(hasActivePinSession);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState(false);
  const [pinSubmitting, setPinSubmitting] = useState(false);
  const [contract, setContract] = useState(null);
  const [error, setError] = useState(null);
  const [expiresAt, setExpiresAt] = useState(getPinSessionExpiresAt);
  const [now, setNow] = useState(Date.now());

  useEffect(() => subscribePinSessionExpiresAt(setExpiresAt), []);

  useEffect(() => {
    if (!pinUnlocked || contract) return;
    setError(null);
    let cancelled = false;
    api.getContract(id)
      .then((value) => { if (!cancelled) setContract(value); })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [id, pinUnlocked, contract]);

  useEffect(() => {
    if (!pinUnlocked) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [pinUnlocked]);

  useEffect(() => {
    if (!pinUnlocked) return;
    if (!expiresAt) {
      setPinUnlocked(false);
      setContract(null);
      return;
    }
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) {
      setPinUnlocked(false);
      setContract(null);
      clearPinSession();
      return;
    }
    const timer = setTimeout(() => {
      setPinUnlocked(false);
      setContract(null);
      setPinInput("");
      clearPinSession();
    }, remaining);
    return () => clearTimeout(timer);
  }, [pinUnlocked, expiresAt]);

  const remainingMs = pinUnlocked && expiresAt ? Math.max(0, expiresAt - now) : 0;
  const remainingLabel = formatDuration(remainingMs);

  // 상단 네비 배지는 이 페이지의 PIN 세션 상태를 그대로 반영 — 잠기거나 페이지를 벗어나면 지운다.
  useEffect(() => {
    setSecuritySessionLabel(pinUnlocked ? remainingLabel : null);
    return () => setSecuritySessionLabel(null);
  }, [pinUnlocked, remainingLabel]);

  function handlePinSubmit(e) {
    e.preventDefault();
    setPinSubmitting(true);
    api
      .verifyPin(pinInput)
      .then((session) => {
        setPinError(false);
        setPinSessionToken(session?.sessionToken ?? null);
        setPinSessionExpiresAt(session?.expiresAt ?? Date.now() + (session?.ttlSeconds ?? SESSION_MS / 1000) * 1000);
        setPinUnlocked(true);
      })
      .catch(() => setPinError(true))
      .finally(() => setPinSubmitting(false));
  }

  if (!pinUnlocked) {
    return (
      <div className="detail-pin-wrap">
        <form className="mx-card mx-card-pad detail-pin-modal" onSubmit={handlePinSubmit}>
          <h4 className="mx-heading-card">보안 PIN 인증</h4>
          <p className="mx-text-sm mx-muted">
            계약 상세 정보(당사자·금액·원문)는 팀 PIN을 입력해야 볼 수 있습니다.
          </p>
          <input
            className="mx-input detail-pin-input"
            type="password"
            inputMode="numeric"
            maxLength={4}
            autoFocus
            value={pinInput}
            onChange={(e) => {
              setPinInput(e.target.value.replace(/\D/g, "").slice(0, 4));
              setPinError(false);
            }}
            placeholder="••••"
          />
          {pinError && <div className="mx-text-xs" style={{ color: "var(--mx-alert-text)" }}>PIN이 일치하지 않습니다.</div>}
          <div className="detail-pin-actions">
            <Link to="/" className="mx-btn mx-btn-secondary">목록으로 돌아가기</Link>
            <button type="submit" className="mx-btn mx-btn-primary" disabled={pinInput.length !== 4 || pinSubmitting}>
              {pinSubmitting ? "확인 중…" : "인증"}
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (error) return <div className="mx-alert-banner">API 연결 실패: {error}</div>;
  if (!contract) return <p>불러오는 중…</p>;

  return <ContractDetailContent contract={contract} onContractUpdate={setContract} />;
}

function formatDuration(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSec / 60);
  const seconds = totalSec % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

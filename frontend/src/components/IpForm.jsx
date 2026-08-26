import { useState } from "react";
import CustomSelect from "./CustomSelect.jsx";
import { LANG_OPTIONS } from "../labels.js";
import { useRefs } from "../lib/useRefs.js";
import "../styles/ip-form.css";

// IP 등록/수정 폼. IP 관리 화면과 업로드 화면의 신규 IP 등록이 공유한다.
export const REQUIRED_LANGS = ["ko", "en", "ja"];

// aliasType은 실 스키마에 고정 값 목록이 없는 자유 텍스트라, 미리 "정식명"으로 채워두면
// 마치 고정 라벨처럼 보여 혼동을 준다 — 빈 값 + 예시 placeholder로 대체.
function emptyAliasRow(lang) {
  return { lang, aliasType: "", text: "" };
}

export function emptyIpForm(prefillTitle = "") {
  return { title: prefillTitle, kind: "", aliases: REQUIRED_LANGS.map(emptyAliasRow), assets: [] };
}

export function ipFormFromIp(ip) {
  return { title: ip.title, kind: ip.kind, aliases: ip.aliases.map((a) => ({ ...a })), activity: ip.activity };
}

function emptyAssetRow() {
  return { scopeType: "", title: "" };
}

// mode="create"일 때만 assets 입력을 보여준다 — API 명세서 #13(등록)이 배열 통째로
// 받는 유일한 엔드포인트이기 때문이다. #14(PATCH /ips/{id})엔 여전히 이 필드가 없고,
// 이 폼이 그대로 수정 모드에서 보이면 빈 배열로 저장해 기존 assets를 지우는 사고가 난다.
//
// 수정 경로는 #18(POST/PATCH/DELETE /ips/{id}/assets)로 열려 있다(client.js의
// createIpAsset/updateIpAsset/deleteIpAsset). 다만 #18은 배열 교체가 아니라 행 단위라
// "저장" 한 번에 폼 전체를 PATCH하는 지금의 흐름과 맞지 않는다 — 추가/수정/삭제를 행마다
// 별도 호출로 쪼개고, 권리가 걸린 행(409 ASSET_IN_USE)과 마지막 한 행을 읽기 전용으로
// 표시하는 폼 재설계가 필요하다. 그 작업 전까지는 편집 경로에서 계속 숨겨둔다.
export default function IpForm({ heading, initial, onSave, onCancel, mode = "create" }) {
  const { ipKindOptions, scopeTypeOptions } = useRefs();
  const [title, setTitle] = useState(initial.title);
  const [kind, setKind] = useState(initial.kind);
  const [aliases, setAliases] = useState(initial.aliases);
  const [assets, setAssets] = useState(initial.assets ?? []);
  // 활성 상태는 수정 화면에서만 다룬다 — 새 IP는 항상 active로 생성되고(명세서 #13),
  // 즉시 반영 토글 대신 "저장" 버튼을 누를 때 나머지 수정 내용과 한 번에 PATCH된다.
  const [activity, setActivity] = useState(initial.activity ?? "active");

  const canSave = Boolean(title.trim() && kind);

  function updateAlias(idx, patch) {
    setAliases((prev) => prev.map((a, i) => (i === idx ? { ...a, ...patch } : a)));
  }
  function addAlias() {
    setAliases((prev) => [...prev, emptyAliasRow("ko")]);
  }
  function removeAlias(idx) {
    setAliases((prev) => prev.filter((_, i) => i !== idx));
  }

  function updateAsset(idx, patch) {
    setAssets((prev) => prev.map((a, i) => (i === idx ? { ...a, ...patch } : a)));
  }
  function addAsset() {
    setAssets((prev) => [...prev, emptyAssetRow()]);
  }
  function removeAsset(idx) {
    setAssets((prev) => prev.filter((_, i) => i !== idx));
  }

  return (
    <div className="mx-card mx-card-pad ipform">
      {heading && <h5 className="mx-heading-panel">{heading}</h5>}
      <section className="ipform-section">
        <h6 className="ipform-section-title">기본 정보</h6>
        <div className="ipform-field">
          <label className="ipform-field-label">
            타이틀<span className="ipform-required-mark">*</span>
          </label>
          <input className="mx-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: Fintrex App Suite v3" />
        </div>
        <div className="ipform-field">
          <label className="ipform-field-label">
            유형<span className="ipform-required-mark">*</span>
          </label>
          <CustomSelect ariaLabel="유형" value={kind} onChange={setKind} options={ipKindOptions} />
        </div>
        {mode === "edit" && (
          <div className="ipform-field">
            <label className="ipform-field-label">활성 상태</label>
            <label className="ipmgmt-inactive-toggle">
              <button
                type="button"
                className="mx-switch"
                data-on={activity === "active"}
                role="switch"
                aria-checked={activity === "active"}
                onClick={() => setActivity((v) => (v === "active" ? "deactive" : "active"))}
              >
                <span className="mx-switch-thumb" />
              </button>
              {activity === "active" ? "활성화" : "비활성화"}
            </label>
          </div>
        )}
      </section>

      <section className="ipform-section ipform-section--divider">
        <div className="mx-flex-between">
          <h6 className="ipform-section-title">별칭</h6>
          <button type="button" className="mx-link-btn ipform-add-alias" onClick={addAlias}>
            + 별칭 추가
          </button>
        </div>
        <div className="ipform-alias-list">
          {aliases.map((a, i) => (
            <div key={i} className="ipform-alias-row">
              <div className="ipform-alias-lang">
                <CustomSelect ariaLabel="언어" value={a.lang} onChange={(v) => updateAlias(i, { lang: v })} options={LANG_OPTIONS} />
              </div>
              <div className="ipform-alias-type">
                <input
                  className="mx-input ipform-alias-type-input"
                  value={a.aliasType}
                  onChange={(e) => updateAlias(i, { aliasType: e.target.value })}
                  placeholder="정식명/약칭"
                  aria-label="별칭 유형"
                />
              </div>
              <input
                className="mx-input ipform-alias-text-input"
                value={a.text}
                onChange={(e) => updateAlias(i, { text: e.target.value })}
                placeholder="별칭 텍스트"
                aria-label="별칭 텍스트"
              />
              <button type="button" className="ipform-remove-alias" onClick={() => removeAlias(i)} aria-label="별칭 삭제">
                ×
              </button>
            </div>
          ))}
        </div>
      </section>

      {mode === "create" && (
        <section className="ipform-section ipform-section--divider">
          <div className="mx-flex-between">
            <h6 className="ipform-section-title">권리 대상 (선택)</h6>
            <button type="button" className="mx-link-btn ipform-add-alias" onClick={addAsset}>
              + 권리 대상 추가
            </button>
          </div>
          <p className="mx-text-xs mx-muted" style={{ marginTop: 0, marginBottom: 10 }}>
            생략하면 "시리즈 전체" 하나만 자동 생성됩니다. 시즌·에피소드 단위로 미리 나눠두려면 여기서 추가하세요.
          </p>
          <div className="ipform-alias-list">
            {assets.map((a, i) => (
              <div key={i} className="ipform-alias-row">
                <div className="ipform-alias-lang">
                  <CustomSelect ariaLabel="범위" value={a.scopeType} onChange={(v) => updateAsset(i, { scopeType: v })} options={scopeTypeOptions} />
                </div>
                <input
                  className="mx-input ipform-alias-text-input"
                  value={a.title}
                  onChange={(e) => updateAsset(i, { title: e.target.value })}
                  placeholder="예: 시즌 1 (생략 시 IP 타이틀 사용)"
                  aria-label="권리 대상 타이틀"
                />
                <button type="button" className="ipform-remove-alias" onClick={() => removeAsset(i)} aria-label="권리 대상 삭제">
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="ipform-actions">
        <button type="button" className="mx-btn mx-btn-secondary" onClick={onCancel}>
          취소
        </button>
        <button
          type="button"
          className="mx-btn mx-btn-primary"
          disabled={!canSave}
          onClick={() =>
            onSave({
              title: title.trim(),
              kind: kind.trim(),
              aliases: aliases.filter((a) => a.text.trim()),
              ...(mode === "create" ? { assets: assets.filter((a) => a.scopeType) } : {}),
              ...(mode === "edit" ? { activity } : {}),
            })
          }
        >
          저장
        </button>
      </div>
    </div>
  );
}

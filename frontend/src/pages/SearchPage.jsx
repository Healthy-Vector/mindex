import { useState } from "react";
import { Link } from "react-router-dom";
import { api, USE_MOCK } from "../api/client.js";
import { mockSearchResponse, mockMcpTranscript } from "../mock/search.js";
import { LANG_LABEL, EXCLUSIVITY_LABEL } from "../labels.js";
import { useRefs } from "../lib/useRefs.js";
import "../styles/search-page.css";

// 통합검색 — 자연어 검색과 교차언어 검색을 화면상 한 모드로 통합했다(Notion "통합검색
// 백엔드 개발 가이드" §0). 원문 언어가 한국어가 아닌 결과에는 카드별로 "교차언어 매칭"
// 배지만 붙이고, 질의는 항상 같은 입력창·같은 엔드포인트(POST /search)로 보낸다.
//
// mock/real 분기는 api.search() 안(USE_MOCK)에서만 결정한다 — 예전엔 여기서 실 API
// 호출이 실패하면 조용히 mock으로 폴백했는데, 그러면 prod에서 진짜 장애가 나도 화면은
// 데모 데이터를 보여주며 정상인 척하게 된다. 이제 dev(mock)는 mock만, prod(실 API)는
// 실패하면 실패를 그대로 보여준다.
const DEFAULT_QUERY = "동남아시아 지역 내에서 독점적으로 모바일 게임 배포 권리를 허용하는 2024년 이후 체결된 모든 계약을 보여줘";

export default function SearchPage() {
  const { territoryLabel } = useRefs();
  const [query, setQuery] = useState(DEFAULT_QUERY);
  // 목업(mindex-ui-mockup)은 정적 화면이라 진입 즉시 예시 질의·결과가 채워져 있다 —
  // mock 모드에서만 진입 시 데모 결과를 바로 보여준다. 실 API 모드는 검색을 실행하기
  // 전까지 빈 화면이다(데모 데이터를 실제 결과인 것처럼 보여주면 안 되니까).
  const [searchResult, setSearchResult] = useState(() => (USE_MOCK ? { query: DEFAULT_QUERY, ...mockSearchResponse } : null));
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [pipelineOpen, setPipelineOpen] = useState(false);

  async function handleSearch(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setSearchError(null);
    try {
      const data = await api.search(query);
      setSearchResult(data);
    } catch (err) {
      setSearchResult(null);
      setSearchError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const results = searchResult?.results ?? [];

  return (
    <div>
      <div className="mx-page-header">
        <div>
          <h2 className="mx-heading-lg">지능형 권리 조건 통합 검색</h2>
          <div className="mx-text-sm mx-muted">
            복잡한 SQL 구문이나 계약서 고유 ID 없이 대화형 언어로 조항 및 제약사항을 실시간 탐색합니다. 원문 언어가 달라도 한국어 질의로 함께 찾습니다.
          </div>
        </div>
      </div>

      <form onSubmit={handleSearch} className="mx-card search-form">
        <div className="search-form-row">
          <input
            className="mx-input"
            style={{ flex: 1 }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="예: 동남아시아 지역 내에서 독점적으로 모바일 게임 배포 권리를 허용하는 계약을 보여줘"
          />
          <button className="mx-btn mx-btn-primary" style={{ flex: "none" }} type="submit" disabled={loading}>
            {loading ? "검색 중…" : "질의 분석 실행"}
          </button>
        </div>
        <div className="search-pipeline">
          <button type="button" className="mx-link-btn mx-collapse-toggle" onClick={() => setPipelineOpen((v) => !v)}>
            AI 분석 흐름 {pipelineOpen ? "숨기기" : "보기"}
          </button>
          {pipelineOpen && (
            <>
              <span className="mx-tag mx-tag-outline">1단계: SQL 파라미터 필터링</span>
              <span style={{ opacity: 0.4 }}>→</span>
              <span className="mx-tag mx-tag-outline">2단계: 벡터 코사인 유사도 랭킹</span>
              {results.length > 0 && (
                <>
                  <span style={{ opacity: 0.4 }}>→</span>
                  <span className="search-pipeline-final">최종 결과 맵핑 완료</span>
                </>
              )}
              {searchResult?.avgConfidence != null && (
                <span className="search-pipeline-muted">| 평균 신뢰도 {(searchResult.avgConfidence * 100).toFixed(1)}%</span>
              )}
            </>
          )}
        </div>
      </form>

      {searchError && <div className="mx-alert-banner mx-mb-20">검색 실패: {searchError}</div>}

      {/* 명세서 #15 "구현 시 주의" — interpreted를 그대로 보여주는 이유는 사용자가 "시스템이
          내 질문을 이렇게 이해했다"를 확인하고 필요하면 다시 질의를 고칠 수 있어야 하기
          때문이다. 모드 통합 전엔 이 카드가 모드별로 따로 있었는데, 통합하면서 하나로
          합쳤다. */}
      {searchResult?.interpreted && <InterpretedConditions interpreted={searchResult.interpreted} territoryLabel={territoryLabel} />}

      {results.length > 0 && (
        <div className={`search-results-grid${USE_MOCK ? "" : " search-results-grid--single"}`}>
          <div>
            <div className="search-results-header">
              <h4 className="search-results-title">검색 결과 (매칭 {results.length}건)</h4>
            </div>

            <div className="result-list">
              {results.map((r) => {
                const crossLingual = r.sourceLang && r.sourceLang !== "ko";
                const snippet = r.snippets?.[0];
                return (
                  <div key={r.contractId} className="mx-card mx-card-pad">
                    <div className="result-card-header">
                      <div className="result-card-title-row">
                        <Link to={`/contracts/${r.contractId}`} className="result-card-title">
                          {r.title ?? `계약 #${r.contractId}`}
                        </Link>
                        {crossLingual && (
                          <span className="mx-tag mx-tag-outline" title={`원문 언어: ${LANG_LABEL[r.sourceLang] ?? r.sourceLang} — 벡터 유사도로 찾은 결과입니다`}>
                            교차언어 매칭 ({r.sourceLang.toUpperCase()})
                          </span>
                        )}
                      </div>
                      {r.similarity != null && <span className="result-card-score">유사도 {(r.similarity * 100).toFixed(1)}%</span>}
                    </div>
                    {(r.grantor || r.grantee) && (
                      <div className="result-card-meta">
                        계약 당사자: {r.grantor ?? "—"} / {r.grantee ?? "—"}
                      </div>
                    )}
                    {r.matchedFilters?.length > 0 && (
                      <div className="result-card-matched-fields">
                        <span className="mx-text-xxs mx-muted">구조화 매칭 근거</span>
                        {r.matchedFilters.map((filter, index) => {
                          const label = typeof filter === "string" ? filter : `${filter.label}=${filter.value}`;
                          return (
                            <span key={typeof filter === "string" ? `${filter}-${index}` : (filter.key ?? index)} className="mx-tag mx-tag-outline">
                              {label}
                            </span>
                          );
                        })}
                      </div>
                    )}
                    {snippet && (
                      <div className="mx-quote-box">
                        근거문({snippet.clauseNo}): "{snippet.text}"
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          {USE_MOCK && <div className="mx-card mx-mono mx-dark-panel search-mcp-panel">
            <div className="search-mcp-header">
              <h5 className="search-mcp-title">Claude Desktop MCP 연동 비교</h5>
              <span className="mx-tag search-mcp-tag">동일 백엔드</span>
            </div>
            <div className="search-mcp-desc">웹 UI와 동일한 하이브리드 검색을 MCP 서버로도 호출한 결과입니다 — 검색 로직은 REST/MCP가 같은 서비스 함수를 공유합니다.</div>
            <div className="search-mcp-transcript">
              <div style={{ color: "#6EAE91" }}>$ {mockMcpTranscript.command}</div>
              <div style={{ marginTop: 8 }}>[MCP RESPONSE]</div>
              {mockMcpTranscript.entries.map((e) => (
                <div key={e.id} className="search-mcp-entry">
                  <div>- {e.id}:</div>
                  <div className="search-mcp-entry-field">* Territory: {e.territory}</div>
                  <div className="search-mcp-entry-field">* Rights: {e.rights}</div>
                  <div className="search-mcp-entry-field">* Expiration: {e.expiration}</div>
                  <div className="search-mcp-entry-field">* Semantic Match: {e.match}</div>
                </div>
              ))}
            </div>
          </div>}
        </div>
      )}
      {results.length === 0 && searchResult && !searchError && <p>검색 결과가 없습니다.</p>}

      <div className="search-footnote mx-mt-20">✱ 검색 결과에는 원본 계약서의 마스킹된 민감 항목(계약 금액 등)이 직접 노출되지 않습니다. {USE_MOCK && "(데모 데이터)"}</div>
    </div>
  );
}

function InterpretedConditions({ interpreted, territoryLabel }) {
  const chips = [];
  if (interpreted.territories?.length) {
    chips.push(interpreted.territories.map((t) => territoryLabel[t] ?? t).join(", "));
  }
  if (interpreted.exclusivity) {
    chips.push(EXCLUSIVITY_LABEL[interpreted.exclusivity] ?? interpreted.exclusivity);
  }
  if (interpreted.signedFrom || interpreted.signedTo) {
    chips.push(`${interpreted.signedFrom ?? "…"} ~ ${interpreted.signedTo ?? "…"} 체결`);
  }
  if (chips.length === 0) return null;
  return (
    <div className="mx-card mx-card-pad search-interpreted-card mx-mb-20">
      <div className="search-meta-card-label">질의에서 감지된 조건</div>
      <div className="search-interpreted-chips">
        {chips.map((c, i) => (
          <span key={i} className="mx-tag mx-tag-outline">
            {c}
          </span>
        ))}
      </div>
    </div>
  );
}

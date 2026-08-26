import { useState } from "react";

// 기존/신규 계약 기간을 막대로 비교하고, 겹치는 구간만 심각도 색(severityVar)으로 표시한다.
// 라벨 열과 그래프 영역을 분리해서, 눈금/중첩 구간/막대가 전부 같은 좌표계(플롯 영역 기준
// 0~100%)를 쓰게 한다 — 안 그러면 라벨 너비만큼 중첩 구간이 막대와 어긋나 보인다.
export default function ConflictTimeline({ existing, incoming, existingTitle, incomingTitle, overlap, severityVar }) {
  const [hover, setHover] = useState(null);
  const dates = [existing.start, existing.end, incoming.start, incoming.end];
  const min = dates.reduce((a, b) => (new Date(b) < new Date(a) ? b : a));
  const max = dates.reduce((a, b) => (new Date(b) > new Date(a) ? b : a));
  const totalDays = Math.max(daySpan(min, max), 1);
  const pct = (d) => (daySpan(min, d) / totalDays) * 100;
  const years = yearTicks(min, max, pct);

  return (
    <div className="conflict-timeline">
      <div className="conflict-timeline-body">
        <div className="conflict-timeline-labels">
          <div className="conflict-timeline-label-spacer" />
          <div className="conflict-timeline-row-label">
            <span className="conflict-timeline-row-role">기존) 등록계약</span>
            <span className="conflict-timeline-row-title">{existingTitle}</span>
          </div>
          <div className="conflict-timeline-row-label">
            <span className="conflict-timeline-row-role">신규) 검토중</span>
            <span className="conflict-timeline-row-title">{incomingTitle}</span>
          </div>
        </div>

        <div className="conflict-timeline-plot">
          <div className="conflict-timeline-axis">
            {years.map(({ year, pct: tickPct }) => (
              <span
                key={year}
                className="conflict-timeline-tick"
                style={{ left: `${tickPct}%`, transform: tickPct < 4 ? "translateX(0)" : tickPct > 96 ? "translateX(-100%)" : "translateX(-50%)" }}
              >
                {year}
              </span>
            ))}
          </div>

          {overlap && (
            <div
              className="conflict-timeline-overlap-band"
              style={{
                left: `${pct(overlap.start)}%`,
                width: `${Math.max(pct(overlap.end) - pct(overlap.start), 0.5)}%`,
                background: `var(${severityVar})`,
              }}
            />
          )}

          <TimelineTrack
            start={existing.start}
            end={existing.end}
            pct={pct}
            cls="conflict-timeline-bar--existing"
            active={hover === "existing"}
            onHover={() => setHover("existing")}
            onLeave={() => setHover(null)}
          />
          <TimelineTrack
            start={incoming.start}
            end={incoming.end}
            pct={pct}
            cls="conflict-timeline-bar--incoming"
            active={hover === "incoming"}
            onHover={() => setHover("incoming")}
            onLeave={() => setHover(null)}
          />
        </div>
      </div>

      {overlap && (
        <div className="conflict-timeline-legend">
          <span className="conflict-timeline-legend-swatch" style={{ background: `var(${severityVar})` }} />
          중첩 구간 {overlap.start} ~ {overlap.end}
        </div>
      )}
    </div>
  );
}

function TimelineTrack({ start, end, pct, cls, active, onHover, onLeave }) {
  return (
    <div className="conflict-timeline-track-row" onMouseEnter={onHover} onMouseLeave={onLeave}>
      <div className={`conflict-timeline-fill ${cls}`} style={{ left: `${pct(start)}%`, width: `${Math.max(pct(end) - pct(start), 1)}%` }} />
      {active && (
        <div className="conflict-timeline-tooltip" style={{ left: `${pct(start)}%` }}>
          {start} ~ {end}
        </div>
      )}
    </div>
  );
}

function daySpan(a, b) {
  return (new Date(b).getTime() - new Date(a).getTime()) / 86400000;
}

// 실제 계약 기간은 임의 범위일 수 있어(수십 년짜리도 가능) 연 단위 눈금 간격을 범위에
// 맞춰 조정하고, 플롯 영역(0~100%) 밖으로 나가는 눈금(예: 시작일이 1/1이 아닐 때의
// 첫 연도)은 아예 만들지 않는다 — 위치를 자르는 게 아니라 애초에 안 그린다.
function yearTicks(minStr, maxStr, pct) {
  const minY = new Date(minStr).getFullYear();
  const maxY = new Date(maxStr).getFullYear();
  const span = maxY - minY;
  const step = span > 20 ? 5 : span > 10 ? 2 : 1;

  const out = [];
  for (let y = minY; y <= maxY; y += step) {
    const tickPct = pct(`${y}-01-01`);
    if (tickPct >= 0 && tickPct <= 100) out.push({ year: y, pct: tickPct });
  }
  return out;
}

// 시연 구간 C(충돌 판정)의 핵심 UI 요소.
// DB가 EXCLUDE 제약조건으로 거부한 건을 화면에서 눈에 띄게 표시한다.
export default function ConflictBadge({ conflict }) {
  if (!conflict) return null;
  return (
    <span
      style={{
        background: "#fef3c7",
        border: "1px solid #f59e0b",
        borderRadius: 4,
        padding: "2px 8px",
        fontSize: 12,
        color: "#b45309",
      }}
      title="conflicting key value violates exclusion constraint"
    >
      충돌 감지됨
    </span>
  );
}

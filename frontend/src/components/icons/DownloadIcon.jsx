// 다운로드 화살표. 유니코드 ⭳(U+2B73)는 일부 시스템 폰트에 글리프가 없어 빈 박스로
// 깨져 보일 수 있어 인라인 SVG로 대체했다 — 외부 아이콘 파일 의존 없이 자체 렌더링된다.
export default function DownloadIcon({ size = 12, className }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
      className={className}
      style={{ verticalAlign: -1 }}
    >
      <path d="M8 2v8.5M4.5 7 8 10.5 11.5 7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.5 13h11" strokeLinecap="round" />
    </svg>
  );
}

export default function Tooltip({ label, children = "?", className = "" }) {
  return (
    <span className={`mx-tooltip${className ? ` ${className}` : ""}`} data-tooltip={label} tabIndex={0} aria-label={label}>
      {children}
    </span>
  );
}

import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useSecuritySessionLabel } from "../lib/securitySession.js";
import "../styles/layout.css";

const navLinkClass = ({ isActive }) => `mx-nav-link${isActive ? " active" : ""}`;

export default function Layout({ children }) {
  const sessionLabel = useSecuritySessionLabel();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  // 페이지를 옮기면 열려 있던 사이드바 메뉴를 자동으로 닫는다 — 다음 화면에서도
  // 열린 채로 남아있으면 콘텐츠를 가린다.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  // 열려 있을 때 Esc로도 닫을 수 있게 한다.
  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(e) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <button
          type="button"
          className="app-nav-hamburger"
          aria-label={menuOpen ? "메뉴 닫기" : "메뉴 열기"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <span />
          <span />
          <span />
        </button>

        <Link to="/" className="app-logo">
          <span className="app-logo-mark" />
          MINDEX
        </Link>

        <div className={`app-nav-links${menuOpen ? " app-nav-links--open" : ""}`}>
          <NavLink to="/" end className={navLinkClass}>
            계약관리
          </NavLink>
          <NavLink to="/ips" className={navLinkClass}>
            IP 관리
          </NavLink>
          <NavLink to="/search" className={navLinkClass}>
            통합 검색
          </NavLink>
        </div>

        <div className="app-nav-right">
          {sessionLabel && <span className="mx-tag mx-tag-accent">보안 세션 · {sessionLabel} 남음</span>}
          <div className="app-user">
            <div className="app-user-avatar">JD</div>
            <div>
              <div className="app-user-name">정민우 책임</div>
              <div className="app-user-team">글로벌 권리 정산팀</div>
            </div>
          </div>
        </div>
      </nav>

      {menuOpen && <div className="app-nav-backdrop" onClick={() => setMenuOpen(false)} />}

      <main className="app-main">{children}</main>
    </div>
  );
}

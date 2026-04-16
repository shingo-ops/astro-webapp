/**
 * ナビゲーションバー用ドロップダウン（GAS互換）。
 *
 * - 親ボタンをクリックで開閉
 * - サブメニュー外クリックで自動クローズ
 * - サブメニュー内のどれかが active なら親もアクティブ状態
 *
 * 変更履歴:
 *   2026-04-17: 初版作成
 */

import { ReactNode, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

interface Props {
  label: string;
  /** サブメニューが active とみなされる pathname の prefix 群 */
  activePaths: string[];
  children: ReactNode;
}

export default function NavDropdown({ label, activePaths, children }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // ルート変更時は閉じる
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  const isActive = activePaths.some((p) => location.pathname.startsWith(p));

  return (
    <div className={`nav-dropdown ${open ? "open" : ""}`} ref={ref}>
      <button
        className={`nav-dropdown-toggle ${isActive ? "active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {label}
        <span className="nav-dropdown-caret">▾</span>
      </button>
      {open && <div className="nav-dropdown-menu">{children}</div>}
    </div>
  );
}

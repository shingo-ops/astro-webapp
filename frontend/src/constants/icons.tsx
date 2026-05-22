/**
 * アイコン一元管理モジュール
 *
 * lucide-react アイコンと絵文字の代替 SVG を集約する。
 * 全コンポーネントはここからインポートすること。
 *
 * - パスエイリアス未設定のため相対パスで import すること
 * - lucide-react v1.14.0 使用
 * - lp/（Astro）はスコープ外
 * - BadgesPage の icon フィールドはユーザー入力値のためスコープ外
 */

import type { LucideIcon } from "lucide-react";
import {
  Moon, Sun, Globe,
  Check, AlertTriangle, X,
  BarChart2, User, Target, Briefcase, Package,
  Users, Key, Settings, Folder,
  Construction, MessageSquare,
  LayoutDashboard, FileText, HelpCircle, ShieldCheck,
  MoreHorizontal, ChevronDown, LogOut, SlidersHorizontal, Search,
} from "lucide-react";

// ステータス（✓ ⚠ ✕ の代替）
export const STATUS_ICONS = {
  check:   Check,
  warning: AlertTriangle,
  error:   X,
} satisfies Record<string, LucideIcon>;

// カテゴリ（RolesPage の CATEGORY_META 用）
// "_default" はフォールバック用
export const CATEGORY_ICONS: Record<string, LucideIcon> = {
  "レポート": BarChart2,
  "顧客":     User,
  "リード":   Target,
  "案件":     Briefcase,
  "注文":     Package,
  "チーム":   Users,
  "ロール":   Key,
  "システム": Settings,
  "_default": Folder,
};

// ページ用（🚧 💬 の代替）
export const PAGE_ICONS = {
  comingSoon: Construction,
  inboxEmpty: MessageSquare,
} satisfies Record<string, LucideIcon>;

// テーマ切り替え（Layout.tsx）
// light: ライトモード時 → ダークへ切り替えるボタンに表示
// dark:  ダークモード時 → ライトへ切り替えるボタンに表示
export const THEME_ICONS = {
  light: Moon,
  dark:  Sun,
} satisfies Record<string, LucideIcon>;

// 言語切り替え（Layout.tsx 🌐 の代替）
export const GlobeIcon: LucideIcon = Globe;

// ナビゲーション（Layout.tsx サイドバー・トップバー）
export const NAV_ICONS = {
  dashboard:   LayoutDashboard,
  leads:       Users,
  inventory:   Package,
  fileText:    FileText,
  report:      BarChart2,
  help:        HelpCircle,
  admin:       ShieldCheck,
  settings:    Settings,
  more:        MoreHorizontal,
  chevronDown: ChevronDown,
  logout:      LogOut,
  filter:      SlidersHorizontal,
  search:      Search,
} satisfies Record<string, LucideIcon>;

// カスタム SVG: Tabler Icons brand-wechat（MIT ライセンス）
// Layout.tsx の /lead-chat ナビアイテム用（🌐 ではなくチャットアイコン）
export function LeadChatIcon({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
      <path d="M16.5 10c3.038 0 5.5 2.015 5.5 4.5c0 1.397 -.72 2.644 -1.861 3.516l.356 1.984l-2.104 -1.028c-.405 .103 -.826 .028 -1.242 .028c-3.038 0 -5.5 -2.015 -5.5 -4.5s2.462 -4.5 5.5 -4.5z" />
      <path d="M11.5 6c-3.866 0 -7 2.686 -7 6c0 1.747 .87 3.316 2.253 4.4l-.403 2.6l2.761 -1.399c.684 .19 1.565 .399 2.389 .399c.329 0 .655 -.016 .976 -.047" />
    </svg>
  );
}

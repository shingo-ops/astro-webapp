/**
 * アイコン一元管理モジュール
 *
 * @phosphor-icons/react アイコンと絵文字の代替 SVG を集約する。
 * 全コンポーネントはここからインポートすること。
 *
 * - パスエイリアス未設定のため相対パスで import すること
 * - weight のデフォルトは App.tsx の IconContext.Provider で "light" に統一
 * - lp/（Astro）はスコープ外
 * - BadgesPage の icon フィールドはユーザー入力値のためスコープ外
 */

import "./platform-icon.css";
import type { Icon } from "@phosphor-icons/react";
import { Envelope } from "@phosphor-icons/react";

// Icon 型を再エクスポート（他ファイルが @phosphor-icons/react を直接 import しなくて済む）
export type { Icon };
// 後方互換エイリアス（RolesPage.tsx 等が LucideIcon 型を参照しているため）
export type LucideIcon = Icon;

import {
  Moon, Sun, Globe,
  Check, Warning, X,
  ChartBar, User, Target, Briefcase, Package,
  Users, Key, GearSix, Folder,
  HardHat, Chat, ChatCircle, ClipboardText,
  SquaresFour, FileText, Question, ShieldCheck,
  DotsThree, CaretDown, SignOut, SlidersHorizontal, MagnifyingGlass,
  Trash, Archive, EnvelopeOpen,
  CalendarBlank,
  TrendUp, Bell, CalendarCheck, ArrowRight, Flag,
} from "@phosphor-icons/react";

// ステータス（✓ ⚠ ✕ の代替）
export const STATUS_ICONS = {
  check:   Check,
  warning: Warning,
  error:   X,
} satisfies Record<string, Icon>;

// 個別エクスポート（StatusBar 等で直接参照）
export { Check, Warning, X };

// カテゴリ（RolesPage の CATEGORY_META 用）
// "_default" はフォールバック用
export const CATEGORY_ICONS: Record<string, Icon> = {
  "レポート": ChartBar,
  "顧客":     User,
  "リード":   Target,
  "案件":     Briefcase,
  "注文":     Package,
  "チーム":   Users,
  "ロール":   Key,
  "システム": GearSix,
  "_default": Folder,
};

// ページ用（🚧 💬 の代替）
export const PAGE_ICONS = {
  comingSoon:  HardHat,
  inboxEmpty:  Chat,
  kartePanel:  ClipboardText, // 受信箱モバイルドロワー「カルテ」ボタン用
} satisfies Record<string, Icon>;

// テーマ切り替え（Layout.tsx）
// light: ライトモード時 → ダークへ切り替えるボタンに表示
// dark:  ダークモード時 → ライトへ切り替えるボタンに表示
export const THEME_ICONS = {
  light: Moon,
  dark:  Sun,
} satisfies Record<string, Icon>;

// 言語切り替え（Layout.tsx 🌐 の代替）
export const GlobeIcon: Icon = Globe;

// ナビゲーション（Layout.tsx サイドバー・トップバー）
export const NAV_ICONS = {
  dashboard:   SquaresFour,
  leads:       Users,
  inventory:   Package,
  fileText:    FileText,
  report:      ChartBar,
  schedule:    CalendarBlank,
  help:        Question,
  admin:       ShieldCheck,
  settings:    GearSix,
  more:        DotsThree,
  chevronDown: CaretDown,
  logout:      SignOut,
  filter:      SlidersHorizontal,
  search:      MagnifyingGlass,
  close:       X,
} satisfies Record<string, Icon>;

// ダッシュボード強化用
export const DashboardIcons = {
  forecast:  TrendUp,
  reminder:  Bell,
  goalDone:  CalendarCheck,
  arrowRight: ArrowRight,
  goalFlag:  Flag,
} satisfies Record<string, Icon>;

// ============================================================
// プラットフォームアイコン（InboxPage 会話バッジ用）
// アセット: 各社公式ブランドリソースセンターより取得（/public/brand-icons/）
//   Messenger: meta.com/brand/resources/facebook/messenger-icon/
//   Instagram:  meta.com/brand/resources/instagram/instagram-brand/
//   WhatsApp:   meta.com/brand/resources/whatsapp/whatsapp-brand/
//   Discord:    discord.com/branding
//   Telegram:   telegram.org/img/t_logo.svg
// ブランド商標: 各社所有。API 連携アプリでのプラットフォーム識別表示は
//              各社 Platform Policy で許可済み。
// ============================================================

/** 公式アセットファイル名（/public/brand-icons/ 配下） */
const PLATFORM_IMG: Record<string, string> = {
  messenger: "/brand-icons/messenger.svg",
  instagram: "/brand-icons/instagram.png",  // 公式SVGは印刷用高解像度のためPNG(96px)使用
  whatsapp:  "/brand-icons/whatsapp.svg",
  discord:   "/brand-icons/discord.svg",
  telegram:  "/brand-icons/telegram.svg",
};

/** 独自の円形背景を含むアイコン → wrap幅いっぱいに表示（0.72比率不要） */
const FULL_CIRCLE_ICONS = new Set(["messenger", "instagram", "whatsapp", "telegram"]);

/**
 * プラットフォームバッジアイコン（会話リスト アバター右下表示用）
 * size はアイコン本体サイズ。外側のボーダー・位置は conv-platform-dot CSS が担う。
 */
export function PlatformIcon({ platform, size = 16 }: { platform: string | null; size?: number }) {
  if (!platform) return null;

  // Mail / Email
  if (platform === "mail" || platform === "email") {
    return (
      <span className="platform-icon-wrap platform-icon-wrap--mail" style={{ width: size, height: size }}>
        <Envelope size={Math.round(size * 0.7)} color="white" aria-hidden="true" />
      </span>
    );
  }

  const src = PLATFORM_IMG[platform];
  if (!src) {
    // 未知プラットフォーム: グレー丸
    return (
      <span className="platform-icon-wrap--unknown" style={{ width: size, height: size }} />
    );
  }

  // 円形背景ありアイコンはwrapを満たす / シンボルのみ(Discord等)は72%で内側に収める
  const imgSize = FULL_CIRCLE_ICONS.has(platform) ? size : Math.round(size * 0.72);

  return (
    <span className="platform-icon-wrap" style={{ width: size, height: size }}>
      <img
        src={src}
        width={imgSize}
        height={imgSize}
        alt=""
        aria-hidden="true"
        draggable={false}
      />
    </span>
  );
}

// 受信箱ヘッダーアクションアイコン（未読にする / 対象外 / 削除）
export const INBOX_ACTION_ICONS = {
  markUnread: EnvelopeOpen,
  exclude:    Archive,
  delete:     Trash,
} satisfies Record<string, Icon>;

// Layout.tsx の /lead-chat ナビアイテム用
export function LeadChatIcon({ size = 20, className }: { size?: number; className?: string }) {
  return <ChatCircle size={size} className={className} aria-hidden="true" />;
}

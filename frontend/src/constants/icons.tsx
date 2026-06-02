/**
 * アイコン一元管理モジュール
 *
 * 全コンポーネントはここからインポートすること。
 *
 * - solid  (@heroicons/react/24/solid)  : ダッシュボード・ステータス・アクション等
 * - outline(@heroicons/react/24/outline): サイドバーナビゲーション（NAV_ICONS）
 * - size prop は hi() ラッパーで width/height に変換
 * - weight prop は受け取るが無視（バリアントは import 元で固定）
 * - lp/（Astro）はスコープ外
 * - BadgesPage の icon フィールドはユーザー入力値のためスコープ外
 */

import "./platform-icon.css";
import { forwardRef } from "react";
import type { CSSProperties, ComponentType, SVGProps, ForwardRefExoticComponent, RefAttributes } from "react";

// ============================================================
// アイコン型定義（@phosphor-icons/react 依存を排除した独自定義）
// ============================================================

/** アイコンコンポーネントが受け取る props */
export type IconProps = {
  size?: number | string;
  color?: string;
  weight?: string;  // Heroicons では無視（solid 固定）
  className?: string;
  style?: CSSProperties;
};

/** アイコンコンポーネント型 — 全 ICON_* 定数の値型 */
export type Icon = ForwardRefExoticComponent<IconProps & RefAttributes<SVGSVGElement>>;

// 後方互換エイリアス（RolesPage.tsx 等が LucideIcon 型を参照しているため）
export type LucideIcon = Icon;

// ── solid: ダッシュボード・ステータス・アクション・カテゴリ等 ──────────────
import {
  MoonIcon, SunIcon, GlobeAltIcon,
  CheckIcon, ExclamationTriangleIcon, XMarkIcon,
  ChartBarIcon, UserIcon, SignalIcon, BriefcaseIcon, CubeIcon,
  UsersIcon, KeyIcon, Cog6ToothIcon, Cog8ToothIcon, FolderIcon,
  WrenchScrewdriverIcon, ChatBubbleLeftIcon, ChatBubbleOvalLeftIcon, ClipboardDocumentListIcon,
  DocumentTextIcon,
  EllipsisHorizontalIcon,
  TrashIcon, EnvelopeIcon, EnvelopeOpenIcon,
  ArrowTrendingUpIcon, BellIcon, CalendarDaysIcon, ArrowRightIcon, FlagIcon,
  ReceiptPercentIcon,
  UserCircleIcon, LockClosedIcon, PhoneIcon,
  ArchiveBoxIcon,
  ArrowUpIcon, ArrowDownIcon,
  LanguageIcon,
  PaperAirplaneIcon,
  PaperClipIcon,
} from "@heroicons/react/24/solid";

// ── outline: サイドバーナビゲーション専用 ────────────────────────────────
import {
  Squares2X2Icon,
  UsersIcon as UsersOutlineIcon,
  CubeIcon as CubeOutlineIcon,
  DocumentTextIcon as DocumentTextOutlineIcon,
  ReceiptPercentIcon as ReceiptPercentOutlineIcon,
  ChartBarIcon as ChartBarOutlineIcon,
  CalendarIcon,
  QuestionMarkCircleIcon,
  ShieldCheckIcon,
  Cog6ToothIcon as Cog6ToothOutlineIcon,
  EllipsisHorizontalIcon as EllipsisHorizontalOutlineIcon,
  ChevronDownIcon,
  ArrowRightOnRectangleIcon,
  AdjustmentsHorizontalIcon,
  MagnifyingGlassIcon,
  XMarkIcon as XMarkOutlineIcon,
  ChatBubbleOvalLeftIcon as ChatBubbleOvalLeftOutlineIcon,
  TruckIcon as TruckOutlineIcon,
  Cog8ToothIcon as Cog8ToothOutlineIcon,
} from "@heroicons/react/24/outline";

/**
 * Heroicons コンポーネントを Icon API（size/weight/color props）に変換するアダプター。
 * weight は受け取るが無視（solid 固定）。
 */
function hi(HeroIcon: ComponentType<SVGProps<SVGSVGElement>>): Icon {
  const Wrapped = forwardRef<SVGSVGElement, IconProps>(
    ({ size = 24, color, className, style }, ref) => (
      <HeroIcon
        ref={ref}
        width={size}
        height={size}
        color={color}
        className={className}
        style={style}
      />
    )
  );
  return Wrapped as unknown as Icon;
}

// ── solid wrapped（ダッシュボード・ステータス・アクション等）────────────
const Moon      = hi(MoonIcon);
const Sun       = hi(SunIcon);
const Globe     = hi(GlobeAltIcon);
const Check     = hi(CheckIcon);
const Warning   = hi(ExclamationTriangleIcon);
const X         = hi(XMarkIcon);
const ChartBar  = hi(ChartBarIcon);
const User      = hi(UserIcon);
const Target    = hi(SignalIcon);
const Briefcase = hi(BriefcaseIcon);
const Package   = hi(CubeIcon);
const Users     = hi(UsersIcon);
const Key       = hi(KeyIcon);
const GearSix   = hi(Cog6ToothIcon);
const GearEight        = hi(Cog8ToothIcon);
const Folder    = hi(FolderIcon);
const HardHat   = hi(WrenchScrewdriverIcon);
const Chat      = hi(ChatBubbleLeftIcon);
const ChatCircle    = hi(ChatBubbleOvalLeftIcon);
const ClipboardText = hi(ClipboardDocumentListIcon);
const FileText      = hi(DocumentTextIcon);
const DotsThree     = hi(EllipsisHorizontalIcon);
const Trash         = hi(TrashIcon);
const Envelope      = hi(EnvelopeOpenIcon);  // markRead = 開封済み封筒
const EnvelopeClosed = hi(EnvelopeIcon);     // markUnread = 未開封封筒（完全ソリッド）
const TrendUp       = hi(ArrowTrendingUpIcon);
const ArrowUp       = hi(ArrowUpIcon);
const ArrowDown     = hi(ArrowDownIcon);
const Bell          = hi(BellIcon);
const CalendarCheck = hi(CalendarDaysIcon);
const ArrowRight    = hi(ArrowRightIcon);
const Flag          = hi(FlagIcon);
const Receipt       = hi(ReceiptPercentIcon);
const UserCircle    = hi(UserCircleIcon);
const Lock          = hi(LockClosedIcon);
const Phone         = hi(PhoneIcon);
const ArchiveBox    = hi(ArchiveBoxIcon);
const Languages     = hi(LanguageIcon);
const PaperAirplane = hi(PaperAirplaneIcon);
const Paperclip     = hi(PaperClipIcon);

// ── outline wrapped（サイドバーナビゲーション専用）────────────────────────
const SquaresFour       = hi(Squares2X2Icon);
const UsersOutline      = hi(UsersOutlineIcon);
const PackageOutline    = hi(CubeOutlineIcon);
const FileTextOutline   = hi(DocumentTextOutlineIcon);
const ReceiptOutline    = hi(ReceiptPercentOutlineIcon);
const TruckOutline      = hi(TruckOutlineIcon);
const ChartBarOutline   = hi(ChartBarOutlineIcon);
const CalendarBlank     = hi(CalendarIcon);
const QuestionOutline   = hi(QuestionMarkCircleIcon);
const ShieldCheckOutline = hi(ShieldCheckIcon);
const GearSixOutline    = hi(Cog6ToothOutlineIcon);
const DotsThreeOutline  = hi(EllipsisHorizontalOutlineIcon);
const CaretDown         = hi(ChevronDownIcon);
const SignOut           = hi(ArrowRightOnRectangleIcon);
const SlidersHorizontal = hi(AdjustmentsHorizontalIcon);
const MagnifyingGlass   = hi(MagnifyingGlassIcon);
const XOutline          = hi(XMarkOutlineIcon);
const GearEightOutline  = hi(Cog8ToothOutlineIcon);

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
/* eslint-disable local/no-japanese-literal -- DB 定義のカテゴリキー（backend permission prefix と一致・変更不可） */
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
/* eslint-enable local/no-japanese-literal */

// ページ用（🚧 💬 の代替）
export const PAGE_ICONS = {
  comingSoon:    HardHat,
  inboxEmpty:    Chat,
  kartePanel:    ClipboardText, // 受信箱モバイルドロワー「カルテ」ボタン用
  settingsSolid: GearEight,     // 受信箱ヘッダー設定ボタン（solid）
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
// outline バリアント使用（塗りつぶしなし・サイドバーデザイン要件）
export const NAV_ICONS = {
  dashboard:   SquaresFour,        // outline
  leads:       UsersOutline,       // outline
  inventory:   PackageOutline,     // outline
  fileText:    FileTextOutline,    // outline
  orders:      TruckOutline,       // outline
  report:      ChartBarOutline,    // outline
  schedule:    CalendarBlank,      // outline
  help:        QuestionOutline,    // outline
  admin:       ShieldCheckOutline, // outline
  settings:    GearEightOutline,    // outline
  more:        DotsThreeOutline,   // outline
  chevronDown: CaretDown,          // outline
  logout:      SignOut,            // outline
  filter:      SlidersHorizontal,  // outline
  search:      MagnifyingGlass,    // outline
  close:       XOutline,           // outline
} satisfies Record<string, Icon>;

// ダッシュボード強化用
export const DashboardIcons = {
  forecast:  TrendUp,
  reminder:  Bell,
  goalDone:  CalendarCheck,
  arrowRight: ArrowRight,
  goalFlag:  Flag,
  trendUp:   ArrowUp,
  trendDown: ArrowDown,
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

/** 真円のブランドロゴ（SVG） → circular バッジで表示 */
const FULL_CIRCLE_ICONS = new Set(["messenger", "whatsapp", "telegram"]);

/**
 * スクワークル（角丸四角形）形状のロゴ（PNG）→ squircle バッジで表示
 * Instagram の公式アセットは真円ではなく squircle のため、
 * Meta Business Suite 同様にバッジも squircle 形状で表示する。
 */
export const SQUIRCLE_ICONS = new Set(["instagram"]);

/**
 * プラットフォームバッジアイコン（会話リスト アバター右下表示用）
 * size はアイコン本体サイズ。外側のボーダー・位置は conv-platform-dot CSS が担う。
 */
export function PlatformIcon({ platform, size = 16 }: { platform: string | null; size?: number }) {
  if (!platform) return null;

  // Mail / Email
  if (platform === "mail" || platform === "email") {
    const iconSize = Math.round(size * 0.7);
    return (
      <span className="platform-icon-wrap platform-icon-wrap--mail" style={{ width: size, height: size }}>
        <EnvelopeIcon width={iconSize} height={iconSize} color="white" aria-hidden="true" />
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

  // squircle(Instagram) → squircle wrap でフル充填 / 真円SVG → circle wrap でフル充填 / シンボルのみ(Discord等) → 72%
  const isSquircle = SQUIRCLE_ICONS.has(platform);
  const imgSize = (FULL_CIRCLE_ICONS.has(platform) || isSquircle) ? size : Math.round(size * 0.72);
  const wrapClass = isSquircle ? "platform-icon-wrap platform-icon-wrap--squircle" : "platform-icon-wrap";

  return (
    <span className={wrapClass} style={{ width: size, height: size }}>
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

// アカウント設定（AccountSettingsPage）
export const ACCOUNT_ICONS = {
  profile:      UserCircle,
  security:     Lock,
  phone:        Phone,
  preferences:  GearSix,
  language:     Globe,
} satisfies Record<string, Icon>;

// 受信箱ヘッダーアクションアイコン（既読 / 未読にする / 対象外 / 削除）
export const INBOX_ACTION_ICONS = {
  markRead:   Envelope,        // EnvelopeOpenIcon  — 開封済み封筒
  markUnread: EnvelopeClosed,  // EnvelopeIcon      — 未開封封筒（完全ソリッド）
  exclude:    ArchiveBox,      // ArchiveBoxIcon    — アーカイブ
  delete:     Trash,           // TrashIcon         — 削除
  translate:  Languages,       // LanguageIcon      — AI翻訳（ADR-088）
  send:       PaperAirplane,   // PaperAirplaneIcon — 送信ボタン（solid）
  attach:     Paperclip,       // PaperClipIcon     — 画像添付ボタン
} satisfies Record<string, Icon>;

// Layout.tsx の /lead-chat ナビアイテム用（outline バリアント — サイドバー統一仕様）
export function LeadChatIcon({ size = 20, className }: { size?: number; className?: string }) {
  return <ChatBubbleOvalLeftOutlineIcon width={size} height={size} className={className} aria-hidden="true" />;
}

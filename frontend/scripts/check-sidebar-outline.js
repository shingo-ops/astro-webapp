/**
 * check-sidebar-outline.js
 *
 * サイドバーナビゲーションのアイコンが outline バリアントのみを使用していることを検証する。
 *
 * 仕様（ADR-074相当）:
 *   - NAV_ICONS の全値は「// ── outline wrapped」セクションで定義された定数のみ
 *   - LeadChatIcon は outline バリアント（ChatBubbleOvalLeftOutlineIcon）を使用
 *
 * 理由: サイドバーナビは塗りつぶしなし (outline) で統一する UX 仕様。
 * solid アイコンを誤って追加した場合に CI でブロックする。
 *
 * check:all に含まれる。CI で自動実行。
 */

import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const src = readFileSync(resolve(root, "src/constants/icons.tsx"), "utf8");

// ── outline wrapped セクション内の定数名を抽出 ────────────────────────────
// セクション開始: "// ── outline wrapped"
// セクション終了: "// ステータス" (次のブロック)
const outlineSectionMatch = src.match(
  /\/\/ ── outline wrapped[\s\S]+?(?=\/\/ ステータス)/
);
if (!outlineSectionMatch) {
  console.error("[sidebar-outline] ❌ icons.tsx に outline wrapped セクションが見つかりません");
  process.exit(1);
}

const outlineConsts = new Set(
  [...outlineSectionMatch[0].matchAll(/^const (\w+)\s*=/gm)].map((m) => m[1])
);

// ── NAV_ICONS の値を抽出 ────────────────────────────────────────────────────
const navIconsMatch = src.match(/export const NAV_ICONS\s*=\s*\{([\s\S]+?)\}\s*satisfies/);
if (!navIconsMatch) {
  console.error("[sidebar-outline] ❌ NAV_ICONS が見つかりません");
  process.exit(1);
}

// "key: Value, // comment" → ["Value", ...]
const navEntries = [...navIconsMatch[1].matchAll(/\w+\s*:\s*(\w+)/g)].map((m) => m[1]);

// ── LeadChatIcon の outline 使用確認 ──────────────────────────────────────
const leadChatMatch = src.match(/export function LeadChatIcon[\s\S]+?^}/m);
const leadChatSrc = leadChatMatch?.[0] ?? "";
const usesOutline = leadChatSrc.includes("OutlineIcon");

// ── 検証 ───────────────────────────────────────────────────────────────────
let errors = 0;

for (const val of navEntries) {
  if (!outlineConsts.has(val)) {
    console.error(
      `[sidebar-outline] ❌ NAV_ICONS の値 "${val}" は outline ラップ定数ではありません` +
      ` (outline wrapped セクションに定義されていない)`
    );
    errors++;
  }
}

if (!usesOutline) {
  console.error(
    "[sidebar-outline] ❌ LeadChatIcon が outline バリアントを使用していません" +
    " (ChatBubbleOvalLeftOutlineIcon を使用してください)"
  );
  errors++;
}

if (errors === 0) {
  console.log(
    `[sidebar-outline] ✅ NAV_ICONS ${navEntries.length}項目 + LeadChatIcon — 全て outline バリアント`
  );
  process.exit(0);
} else {
  console.error(
    `[sidebar-outline] ${errors}件のエラー。` +
    "サイドバーナビには /24/outline バリアントのみ使用してください。"
  );
  process.exit(1);
}

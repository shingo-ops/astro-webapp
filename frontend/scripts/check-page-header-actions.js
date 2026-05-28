/**
 * check-page-header-actions.js
 *
 * ページヘッダーアクションエリアの CSS 定義が SSoT に従っているかを検証する。
 *
 * 仕様:
 *   - .page-header-actions は components.css のみで定義すること（重複禁止）
 *   - .page-header-select  は components.css のみで定義すること（重複禁止）
 *   - pages/ 以下の CSS に *-header-btns / *-header-actions という
 *     ページ固有のラッパークラスを定義してはならない
 *   - pages/ 以下の CSS に *-period-select / *-view-select という
 *     ページ固有のプルダウンクラスを定義してはならない
 *   - pages/ 以下の CSS に *-faq-btn / *-settings-btn という
 *     ページ固有ヘッダーボタンクラスを定義してはならない
 *     （代わりに .btn-ghost / .icon-btn を使用すること）
 *
 * 理由: ヘッダーアクションの見た目を全ページで統一するため、
 *       デザイントークンの変更を1ヶ所（components.css）で完結させる。
 *
 * check:all に含まれる。CI で自動実行。
 */

import { readFileSync, readdirSync, statSync } from "fs";
import { resolve, join, dirname, relative } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const srcDir = resolve(root, "src");
const componentsCSS = resolve(srcDir, "components.css");

// ── CSS ファイルを再帰収集 ──────────────────────────────────────────────────
function collectCSS(dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...collectCSS(full));
    } else if (entry.endsWith(".css")) {
      files.push(full);
    }
  }
  return files;
}

const allCSS = collectCSS(srcDir);
let errors = 0;

// ── チェック1: .page-header-actions の定義は components.css のみ ──────────
for (const file of allCSS) {
  if (file === componentsCSS) continue; // SSoT ファイルはスキップ
  const src = readFileSync(file, "utf8");
  if (/\.page-header-actions\s*\{/.test(src)) {
    console.error(
      `[page-header-actions] ❌ ${relative(root, file)}: ` +
      `.page-header-actions が重複定義されています。` +
      `定義は components.css のみに置いてください。`
    );
    errors++;
  }
}

// ── チェック2: .page-header-select の定義は components.css のみ ────────────
for (const file of allCSS) {
  if (file === componentsCSS) continue;
  const src = readFileSync(file, "utf8");
  if (/\.page-header-select[\s:{]/.test(src)) {
    console.error(
      `[page-header-actions] ❌ ${relative(root, file)}: ` +
      `.page-header-select が重複定義されています。` +
      `定義は components.css のみに置いてください。`
    );
    errors++;
  }
}

// ── チェック3: pages/ 以下にページ固有ラッパークラスを禁止 ─────────────────
const pagesDir = resolve(srcDir, "pages");
const pageCSS = collectCSS(pagesDir);

// 検出パターン: .xxx-header-btns / .xxx-header-actions (page-header-actions は除外)
const WRAPPER_PATTERN = /\.\w+-header-(btns|actions)\s*\{/g;
// 検出パターン: .xxx-period-select / .xxx-view-select
const SELECT_PATTERN = /\.\w+-(period|view)-select[\s:{]/g;
// 検出パターン: ページ固有ヘッダーボタン (.xxx-faq-btn / .xxx-settings-btn 等)
const HEADER_BTN_PATTERN = /\.\w+-(faq|settings)-btn[\s:{]/g;

for (const file of pageCSS) {
  const src = readFileSync(file, "utf8");
  const rel = relative(root, file);

  const wrapperMatches = [...src.matchAll(WRAPPER_PATTERN)]
    .map((m) => m[0].trim())
    .filter((m) => !m.startsWith(".page-header-actions"));

  for (const match of wrapperMatches) {
    console.error(
      `[page-header-actions] ❌ ${rel}: ` +
      `ページ固有ラッパー "${match}" が定義されています。` +
      `代わりに .page-header-actions を使用してください。`
    );
    errors++;
  }

  const selectMatches = [...src.matchAll(SELECT_PATTERN)].map((m) => m[0].trim());
  for (const match of selectMatches) {
    console.error(
      `[page-header-actions] ❌ ${rel}: ` +
      `ページ固有プルダウン "${match}" が定義されています。` +
      `代わりに .page-header-select を使用してください。`
    );
    errors++;
  }

  const headerBtnMatches = [...src.matchAll(HEADER_BTN_PATTERN)].map((m) => m[0].trim());
  for (const match of headerBtnMatches) {
    console.error(
      `[page-header-actions] ❌ ${rel}: ` +
      `ページ固有ヘッダーボタン "${match}" が定義されています。` +
      `代わりに .btn-ghost または .icon-btn を使用してください。`
    );
    errors++;
  }
}

// ── 結果 ──────────────────────────────────────────────────────────────────
if (errors === 0) {
  console.log(
    `[page-header-actions] ✅ .page-header-actions / .page-header-select — SSoT 維持（components.css のみ定義）`
  );
  process.exit(0);
} else {
  console.error(
    `[page-header-actions] ${errors}件のエラー。` +
    `ヘッダーアクションは components.css の共通クラスを使用してください。`
  );
  process.exit(1);
}

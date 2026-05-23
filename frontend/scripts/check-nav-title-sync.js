#!/usr/bin/env node
/**
 * check-nav-title-sync.js (CLAUDE.md: ページ見出し統一規約)
 *
 * pages/ 配下の TSX ファイルで h1/h2 が `t("xxx.title")` 形式のキーを
 * 使っていないか検査する。サイドナビにあるページは必ず `t("nav.xxx")` か
 * `usePageTitle()` を使うことで、サイドナビ文言とページ見出しの乖離を防ぐ。
 *
 * 検出パターン: <h1 or <h2 に `t("xxx.title")` （xxx が "nav" 以外）
 *
 * 使用方法: node scripts/check-nav-title-sync.js
 * CI: npm run check:nav-sync
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname, basename, relative, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGES_DIR = join(__dirname, '../src/pages');

// 詳細ページ・非ナビページなど、.title キーを使うことが正当なファイル
// （レコード名表示・サイドバーに直接存在しないページ）
const EXCLUDE_FILES = new Set([
  'QuoteDetailPage.tsx',    // 見積コードを h2 に表示
  'InvoiceDetailPage.tsx',  // 請求書番号を h2 に表示
  'OrdersPage.tsx',         // サイドバーに存在しない
  'NotificationsPage.tsx',  // サイドバーに存在しない
  'CustomersPage.tsx',      // サイドバーは /companies 経由（直接リンクなし）
  'LoginPage.tsx',          // ナビ外ページ
  'OAuthCallbackPage.tsx',  // ナビ外ページ
]);

// サイドバーに存在しないディレクトリ（スーパー管理者専用ナビ）
const EXCLUDE_DIRS = new Set([
  'super-admin', // 管理者専用サブナビ体系、main sidebar 対象外
  'admin',       // テナント管理ページ群、main sidebar 対象外
]);

// h1/h2 内で nav.* 以外の xxx.title キーを使っているパターン
// 例: <h2>{t("commissions.title")}</h2>  → NG
// 例: <h2>{t("nav.commissionSettings")}</h2>  → OK（検出しない）
const HEADING_TITLE_PATTERN = /<h[12][\s>][^<]*t\("(?!nav\.)[\w.]+\.title"/;

// モーダル・パネル・ドロワー等の非ページ h2 は除外
// className にこれらのキーワードが含まれていれば「セクション/モーダルタイトル」と判断
const MODAL_CLASS_PATTERN = /className="[^"]*(?:modal|panel|drawer|card|section|settings-modal|detail|title)[^"]*"/;

function collectTsxFiles(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      if (EXCLUDE_DIRS.has(entry)) continue;
      results.push(...collectTsxFiles(full));
    } else if (extname(entry) === '.tsx') {
      results.push(full);
    }
  }
  return results;
}

const files = collectTsxFiles(PAGES_DIR).filter(
  (f) => !EXCLUDE_FILES.has(basename(f))
);

let hasError = false;

for (const file of files) {
  const lines = readFileSync(file, 'utf8').split('\n');
  lines.forEach((line, i) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) return;
    if (HEADING_TITLE_PATTERN.test(trimmed) && !MODAL_CLASS_PATTERN.test(trimmed)) {
      const rel = relative(process.cwd(), file);
      console.error(`❌ ${rel}:${i + 1}`);
      console.error(`   ${trimmed}`);
      console.error(
        `   → h1/h2 は t("nav.xxx") または usePageTitle() を使ってください（CLAUDE.md: ページ見出し統一規約）`
      );
      hasError = true;
    }
  });
}

if (hasError) {
  console.error('');
  console.error(
    '❌ nav-title-sync チェック FAILED: サイドナビと同じ nav.* キーを使ってください'
  );
  process.exit(1);
} else {
  console.log('✅ nav-title-sync チェック PASSED');
  process.exit(0);
}

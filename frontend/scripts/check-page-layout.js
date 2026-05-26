#!/usr/bin/env node
/**
 * check-page-layout.js
 *
 * src/pages/ 配下の tsx ファイルを 2 種類検査する:
 *   1. raw <h2 が残っていないか
 *   2. <PageLayout に subtitleKey が付いているか
 *
 * eslint-disable-next-line コメントが直前行にある h2 は除外（正当な例外として認める）。
 * PageLayout コンポーネント自体は除外。
 * subtitleKey 不要なページ（システム管理系）は SUBTITLE_ALLOWLIST で除外。
 *
 * 使用方法: node scripts/check-page-layout.js
 * CI: npm run check:page-layout（check:all に含まれる）
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, relative } from 'path';
import { execSync } from 'child_process';

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const pagesDir = join(repoRoot, 'frontend/src/pages');

/**
 * subtitleKey チェックから除外するページ（パスの一部でマッチ）。
 * 除外理由: システム・管理ツール系のページはサブタイトルが不要。
 */
const SUBTITLE_ALLOWLIST = [
  'super-admin/',      // スーパー管理者専用ツール
  'admin/',            // テナント管理ツール
  'design-system/',    // 開発用デザインシステムページ
  'crm/CustomerHub',   // タブコンテナ（CRMハブ）、子ページで表示
];

function walkTsx(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      results.push(...walkTsx(fullPath));
    } else if (entry.endsWith('.tsx')) {
      results.push(fullPath);
    }
  }
  return results;
}

const files = walkTsx(pagesDir);
const h2Violations = [];
const subtitleViolations = [];

for (const file of files) {
  // PageLayout コンポーネント自体はスキップ
  if (file.includes('PageLayout')) continue;

  const content = readFileSync(file, 'utf8');
  const relPath = relative(repoRoot, file);
  const lines = content.split('\n');

  // --- チェック 1: raw <h2 ---
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].includes('<h2')) continue;
    const prevLine = i > 0 ? lines[i - 1].trim() : '';
    if (
      prevLine.includes('eslint-disable-next-line') ||
      prevLine.includes('eslint-disable')
    ) {
      continue;
    }
    h2Violations.push(`${relPath}:${i + 1}`);
  }

  // --- チェック 2: <PageLayout に subtitleKey があるか ---
  // allowlist に含まれるファイルはスキップ
  const isAllowlisted = SUBTITLE_ALLOWLIST.some((pattern) =>
    relPath.includes(pattern)
  );
  if (isAllowlisted) continue;

  // <PageLayout の開始タグブロック（次の > まで）を抽出してチェック
  const tagBlocks = content.match(/<PageLayout[\s\S]*?>/g) || [];
  for (const block of tagBlocks) {
    if (!block.includes('subtitleKey')) {
      subtitleViolations.push(relPath);
      break; // ファイルにつき 1 件のみ報告
    }
  }
}

// --- 結果出力 ---
let failed = false;

if (h2Violations.length > 0) {
  failed = true;
  console.error('❌ PageLayout チェック FAILED: 以下のページに raw <h2> が残っています');
  console.error('   <PageLayout navKey="nav.xxx"> を使ってください（frontend/CLAUDE.md 参照）');
  console.error('   例外の場合は // eslint-disable-next-line no-restricted-syntax を直前行に追加');
  console.error('');
  for (const v of h2Violations) {
    console.error(`   ${v}`);
  }
  console.error('');
}

if (subtitleViolations.length > 0) {
  failed = true;
  console.error('❌ subtitleKey チェック FAILED: 以下のページに subtitleKey がありません');
  console.error('   <PageLayout subtitleKey="xxx.subtitle"> を追加してください（frontend/CLAUDE.md 参照）');
  console.error('   システム管理ページは SUBTITLE_ALLOWLIST に追加することで除外可能です');
  console.error('');
  for (const v of subtitleViolations) {
    console.error(`   ${v}`);
  }
  console.error('');
}

if (failed) {
  process.exit(1);
} else {
  console.log('✅ PageLayout チェック PASSED（raw <h2> なし・subtitleKey 付与済み）');
  process.exit(0);
}

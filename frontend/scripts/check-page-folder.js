#!/usr/bin/env node
/**
 * check-page-folder.js
 *
 * src/pages/ 直下に .tsx ファイルを直接置くことを禁止する。
 * 全ページは必ず pages/<lowercase-kebab-case>/ サブフォルダに配置すること。
 *
 * 免除: super-admin/ admin/ は既にカテゴリフォルダ内のため対象外。
 *
 * 使用方法: node scripts/check-page-folder.js
 * CI: npm run check:page-folder（check:all に含まれる）
 */

import { readdirSync, statSync } from 'fs';
import { join, relative } from 'path';
import { execSync } from 'child_process';

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const pagesDir = join(repoRoot, 'frontend/src/pages');

const violations = [];

for (const entry of readdirSync(pagesDir)) {
  const fullPath = join(pagesDir, entry);
  const stat = statSync(fullPath);
  // pages/ 直下の .tsx ファイルを検出（ディレクトリは OK）
  if (!stat.isDirectory() && entry.endsWith('.tsx')) {
    violations.push(relative(repoRoot, fullPath));
  }
}

if (violations.length > 0) {
  console.error('❌ ページフォルダ構造チェック FAILED: pages/ 直下に .tsx ファイルがあります');
  console.error('   全ページは pages/<lowercase-kebab-case>/ サブフォルダに移動してください');
  console.error('   例: InboxPage.tsx → pages/inbox/InboxPage.tsx');
  console.error('');
  for (const v of violations) {
    console.error(`   ${v}`);
  }
  process.exit(1);
} else {
  console.log('✅ ページフォルダ構造チェック PASSED');
  process.exit(0);
}

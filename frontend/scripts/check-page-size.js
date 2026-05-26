#!/usr/bin/env node
/**
 * check-page-size.js
 *
 * *Page.tsx ファイルの行数上限を強制する。
 *   - 通常ページ: 800 行以下
 *   - super-admin/ / admin/ 配下: 1000 行以下
 *
 * 対象: src/pages/**\/*Page.tsx（*Page.tsx サフィックスのみ）
 *
 * 使用方法: node scripts/check-page-size.js
 * CI: npm run check:page-size（check:all に含まれる）
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, relative } from 'path';
import { execSync } from 'child_process';

const REGULAR_LIMIT = 800;
const ADMIN_LIMIT = 1000;

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const pagesDir = join(repoRoot, 'frontend/src/pages');

/** pages/ 以下を再帰的に走査して *Page.tsx を収集 */
function collectPageFiles(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      results.push(...collectPageFiles(fullPath));
    } else if (entry.endsWith('Page.tsx')) {
      results.push(fullPath);
    }
  }
  return results;
}

const files = collectPageFiles(pagesDir);
const violations = [];

for (const file of files) {
  const rel = relative(repoRoot, file);
  const isAdmin = rel.includes('/super-admin/') || rel.includes('/admin/');
  const limit = isAdmin ? ADMIN_LIMIT : REGULAR_LIMIT;
  const content = readFileSync(file, 'utf8');
  const lines = content.split('\n').length;
  if (lines > limit) {
    violations.push({ rel, lines, limit });
  }
}

if (violations.length > 0) {
  console.error('❌ ページサイズチェック FAILED: 行数上限を超えているファイルがあります');
  console.error('   800 行超のページは pages/<name>/ サブフォルダのコンポーネントに分割してください');
  console.error('');
  for (const { rel, lines, limit } of violations) {
    console.error(`   ${rel}: ${lines} 行 (上限: ${limit} 行)`);
  }
  process.exit(1);
} else {
  console.log('✅ ページサイズチェック PASSED');
  process.exit(0);
}

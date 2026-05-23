#!/usr/bin/env node
/**
 * check-page-layout.js
 *
 * src/pages/ 配下の tsx ファイルに raw <h2 が残っていないか検査する。
 * eslint-disable-next-line コメントが直前行にある h2 は除外（正当な例外として認める）。
 * PageLayout コンポーネント自体は除外。
 *
 * 使用方法: node scripts/check-page-layout.js
 * CI: npm run check:page-layout（check:all に含まれる）
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, relative } from 'path';
import { execSync } from 'child_process';

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const pagesDir = join(repoRoot, 'frontend/src/pages');

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
const violations = [];

for (const file of files) {
  const content = readFileSync(file, 'utf8');
  const lines = content.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].includes('<h2')) continue;
    // eslint-disable-next-line コメントが直前行にあれば正当な例外として除外
    const prevLine = i > 0 ? lines[i - 1].trim() : '';
    if (
      prevLine.includes('eslint-disable-next-line') ||
      prevLine.includes('eslint-disable')
    ) {
      continue;
    }
    violations.push(`${relative(repoRoot, file)}:${i + 1}`);
  }
}

if (violations.length > 0) {
  console.error('❌ PageLayout チェック FAILED: 以下のページに raw <h2> が残っています');
  console.error('   <PageLayout navKey="nav.xxx"> を使ってください（frontend/CLAUDE.md 参照）');
  console.error('   例外の場合は // eslint-disable-next-line no-restricted-syntax を直前行に追加');
  console.error('');
  for (const v of violations) {
    console.error(`   ${v}`);
  }
  process.exit(1);
} else {
  console.log('✅ PageLayout チェック PASSED');
  process.exit(0);
}

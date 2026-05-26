#!/usr/bin/env node
/**
 * check-stories-count.js (ADR-073)
 *
 * src/components/ 配下の視覚コンポーネントに対応する .stories.tsx が
 * 存在するかを検査する。CI ブロック対象（終了コード 1 で失敗）。
 *
 * 使用方法: node scripts/check-stories-count.js
 * CI: npm run check:stories
 */

import { readdirSync, existsSync } from 'fs';
import { join, basename, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const COMPONENTS_DIR = join(__dirname, '../src/components');

// UI表示がないコンポーネントは対象外（認証ガード・HOC等）
const EXEMPT = new Set([
  'ProtectedRoute.tsx',
]);

const files = readdirSync(COMPONENTS_DIR).filter(
  (f) => f.endsWith('.tsx') && !f.endsWith('.stories.tsx') && !EXEMPT.has(f)
);

let missing = [];
for (const file of files) {
  const storyFile = join(COMPONENTS_DIR, file.replace('.tsx', '.stories.tsx'));
  if (!existsSync(storyFile)) {
    missing.push(file);
  }
}

if (missing.length > 0) {
  console.error('❌ check:stories — 以下のコンポーネントに .stories.tsx がありません:');
  for (const f of missing) {
    console.error(`   src/components/${f}`);
  }
  console.error('');
  console.error('修正方法: 対応する .stories.tsx を作成してください。');
  console.error('除外する場合（UI表示なし）: EXEMPT 配列に追加してください。');
  process.exit(1);
}

console.log(`✅ check:stories — 全 ${files.length} コンポーネントに stories が存在します`);

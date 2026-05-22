#!/usr/bin/env node
/**
 * check-jsx-emoji.js
 *
 * TSX ファイル内の絵文字・記号文字（✓ ⚠ 等）直書きを禁止する。
 * 代わりに constants/icons.tsx のアイコンコンポーネントを使うこと。
 *
 * スコープ外（EXCLUDE_FILES）:
 *   - BadgesPage.tsx: icon フィールドはユーザー入力値のため除外
 *
 * 使用方法: node scripts/check-jsx-emoji.js
 */

import { readFileSync, readdirSync, statSync } from "fs";
import { join, extname, basename, relative, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, "../src");

// スコープ外ファイル
const EXCLUDE_FILES = new Set(["BadgesPage.tsx"]);

// 絵文字 + 記号（✓ U+2713, ⚠ U+26A0, 等を含む主要範囲）
const EMOJI_PATTERN = /[\u2300-\u27BF\u{1F000}-\u{1FFFF}]/u;

function collectTsxFiles(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      results.push(...collectTsxFiles(full));
    } else if (extname(entry) === ".tsx") {
      results.push(full);
    }
  }
  return results;
}

const files = collectTsxFiles(SRC_DIR).filter(
  (f) => !EXCLUDE_FILES.has(basename(f))
);

let hasError = false;

for (const file of files) {
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    const trimmed = line.trim();
    // コメント行・import 行はスキップ
    if (
      trimmed.startsWith("//") ||
      trimmed.startsWith("/*") ||
      trimmed.startsWith("*") ||
      trimmed.startsWith("import ")
    )
      return;

    if (EMOJI_PATTERN.test(trimmed)) {
      const rel = relative(process.cwd(), file);
      console.error(`❌ ${rel}:${i + 1}`);
      console.error(`   ${trimmed}`);
      console.error(
        `   → constants/icons.tsx のアイコンコンポーネントを使ってください`
      );
      hasError = true;
    }
  });
}

if (hasError) {
  console.error("\n❌ JSX絵文字チェック FAILED");
  process.exit(1);
} else {
  console.log("✅ JSX絵文字チェック PASSED");
}

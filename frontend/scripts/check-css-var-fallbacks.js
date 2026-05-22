#!/usr/bin/env node
/**
 * check-css-var-fallbacks.js
 *
 * CSS/TSX ファイル内の var(--xxx, #hex) フォールバックパターンを禁止する。
 * フォールバック hex はダークモードを無効化する隠れたバグの原因になる。
 *
 * 対象: src/ 以下の .css / .tsx / .ts ファイル
 * 除外: index.css（変数定義ファイル）
 *
 * 使用方法: node scripts/check-css-var-fallbacks.js
 */

import { readFileSync, readdirSync, statSync } from "fs";
import { join, extname, basename, relative, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, "../src");

const EXCLUDE_FILES = new Set(["index.css"]);
const TARGET_EXTS = new Set([".css", ".tsx", ".ts"]);

// var(--xxx, #hhh) — スペースの有無を問わず検出
const VAR_FALLBACK_HEX = /var\(--[\w-]+\s*,\s*#[0-9a-fA-F]{3,8}\)/;

function collectFiles(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      results.push(...collectFiles(full));
    } else if (TARGET_EXTS.has(extname(entry))) {
      results.push(full);
    }
  }
  return results;
}

const targetFiles = collectFiles(SRC_DIR).filter(
  (f) => !EXCLUDE_FILES.has(basename(f))
);

let hasError = false;

for (const file of targetFiles) {
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    const trimmed = line.trim();
    // コメント行はスキップ
    if (
      trimmed.startsWith("//") ||
      trimmed.startsWith("/*") ||
      trimmed.startsWith("*")
    )
      return;

    if (VAR_FALLBACK_HEX.test(trimmed)) {
      const rel = relative(process.cwd(), file);
      console.error(`❌ ${rel}:${i + 1}`);
      console.error(`   ${trimmed}`);
      console.error(
        `   → var() フォールバックに hex を使わないでください。` +
          `変数が未定義なら index.css の :root と :root.force-dark 両方に追加してください。`
      );
      hasError = true;
    }
  });
}

if (hasError) {
  console.error("\n❌ CSS var フォールバックチェック FAILED");
  process.exit(1);
} else {
  console.log("✅ CSS var フォールバックチェック PASSED");
}

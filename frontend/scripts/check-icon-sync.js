/**
 * check-icon-sync.js
 *
 * Verifies that constants/iconSizes.ts and tokens.css define identical icon size values.
 * CSS variables cannot be passed directly as number props to Lucide icons,
 * so both files must exist — but they must stay in sync.
 *
 * Exits with code 1 if values diverge.
 */

import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

// --- Parse tokens.css for --icon-* values ---
const cssText = readFileSync(resolve(root, "src/tokens.css"), "utf8");
const cssTokens = {};
for (const [, name, value] of cssText.matchAll(/--icon-(\w+):\s*(\d+)px/g)) {
  cssTokens[name] = Number(value);
}

// --- Parse iconSizes.ts for ICON object values ---
const tsText = readFileSync(resolve(root, "src/constants/iconSizes.ts"), "utf8");
const tsTokens = {};
for (const [, name, value] of tsText.matchAll(/(\w+):\s*(\d+),/g)) {
  // Skip non-icon keys (type assertions, etc.)
  if (["sm", "md", "base", "lg", "xl"].includes(name)) {
    tsTokens[name] = Number(value);
  }
}

// --- Compare ---
let errors = 0;

const allKeys = new Set([...Object.keys(cssTokens), ...Object.keys(tsTokens)]);
for (const key of allKeys) {
  const cssVal = cssTokens[key];
  const tsVal = tsTokens[key];
  if (cssVal === undefined) {
    console.error(`[icon-sync] ❌ --icon-${key} found in iconSizes.ts but MISSING in tokens.css`);
    errors++;
  } else if (tsVal === undefined) {
    console.error(`[icon-sync] ❌ --icon-${key} found in tokens.css but MISSING in iconSizes.ts`);
    errors++;
  } else if (cssVal !== tsVal) {
    console.error(`[icon-sync] ❌ --icon-${key}: tokens.css=${cssVal}px, iconSizes.ts=${tsVal} — VALUES DIFFER`);
    errors++;
  }
}

if (errors === 0) {
  console.log(`[icon-sync] ✅ All ${allKeys.size} icon sizes in sync (tokens.css ↔ iconSizes.ts)`);
  process.exit(0);
} else {
  console.error(`[icon-sync] ${errors} sync error(s). Update tokens.css or iconSizes.ts to match.`);
  process.exit(1);
}

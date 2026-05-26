/**
 * check-breakpoint-sync.js
 *
 * Verifies that constants/breakpoints.ts and tokens.css define identical breakpoint values.
 * CSS variables cannot be used in @media conditions (browser spec constraint),
 * so both files must coexist — but they must stay in sync.
 *
 * Mapping:
 *   tokens.css              ↔  breakpoints.ts
 *   --breakpoint-mobile-max  ↔  MOBILE_MAX
 *   --breakpoint-tablet-min  ↔  TABLET_MIN
 *   --breakpoint-tablet-max  ↔  TABLET_MAX
 *   --breakpoint-desktop-min ↔  DESKTOP_MIN
 *   --breakpoint-xl-min      ↔  XL_MIN
 *
 * Exits with code 1 if values diverge.
 */

import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

// CSS key (kebab-case after --breakpoint-) → TS key (UPPER_SNAKE_CASE in BREAKPOINTS)
const CSS_TO_TS = {
  "mobile-max":   "MOBILE_MAX",
  "tablet-min":   "TABLET_MIN",
  "tablet-max":   "TABLET_MAX",
  "desktop-min":  "DESKTOP_MIN",
  "xl-min":       "XL_MIN",
};

// --- Parse tokens.css for --breakpoint-* values ---
const cssText = readFileSync(resolve(root, "src/tokens.css"), "utf8");
const cssTokens = {};
for (const [, name, value] of cssText.matchAll(/--breakpoint-([\w-]+):\s*(\d+)px/g)) {
  cssTokens[name] = Number(value);
}

// --- Parse breakpoints.ts for BREAKPOINTS object values ---
const tsText = readFileSync(resolve(root, "src/constants/breakpoints.ts"), "utf8");
const tsTokens = {};
for (const [, name, value] of tsText.matchAll(/(\w+):\s*(\d+),/g)) {
  for (const [cssKey, tsKey] of Object.entries(CSS_TO_TS)) {
    if (tsKey === name) {
      tsTokens[cssKey] = Number(value);
      break;
    }
  }
}

// --- Compare ---
let errors = 0;

const allKeys = new Set([...Object.keys(cssTokens), ...Object.keys(tsTokens)]);
for (const key of allKeys) {
  const cssVal = cssTokens[key];
  const tsVal = tsTokens[key];

  if (cssVal === undefined) {
    console.error(`[breakpoint-sync] ❌ "${CSS_TO_TS[key] || key}" found in breakpoints.ts but MISSING in tokens.css`);
    errors++;
  } else if (tsVal === undefined) {
    console.error(`[breakpoint-sync] ❌ --breakpoint-${key} found in tokens.css but MISSING in breakpoints.ts`);
    errors++;
  } else if (cssVal !== tsVal) {
    console.error(`[breakpoint-sync] ❌ ${key}: tokens.css=${cssVal}px, breakpoints.ts[${CSS_TO_TS[key]}]=${tsVal} — VALUES DIFFER`);
    errors++;
  }
}

if (errors === 0) {
  console.log(`[breakpoint-sync] ✅ All ${allKeys.size} breakpoints in sync (tokens.css ↔ breakpoints.ts)`);
  process.exit(0);
} else {
  console.error(`[breakpoint-sync] ${errors} sync error(s). Update tokens.css or breakpoints.ts to match.`);
  process.exit(1);
}

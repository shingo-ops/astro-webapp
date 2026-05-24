#!/usr/bin/env node
/**
 * download-brand-assets.js
 *
 * 公式ブランドリソースセンターからプラットフォームアイコンを取得し
 * frontend/public/brand-icons/ に配置する。
 *
 * 使用方法:
 *   node scripts/download-brand-assets.js              # 全プラットフォーム
 *   node scripts/download-brand-assets.js messenger    # 特定プラットフォームのみ
 *
 * 終了コード:
 *   0 = 成功
 *   1 = 予期しないエラー
 *   2 = Meta ページが CI runner IP をブロック → fallback Job が Issue を起票
 *
 * 依存: @playwright/test (frontend/devDependencies)、unzip、ImageMagick convert
 * 参照: ADR-068-platform-brand-asset-policy.md
 */

const { chromium } = require('playwright');
const { execSync }  = require('child_process');
const fs   = require('fs');
const path = require('path');

const OUT = path.resolve(__dirname, '../frontend/public/brand-icons');
const TMP = '/tmp/brand-assets-dl';

fs.mkdirSync(TMP, { recursive: true });
fs.mkdirSync(OUT, { recursive: true });

// ── ヘルパー ──────────────────────────────────────────────────────────────

function curlDownload(url, dest) {
  execSync(`curl -sL --max-time 30 "${url}" -o "${dest}"`, { stdio: 'pipe' });
}

function unzipTo(zipPath, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  execSync(`unzip -o "${zipPath}" -d "${destDir}"`, { stdio: 'pipe' });
}

function findFiles(dir) {
  try {
    return execSync(`find "${dir}" -type f`, { encoding: 'utf8' })
      .trim().split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

/** DOM から ZIP ダウンロード URL を探す（CDN href / data-href / JSON 埋め込み） */
async function extractDownloadUrl(page) {
  return page.evaluate(() => {
    // 1. <a href="...zip"> または <a href="...akamaihd...">
    const links = Array.from(document.querySelectorAll('a[href]'));
    const zipLink = links.find(l =>
      l.href && (l.href.includes('.zip') || l.href.includes('akamaihd') || l.href.includes('fbcdn'))
    );
    if (zipLink) return zipLink.href;

    // 2. data-href 属性
    const dataLinks = Array.from(document.querySelectorAll('[data-href]'));
    const dataZip = dataLinks.find(l => l.dataset.href && l.dataset.href.includes('.zip'));
    if (dataZip) return dataZip.dataset.href;

    // 3. <script type="application/json"> 内の URL
    for (const s of document.querySelectorAll('script')) {
      const txt = s.textContent || '';
      const m = txt.match(/"(https?:\/\/[^"]+\.zip[^"]*)"/);
      if (m) return m[1];
    }

    return null;
  });
}

/** ボタンクリックで download イベントを捕捉して URL を取得（フォールバック） */
async function clickAndCapture(page) {
  const dlPromise = page.waitForEvent('download', { timeout: 10000 }).catch(() => null);
  const btn = await page.$('button:has-text("Download"), a:has-text("Download"), [aria-label*="Download"]');
  if (!btn) return null;
  await btn.click();
  const dl = await dlPromise;
  return dl ? dl.url() : null;
}

/** CI runner IP ブロックを判定 */
function isBlocked(response, title) {
  if (!response || response.status() === 403 || response.status() === 429) return true;
  const t = (title || '').toLowerCase();
  return t.includes('captcha') || t.includes('access denied') || t.includes('403');
}

// ── Meta 汎用ダウンロード ─────────────────────────────────────────────────

const META_CONFIGS = {
  messenger: {
    url: 'https://www.meta.com/brand/resources/facebook/messenger-icon/',
    pick: (files) => files.find(f => /\.svg$/i.test(f) && !f.includes('__MACOSX')),
    dest: path.join(OUT, 'messenger.svg'),
  },
  whatsapp: {
    url: 'https://www.meta.com/brand/resources/whatsapp/whatsapp-brand/',
    pick: (files) => files.find(f =>
      /green/i.test(f) && /\.svg$/i.test(f) && !f.includes('__MACOSX')
    ) || files.find(f => /\.svg$/i.test(f) && !f.includes('__MACOSX')),
    dest: path.join(OUT, 'whatsapp.svg'),
  },
  instagram: {
    url: 'https://www.meta.com/brand/resources/instagram/instagram-brand/',
    // PNG を優先（公式 SVG は印刷用高解像度）。なければ SVG を一時保存して convert
    pick: (files) =>
      files.find(f => /\.png$/i.test(f) && !f.includes('__MACOSX')) ||
      files.find(f => /\.svg$/i.test(f) && !f.includes('__MACOSX')),
    dest: null, // 後処理あり
    tmp: path.join(TMP, 'instagram_hires'),
  },
};

async function downloadMeta(page, name) {
  const cfg = META_CONFIGS[name];
  console.log(`[Meta/${name}] ${cfg.url}`);

  const resp = await page.goto(cfg.url, { waitUntil: 'networkidle', timeout: 30000 });
  const title = await page.title();

  if (isBlocked(resp, title)) {
    throw Object.assign(new Error(`BLOCKED: status=${resp?.status()} title="${title}"`), { blocked: true });
  }

  let dlUrl = await extractDownloadUrl(page);
  if (!dlUrl) dlUrl = await clickAndCapture(page);
  if (!dlUrl) throw new Error(`[Meta/${name}] download URL not found`);

  const zipPath = path.join(TMP, `${name}.zip`);
  curlDownload(dlUrl, zipPath);
  const extractDir = path.join(TMP, name);
  unzipTo(zipPath, extractDir);

  const allFiles = findFiles(extractDir).map(f => f.replace(extractDir + '/', ''));
  const picked = cfg.pick(allFiles);
  if (!picked) throw new Error(`[Meta/${name}] target file not found in ZIP. Files: ${allFiles.join(', ')}`);

  const src = path.join(extractDir, picked);

  if (cfg.dest) {
    fs.copyFileSync(src, cfg.dest);
    console.log(`✓ [Meta/${name}] → ${path.basename(cfg.dest)}`);
  } else {
    // Instagram: tmp に保存して変換は呼び出し元（workflow）が担当
    const ext = path.extname(picked);
    const tmpDest = `${cfg.tmp}${ext}`;
    fs.copyFileSync(src, tmpDest);
    console.log(`✓ [Meta/${name}] → ${tmpDest} (変換待ち)`);
  }
}

// ── Discord ──────────────────────────────────────────────────────────────

async function downloadDiscord(page) {
  console.log('[Discord] https://discord.com/branding');

  const resp = await page.goto('https://discord.com/branding', {
    waitUntil: 'networkidle',
    timeout: 30000,
  });
  const title = await page.title();

  if (isBlocked(resp, title)) {
    throw new Error(`[Discord] BLOCKED: status=${resp?.status()}`);
  }

  let dlUrl = await extractDownloadUrl(page);
  if (!dlUrl) dlUrl = await clickAndCapture(page);
  if (!dlUrl) throw new Error('[Discord] download URL not found');

  const zipPath = path.join(TMP, 'discord.zip');
  curlDownload(dlUrl, zipPath);
  unzipTo(zipPath, path.join(TMP, 'discord'));

  const svgFiles = findFiles(path.join(TMP, 'discord')).filter(f => /\.svg$/i.test(f));
  const target =
    svgFiles.find(f => /blurple/i.test(f) && /symbol/i.test(f)) ||
    svgFiles.find(f => /symbol/i.test(f)) ||
    svgFiles[0];

  if (!target) throw new Error('[Discord] SVG not found in ZIP');

  fs.copyFileSync(target, path.join(OUT, 'discord.svg'));
  console.log(`✓ [Discord] → discord.svg`);
}

// ── エントリポイント ──────────────────────────────────────────────────────

async function main() {
  const targets = process.argv.slice(2).filter(a => !a.startsWith('-'));
  const platforms = targets.length > 0
    ? targets
    : ['messenger', 'instagram', 'whatsapp', 'discord'];

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  let metaBlocked = false;

  try {
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      locale: 'en-US',
    });
    const page = await context.newPage();

    // Meta
    for (const name of ['messenger', 'instagram', 'whatsapp']) {
      if (!platforms.includes(name)) continue;
      try {
        await downloadMeta(page, name);
      } catch (err) {
        if (err.blocked) {
          console.error(`Meta IP block detected (${name}): ${err.message}`);
          metaBlocked = true;
          break;
        }
        throw err;
      }
    }

    // Discord
    if (platforms.includes('discord') && !metaBlocked) {
      await downloadDiscord(page);
    }

  } finally {
    await browser.close();
  }

  if (metaBlocked) {
    console.error('Meta assets blocked. Exiting with code 2 (triggers fallback Issue).');
    process.exit(2);
  }

  console.log('All brand assets downloaded successfully.');
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});

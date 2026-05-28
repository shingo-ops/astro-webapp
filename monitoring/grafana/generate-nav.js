#!/usr/bin/env node
/**
 * monitoring/grafana/generate-nav.js
 * ===================================
 * nav-config.json を SSoT として全ダッシュボード JSON に
 * ナビゲーションリンク・description・ヘッダーテキストパネルを一括配布するスクリプト。
 *
 * 使い方:
 *   node monitoring/grafana/generate-nav.js          # 全ダッシュボードを更新
 *   node monitoring/grafana/generate-nav.js --check  # CI 整合性チェック（差分があれば exit 1）
 *
 * タブの追加・変更は nav-config.json だけ編集してこのスクリプトを実行する。
 * フォルダ構成（大カテゴリ）は nav-config.json の dashboards[uid].folder と
 * provisioning/dashboards/dashboards.yml で管理する。
 */

const fs   = require('fs');
const path = require('path');

const CHECK_MODE     = process.argv.includes('--check');
const NAV_CONFIG     = 'monitoring/grafana/nav-config.json';
const DASHBOARDS_DIR = 'monitoring/grafana/provisioning/dashboards/json';

// ヘッダーテキストパネルの識別 ID（全ダッシュボード共通の予約 ID）
const HEADER_PANEL_ID = 9999;
const HEADER_HEIGHT   = 3;

const navConfig = JSON.parse(fs.readFileSync(NAV_CONFIG, 'utf8'));

/** DASHBOARDS_DIR 以下を再帰的に走査して *.json を返す */
const collectJsonFiles = (dir) => {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectJsonFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith('.json')) {
      results.push(fullPath);
    }
  }
  return results;
};

const files = collectJsonFiles(DASHBOARDS_DIR);

const buildLinks = () =>
  navConfig.links.map(link => ({
    asDropdown:  false,
    icon:        'external link',
    includeVars: false,
    keepTime:    true,
    tags:        [],
    targetBlank: false,
    title:       link.title,
    tooltip:     '',
    type:        'link',
    url:         link.url,
  }));

/** パネル配列内の全パネルの y 座標を dy だけずらす（ネスト対応）*/
const shiftPanelsBy = (panels, dy) =>
  panels.map(p => ({
    ...p,
    gridPos: { ...p.gridPos, y: p.gridPos.y + dy },
    ...(p.panels && p.panels.length > 0
      ? { panels: shiftPanelsBy(p.panels, dy) }
      : {}),
  }));

/** 既存のヘッダーパネル（id=HEADER_PANEL_ID）を除去してから y を元に戻す */
const stripHeader = (panels) => {
  if (panels.length === 0 || panels[0].id !== HEADER_PANEL_ID) return panels;
  const headerHeight = panels[0].gridPos.h;
  return shiftPanelsBy(panels.slice(1), -headerHeight);
};

/** ヘッダーテキストパネルを生成して先頭に追加、既存パネルを HEADER_HEIGHT 分押し下げる */
const applyHeader = (panels, header) => {
  const headerPanel = {
    id:      HEADER_PANEL_ID,
    type:    'text',
    title:   '',
    gridPos: { h: HEADER_HEIGHT, w: 24, x: 0, y: 0 },
    options: {
      mode:    'html',
      content: `<div style="padding:4px 8px"><p style="margin:0;font-size:20px;font-weight:600;line-height:1.3">${header.title}</p><p style="margin:2px 0 0;font-size:10px;opacity:0.75">${header.subtitle}</p></div>`,
    },
    transparent: true,
  };
  return [headerPanel, ...shiftPanelsBy(panels, HEADER_HEIGHT)];
};

let hasError = false;

files.forEach(filePath => {
  const file      = path.basename(filePath);
  const dashboard = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const uid       = dashboard.uid || '';
  const config    = navConfig.dashboards[uid];

  // 既存ヘッダーを除去した素の panels
  const basePanels = stripHeader(dashboard.panels || []);

  // ヘッダー設定がある場合は注入、ない場合はそのまま
  const newPanels = config && config.header
    ? applyHeader(basePanels, config.header)
    : basePanels;

  const updated = {
    ...dashboard,
    links:  buildLinks(),
    panels: newPanels,
    ...(config ? { description: config.description } : {}),
  };

  const newContent = JSON.stringify(updated, null, 2) + '\n';
  const oldContent = fs.readFileSync(filePath, 'utf8');

  if (CHECK_MODE) {
    if (newContent !== oldContent) {
      console.error(`❌ ${file}: nav-config.json と同期されていません。node monitoring/grafana/generate-nav.js を実行してください。`);
      hasError = true;
    } else {
      console.log(`  ✅ ${file}: 同期済み`);
    }
  } else {
    fs.writeFileSync(filePath, newContent);
    console.log(`✅ ${file} 更新完了`);
  }
});

if (hasError) process.exit(1);
if (CHECK_MODE) console.log('\n✅ 全ダッシュボード nav-config.json と同期済み');

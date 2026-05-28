#!/usr/bin/env node
/**
 * monitoring/grafana/generate-nav.js
 * ===================================
 * nav-config.json を SSoT として全ダッシュボード JSON に
 * ナビゲーションリンクと description を一括配布するスクリプト。
 *
 * 使い方:
 *   node monitoring/grafana/generate-nav.js          # 全ダッシュボードを更新
 *   node monitoring/grafana/generate-nav.js --check  # CI 整合性チェック（差分があれば exit 1）
 *
 * タブの追加・変更は nav-config.json だけ編集してこのスクリプトを実行する。
 */

const fs   = require('fs');
const path = require('path');

const CHECK_MODE    = process.argv.includes('--check');
const NAV_CONFIG    = 'monitoring/grafana/nav-config.json';
const DASHBOARDS_DIR = 'monitoring/grafana/provisioning/dashboards/json';

const navConfig  = JSON.parse(fs.readFileSync(NAV_CONFIG, 'utf8'));
const files      = fs.readdirSync(DASHBOARDS_DIR).filter(f => f.endsWith('.json'));

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

let hasError = false;

files.forEach(file => {
  const filePath  = path.join(DASHBOARDS_DIR, file);
  const dashboard = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const uid       = dashboard.uid || '';

  const updated = {
    ...dashboard,
    links: buildLinks(),
    ...(navConfig.dashboards[uid]
      ? { description: navConfig.dashboards[uid].description }
      : {}),
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

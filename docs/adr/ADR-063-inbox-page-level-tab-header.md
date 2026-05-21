# ADR-063: Inbox ページレベル ヘッダー + 全幅タブバー

## Status
Proposed

## Date
2026-05-21

## Context（背景）

Meta Business Suite の受信箱（business.facebook.com/inbox）は以下の構造を持つ：

```
[ページヘッダー] 受信箱 ← タイトル
                メッセージへの返信や自動化の設定などができます。← サブタイトル
[全幅タブバー]  すべてのメッセージ | Messenger | Instagram | ...
[3カラム]       左パネル（会話リスト）| 中央（メッセージ）| 右（連絡先）
```

現在の salesanchor Inbox は：
- タブ（All/Leads/Converted/Customers）が左パネル内（340px幅）に閉じ込められている
- ページヘッダー（タイトル・サブタイトル）が存在しない
- Meta のレイアウトと構造的に大きく異なる

## Decision（決定）

`frontend/src/pages/InboxPage.tsx` の最上位 DOM 構造を以下に変更する：

```
inbox-wrapper（flex column, height: calc(100vh - 56px)）
  ├── inbox-page-header（タイトル + サブタイトル）
  ├── inbox-full-tab-bar（全幅タブ: All / Leads / Converted / Customers）
  └── inbox-columns（flex horizontal, flex:1, overflow:hidden）
        ├── inbox-left-panel（340px: 検索・管理・プラットフォームフィルタ・会話リスト）
        ├── inbox-center（flex:1: メッセージ）
        └── inbox-right-panel（300px: 顧客カルテ）
```

### 変更前
```
inbox-page（flex horizontal, height: calc(100vh - 56px)）
  ├── inbox-left-panel
  │    ├── inbox-panel-title（視覚的非表示）
  │    ├── inbox-lead-tabs ← タブがここにあった
  │    ├── inbox-search-row
  │    └── ...
  ├── inbox-center
  └── inbox-right-panel
```

### 変更後
```
inbox-wrapper（flex column, height: calc(100vh - 56px)）
  ├── inbox-page-header（~72px）
  │    ├── h1.inbox-page-title「受信箱」
  │    └── p.inbox-page-subtitle「メッセージの管理と返信ができます。」
  ├── inbox-full-tab-bar（52px, 全幅）
  │    └── All | Leads | Converted | Customers ← 全幅に移動
  └── inbox-columns（flex:1, overflow:hidden）
        ├── inbox-left-panel（タブなし）
        │    ├── inbox-panel-title（視覚的非表示 - a11y用）
        │    ├── inbox-search-row（検索 + 管理）
        │    ├── inbox-platform-bar
        │    └── inbox-conversation-list
        ├── inbox-center
        └── inbox-right-panel
```

## Scope

### 変更対象ファイル
- `frontend/src/pages/InboxPage.tsx`
  - CSS: `inbox-page` → `inbox-wrapper + inbox-columns`
  - CSS: `inbox-lead-tabs / inbox-lead-tab` を削除 → 新規 `inbox-full-tab-bar / inbox-full-tab` を追加
  - CSS: `inbox-page-header / inbox-page-title / inbox-page-subtitle` を追加
  - JSX: 最上位構造変更、タブをヘッダー直下に移動、左パネルからタブ除去

- `frontend/src/locales/ja.json`
  - `inbox.subtitle`: "メッセージの管理と返信ができます。"

- `frontend/src/locales/en.json`
  - `inbox.subtitle`: "Manage and respond to messages."

### 変更しないもの
- バックエンド・DB・API
- タブのフィルタロジック（leadStatusFilter、filteredConversations）
- 中央パネル・右パネルの内部構造
- App.css / Layout.tsx

## CSS 設計

```css
/* 全体ラッパー（旧 inbox-page を置換） */
.inbox-wrapper {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  overflow: hidden;
  background: #E9EBEE;
  font-family: 'SF Pro Text', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}

/* ページヘッダー */
.inbox-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px 12px;
  background: #fff;
  border-bottom: 1px solid #dadde1;
  flex-shrink: 0;
}
.inbox-page-title {
  font-size: 20px;
  font-weight: 700;
  color: #1c1e21;
  margin: 0 0 4px;
  line-height: 1.2;
}
.inbox-page-subtitle {
  font-size: 13px;
  color: #65676B;
  margin: 0;
}

/* 全幅タブバー */
.inbox-full-tab-bar {
  display: flex;
  background: #fff;
  border-bottom: 1px solid #dadde1;
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 0 8px;
}
.inbox-full-tab-bar::-webkit-scrollbar { display: none; }
.inbox-full-tab {
  height: 52px;
  padding: 0 20px;
  border: none;
  border-bottom: 3px solid transparent;
  margin-bottom: -1px;
  background: transparent;
  font-size: 15px;
  font-weight: 600;
  color: #65676B;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.1s, border-color 0.1s;
  font-family: inherit;
}
.inbox-full-tab:hover {
  color: #0064E0;
  background: rgba(0,0,0,0.03);
}
.inbox-full-tab.active {
  color: #0064E0;
  border-bottom-color: #0064E0;
}

/* 3カラム（旧 inbox-page の flex-horizontal 部分） */
.inbox-columns {
  flex: 1;
  display: flex;
  overflow: hidden;
}
```

## Consequences（影響）

- ページヘッダーが追加されることで Meta に近い視覚的インパクトになる
- タブが全幅になることで ADR-062（追客タブ追加）や将来のタブ増設に対して左パネル幅340pxの制約がなくなる
- タブの高さが 52px → 3カラムの高さが `calc(100vh - 56px - ヘッダー高 - タブ高)` 相当になるが flex で自動解決
- E2E テスト: `h1.inbox-page-title` が追加されるため E2E の見出しセレクタを確認・更新する

## Verification（完了条件）

- [ ] ページ最上部に「受信箱」（h1）と説明文が表示される
- [ ] タブ（All/Leads/Converted/Customers）がコンテンツエリア全幅に配置される
- [ ] タブクリックで会話リストが正しくフィルタされる
- [ ] 左パネル内にタブが表示されない
- [ ] 検索 + 管理ボタンが左パネル内の検索行に残っている
- [ ] プラットフォームフィルタ（Messenger/Instagram/未読）が左パネル内に残っている
- [ ] ja.json / en.json キー数が一致する
- [ ] E2E グリーン

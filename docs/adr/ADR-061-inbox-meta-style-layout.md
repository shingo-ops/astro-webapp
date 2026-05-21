# ADR-061: Inbox Meta Business Suite スタイル UI 再設計

## Status
Proposed

## Date
2026-05-21

## Context（背景）

現在の Inbox ページ（`/lead-chat`）では以下の問題がある：

- 「受信箱」タイトルが左パネル最上部に表示され、タブはその下に配置されている
- 検索ボックスと管理操作が別行に分離されている
- Meta Business Suite の UI に比べて視認性・操作性が劣っている

ユーザーの要望：
- タブを Meta と同様に検索ボックスの**上**（左パネル最上部）に配置する
- 検索ボックスと管理ボタン（管理）を横並びに配置する
- 管理ボタンからインライン操作（全て既読にする等）を実行できるようにする

## Decision（決定）

`frontend/src/pages/InboxPage.tsx` の左パネル構造を以下の順序に変更する：

```
左パネル（変更前）:
  h2「受信箱」
  タブ行（すべて/リード/…）
  検索ボックス
  プラットフォームフィルタ

左パネル（変更後）:
  タブ行（最上部・Meta スタイル・height 52px）
  検索 + 管理ボタン 横並び行
  プラットフォームフィルタ
  h2「受信箱」（スクリーンリーダー専用・視覚的に非表示）
```

### 管理ボタン（管理）

- 検索ボックスの右に配置
- クリックでドロップダウン表示
- 初期機能: 「全て既読にする」（現在フィルタ適用済みの未読会話を一括既読化）
- click-outside で自動クローズ

## Scope

### 変更対象
- `frontend/src/pages/InboxPage.tsx`
  - CSS: `.inbox-panel-title`（visually hidden に変更）、`.inbox-lead-tabs`（top スタイル）、新規 `.inbox-search-row`・`.inbox-manage-*` クラス群
  - JSX: 左パネル構造変更、管理ドロップダウン追加
  - 新規 state: `manageOpen`
  - 新規 handler: `handleMarkAllRead`
  - 新規 import: `SlidersHorizontal` from lucide-react

- `frontend/src/locales/ja.json`
  - `inbox.manage`: "管理"
  - `inbox.markAllRead`: "全て既読にする"
  - `inbox.filterUnread`: "未読"
  - `inbox.filterFollowUp`: "フォローアップ"

- `frontend/src/locales/en.json`
  - 同一キーの英語値追加

### 変更しないもの
- バックエンド・DB・APIは一切変更しない
- タブのフィルタロジック（ステータスマッピング）は変更しない
- 中央パネル・右パネルの構造は変更しない

## Consequences（影響）

- 左パネルの情報密度が向上し、Meta Business Suite に近い操作感になる
- 管理ボタンにより将来的な一括操作（アーカイブ、ラベル付け等）の拡張起点となる
- タブが最上部に来ることでステージ切り替えの視認性が向上する

## Verification（完了条件）

- [ ] タブ（すべて/リード/コンバート済み/顧客）が左パネル最上部に表示される
- [ ] 検索ボックスと「管理」ボタンが横並びで表示される
- [ ] 「管理」ボタンをクリックするとドロップダウンが表示される
- [ ] 「全て既読にする」をクリックすると未読バッジが消える
- [ ] ドロップダウン外をクリックすると閉じる
- [ ] ja.json と en.json のキー数が一致している
- [ ] CI（Playwright E2E）グリーン

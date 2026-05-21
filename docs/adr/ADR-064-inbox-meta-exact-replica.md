# ADR-064: Inbox Meta Business Suite 完全再現レイアウト

## ステータス

Accepted

## コンテキスト

ADR-063 で実装した Inbox ページは Meta Business Suite 風の 3 カラムレイアウトを実現したが、
実測スクリーンショットと比較すると以下の差異が確認された：

| 要素 | Meta実測 | 旧実装 |
|---|---|---|
| 左パネル幅 | 280px | 340px |
| 右パネル幅 | 360px | 320px |
| 会話アイテム padding | 12px 8px | 8px 12px |
| アバターサイズ | 48px | 44px |
| 会話名フォントサイズ | 15px | 14px |
| タイムスタンプフォント | 13px | 11px |
| プラットフォームドット | 14px / border 2.5px | 16px / border 2px |
| 会話セパレータ色 | #e4e6eb | var(--bg-subtle) |
| ホバー背景 | #f2f3f5 | var(--bg-hover) |
| 右パネルカード padding | 20px 16px | 16px |
| セクション区切り | border-top visible | margin-top のみ |

また以下の CSS 変数が未定義だったため、Meta の精確な色値を再現できていなかった：
- `--inbox-separator` (#e4e6eb)
- `--inbox-hover` (#f2f3f5)

## 決定

### 1. CSS 変数追加（index.css）

Inbox 専用のカラートークンを追加し、Meta の実測値を変数化する：

```css
:root {
  --inbox-separator: #e4e6eb;
  --inbox-hover: #f2f3f5;
}
:root.force-dark {
  --inbox-separator: #374151;
  --inbox-hover: #243046;
}
```

### 2. INBOX_STYLES 変更（InboxPage.tsx）

#### レイアウト寸法

- 左パネル幅: `340px` → `280px`
- 右パネル幅: `320px` → `360px`

#### 会話アイテム

- padding: `8px 12px` → `12px 8px`
- border-bottom に `--inbox-separator` を使用
- hover 背景に `--inbox-hover` を使用
- アバターサイズ: `44px` → `48px`
- プラットフォームドット: `16px` → `14px`、border: `2px` → `2.5px`
- 会話名フォント: `14px` → `15px`
- タイムスタンプ: `11px` → `13px`

#### 右パネルカード

- padding: `16px` → `20px 16px`

#### セクション区切り

- `right-panel-section` に `border-top: 1px solid var(--border)` と `padding-top: 16px` を追加
- 最初のセクション（`.right-panel-header`）は `border-top: none`
- `right-panel-section-title` の `border-bottom` を削除（カード内なので不要）

## 影響範囲

- `frontend/src/index.css`: CSS 変数追加（2 変数 × 2 テーマ）
- `frontend/src/pages/InboxPage.tsx`: INBOX_STYLES 変更のみ（JSX 変更なし）

## 代替案

- Tailwind クラスへの移行: プロジェクト全体の CSS 戦略と不一致のため却下
- ハードコードカラー使用: ADR-027 i18n ルールと同様にカラーも変数化する方針のため却下

## 関連ADR

- ADR-061: Inbox Meta スタイルレイアウト
- ADR-063: Inbox ページレベルタブヘッダー
- ADR-027: i18n ルール（CSS 変数化の方針に準拠）

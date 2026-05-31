# ADR-087: hub-shell 共通シェルレイアウト標準

- **日付**: 2026-05-31
- **ステータス**: Accepted
- **起案者**: Hikky-dev（Claude Code）
- **承認者**: しんごさん（PO）

---

## 背景

`ManagementCenterPage`（`mc-*`）と `CustomerHubPage`（`crm-*`）は
「左サブナビ + 右コンテンツ」の 2 カラムシェルを別々の CSS クラスで
重複実装していた。

- `mc-shell` / `mc-subnav` / `mc-content`（ManagementCenterPage.css）
- `crm-shell` / `crm-subnav` / `crm-content`（CustomerHubPage.css）

加えて `mc-subnav` は `background: var(--bg-surface)` で不透過だったため
`app-body` のグラデーション背景がサブナビ越しに透過せず、
`crm-subnav`（`background: transparent`）との見た目の不統一があった。

---

## 決定

1. **`hub-shell.css` を `frontend/src/` に新設し、全ハブページ共通の CSS 定義とする**
2. **クラス命名規約を `hub-*` に統一する**（旧 `mc-*` / `crm-*` は廃止）
3. **`hub-subnav` の背景を `transparent` にする**（グラデーション透過・全ハブで統一）
4. **`App.tsx` でグローバルインポート**（ページ個別のインポート不要）

### 共通クラス一覧

| クラス | 役割 |
|--------|------|
| `.hub-shell` | 左サブナビ + 右コンテンツの flex コンテナ |
| `.hub-subnav` | 左サブナビ（幅 `--mc-subnav-width`、内部スクロール） |
| `.hub-subnav-section` | セクションコンテナ（セクション見出し + アイテム群） |
| `.hub-subnav-title` | セクション見出し（大文字・muted） |
| `.hub-subnav-item` | ナビリンク（NavLink / a） |
| `.hub-content` | 右コンテンツ領域（子ルートの Outlet） |

---

## 適用対象ページ

現在:
- `ManagementCenterPage`（`/management-center/*`）
- `CustomerHubPage`（`/crm/*`）

将来の新規ハブページも `hub-*` クラスを使用すること。

---

## 廃止クラス

以下のクラスは `hub-shell.css` への統合により廃止。
再定義・再使用は `check:css-class-naming` CI で自動ブロックされる。

```
.mc-shell  .mc-subnav  .mc-subnav-section  .mc-subnav-title  .mc-subnav-item  .mc-content
.crm-shell .crm-subnav .crm-subnav-item    .crm-content
```

---

## 実装

- PR: shingo-ops/salesanchor#1279

---

## 代替案

**案 A: React コンポーネント `<HubShell>` として共通化**
→ JSX 側の変更も必要になり差分が大きくなる。CSS のみの変更で十分なため採用しない。

**案 B: 現状維持（`mc-*` / `crm-*` 並存）**
→ 同一パターンの重複・不統一な背景色の問題が残るため採用しない。

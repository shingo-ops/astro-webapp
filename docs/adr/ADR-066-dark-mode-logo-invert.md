# ADR-066: ダークモード時サイドバーロゴ白反転

## Status
Proposed

## Date
2026-05-21

## Context（背景）

現在のサイドバーロゴ（`favicon.png` / `logo.png`）はライトモード用の配色（紺・青）で作成されており、ダークモード（`:root.force-dark`）に切り替えると背景が暗くなるためロゴが見づらくなる。

LP フッターでは同様の問題を `filter: brightness(0) invert(1)` CSS フィルターで解決済み（ネイビー背景でアイコン・テキストロゴを白に反転）。アプリのサイドバーにも同じ仕組みを適用する。

## Decision（決定）

`frontend/src/App.css` に `:root.force-dark` スコープのロゴ反転ルールを追加する。

```css
:root.force-dark .sidebar-logo-icon,
:root.force-dark .sidebar-logo-text-img {
  filter: brightness(0) invert(1);
}
```

### 仕組み
| フィルター | 効果 |
|---|---|
| `brightness(0)` | 全ピクセルを黒（RGB: 0,0,0）に変換 |
| `invert(1)` | 黒を白に反転（RGB: 255,255,255） |

元のロゴは透過PNG（RGBA）のため、有色ピクセルがすべて白になり、透過部分は透過のまま保持される。

## Scope

### 変更対象ファイル
- `frontend/src/App.css`
  - `.sidebar-logo-icon` / `.sidebar-logo-text-img` に `:root.force-dark` スコープのフィルター追加

### 変更しないもの
- ロゴ画像ファイル（`favicon.png`, `logo.png`）
- ThemeContext / テーマ切り替えロジック
- LP（別リポジトリスコープ、既に対応済み）

## CSS 設計

```css
/* App.css — サイドバーロゴのダークモード反転 */
:root.force-dark .sidebar-logo-icon,
:root.force-dark .sidebar-logo-text-img {
  filter: brightness(0) invert(1);
}
```

既存のライトモード定義（`.sidebar-logo-icon { width: 36px; height: 36px; }` 等）は変更不要。

## Consequences（影響）

- **Positive**: ダークモードでもロゴが視認しやすくなる
- **Positive**: 画像ファイルの追加・変更なし。CSS 2行の追加のみ
- **Negative**: `brightness(0) invert(1)` はグレースケール変換を経由するため、ロゴが白一色になる（グラデーションや複数色は失われる）。ただしサイドバー背景が暗いため白単色で十分な視認性が得られる

## Verification（完了条件）

- [ ] ダークモード切り替え時にサイドバーの `favicon.png`（アイコン）が白表示になる
- [ ] ダークモード切り替え時にサイドバーの `logo.png`（テキスト）が白表示になる
- [ ] ライトモードではロゴが元の配色（紺・青）のまま表示される
- [ ] テーマ切り替えボタン（🌙/☀️）で即座に切り替わる（ページリロード不要）
- [ ] E2E グリーン

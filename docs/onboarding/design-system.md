# デザインシステム オンボーディング

> 読了目安: 5分 / 詳細は各 ADR リンク先を参照

---

## 1. 仕組みの全体像（素人向け）

```
色・サイズ等の値 → index.css / tokens.css に一元定義（変更はここだけ）
                       ↓
              CSS変数（var(--token)）として全体で参照
                       ↓
        CIが「直書き」「定義漏れ」を自動検出してPRをブロック
```

**やってはいけないこと** → CIが止める（自動）

| 禁止 | 代わりに |
|---|---|
| `color: #1877F2` | `color: var(--accent)` |
| `opacity: 0.5` | `opacity: var(--opacity-dim)` |
| `border-radius: 8px` | `border-radius: var(--radius-md)` |
| `style={{ color: "#fff" }}` | `style={{ color: "var(--accent)" }}` |

---

## 2. トークン定義ファイル（SSoT）

| ファイル | 何が入っているか |
|---|---|
| `src/index.css` | **色トークン**（`:root` ＋ `:root.force-dark` に必ず両方） |
| `src/tokens.css` | 色以外（spacing / radius / shadow / z-index / motion） |

> 詳細ルール: `docs/adr/ADR-067-design-token-enforcement.md`

---

## 3. 新しいカラートークンを追加する手順（5ステップ）

```bash
# Step 1: index.css の :root { } に追加
--my-new-color: #XXXXXX;

# Step 2: 同ファイルの :root.force-dark { } にも追加（必須）
--my-new-color: #YYYYYY;

# Step 3: パリティチェック（両方の定義が揃っているか確認）
cd frontend && npm run check:dark-parity

# Step 4: DesignSystemPage.tsx の COLOR_TOKENS 配列に追加
# （追加しないと check:color-token-sync が CI をブロック）
{ name: "--my-new-color", label: "説明文" },

# Step 5: 全チェックを通す
npm run check:all
```

---

## 4. CI チェック失敗時の対処（16チェック）

`npm run check:all` が失敗したら、**エラーメッセージが直し方を教えてくれる**。
迷ったら下表を参照。

| スクリプト | 何を見るか | よくある修正 |
|---|---|---|
| `check:css-colors` | CSS に `#hex` 直書き | `var(--token)` に置換 |
| `check:dark-parity` | `:root` と `:root.force-dark` の変数差異 | 漏れているほうに追加 |
| `check:css-var-fallbacks` | `var(--token, #hex)` のhexフォールバック | フォールバックを削除 |
| `check:css-values` | opacity/radius 等の数値直書き | `var(--xxx)` に置換 |
| `check:color-token-sync` | `index.css` と `COLOR_TOKENS` 配列の乖離 | `DesignSystemPage.tsx` に追加 |
| `check:stories` | コンポーネントに `.stories.tsx` がない | `ComponentName.stories.tsx` を作成 |
| `check:page-layout` | ページに生 `<h2>` / `<PageLayout>` 不使用 | `<PageLayout navKey="nav.xxx">` で包む |
| `lint` | ESLint 違反（i18n・icon・hex等） | `npm run lint:fix` → 残りは手動 |
| `check:dark-parity` | index.css 変更後の対 | 詳細: ADR-067 §パリティチェック |

その他のチェックはエラーメッセージに修正方法が記載されている。

---

## 5. ビジュアルカタログで確認する

```bash
# 開発サーバー起動後 → ブラウザで開く（開発環境のみ表示）
http://localhost:5173/design-system

# Storybook（コンポーネント単体確認）
cd frontend && npm run storybook   # → http://localhost:6006
```

---

## 6. 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| `docs/adr/ADR-067-design-token-enforcement.md` | トークン強制の全ルール・根拠 |
| `docs/adr/ADR-073-design-system-kgi-rubric.md` | KGI 100% の定義と現状 |
| `frontend/CLAUDE.md` | PageLayout / i18n / アイコンのルール |

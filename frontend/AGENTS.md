# frontend/AGENTS.md

`frontend/` 配下の作業時のみ適用。プロジェクト全体ルールは `/AGENTS.md` を参照。

---

## PageLayout ルール（全ページ必須）

ページタイトル・サブタイトルは必ず `<PageLayout navKey="nav.xxx">` 経由。
raw `<h2>` は ESLint が自動ブロック（CI で PR マージ不可）。

```tsx
// ❌ 禁止（ESLint エラー）
<h2>{t("nav.leadChat")}</h2>

// ✅ 正しい
<PageLayout navKey="nav.leadChat" subtitleKey="inbox.subtitle">
  {/* コンテンツ */}
</PageLayout>
```

新規ページ: `ja.json` + `en.json` の `"nav"` セクションに同キー追加 → `navKey="nav.xxx"` で参照。
ページ右上ボタンは必ず `headerAction` プロップ経由（`position: fixed` で直接配置禁止）。

---

## i18n ハードコード検出（ESLint 自動強制）

JSX / TS(X) 内の日本語ハードコードは ESLint ルール `local/no-japanese-literal`（ADR-027）が自動検出。
コミット前に自動ブロック（`--max-warnings=0`）。

```bash
cd frontend && npm run lint   # 新規違反が 0 件であること
```

DB 由来の値（ステータスコード等）は `// eslint-disable-next-line local/no-japanese-literal -- DB value` で除外可。

---

## CSS 変数 / ダークモード

新規 CSS 変数のうち**色トークン**は `:root` と `:root.force-dark` の**両方**に追加（片方のみ禁止）。
寸法・サイズ・スペーシング等の非色トークンは `tokens.css` の `:root` のみ（`force-dark` 不要）。

```bash
cd frontend && npm run check:all   # 全デザインシステムチェック一括実行
```

詳細: `docs/adr/ADR-067-design-token-enforcement.md`

---

## アイコン管理

全 UI アイコンは `frontend/src/constants/icons.tsx` から import。
`lucide-react` からの直接 import は ESLint が禁止。

追加手順: lucide-react で確認 → `constants/icons.tsx` に追加 → import → `aria-hidden="true"` 付与。
スコープ外: `BadgesPage.tsx` のユーザー定義絵文字、`lp/src/` 以下

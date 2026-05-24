# frontend/CLAUDE.md

`frontend/` 配下の作業時のみ適用。プロジェクト全体ルールは `/CLAUDE.md` を参照。

---

## PageLayout ルール（全ページ必須）

ページタイトル・サブタイトルは必ず `<PageLayout navKey="nav.xxx">` 経由。raw `<h2>` は ESLint が自動ブロック。違反は CI で PR マージ不可。

```tsx
// ❌ 禁止（ESLint エラー）
<h2>{t("nav.leadChat")}</h2>

// ✅ 正しい
<PageLayout navKey="nav.leadChat" subtitleKey="inbox.subtitle">
  {/* コンテンツ */}
</PageLayout>
```

新規ページ: ja.json + en.json の `"nav"` セクションに同キー追加 → `navKey="nav.xxx"` で参照。

---

## i18n ハードコード検出（セルフチェック）

フロントエンドのコードを変更した後、以下を実行してヒット 0 行であること:

```bash
git diff --name-only develop...HEAD -- 'frontend/src/**/*.tsx' 'frontend/src/**/*.ts' \
  | grep -v 'locales/' \
  | xargs -I{} grep -nE '[ぁ-んァ-ヶ一-龯]' {} 2>/dev/null
```

コメント内の日本語は OK。JSX / 文字列リテラル内は必ず `t()` 経由にすること。

---

## CSS 変数 / ダークモード

詳細ルールは ESLint と `npm run check:all` が自動強制する。
新規 CSS 変数を追加した場合は **必ず** `:root` と `:root.force-dark` の両方に追加すること。

```css
/* ✅ 正しい */
:root { --new-color: #xxx; }
:root.force-dark { --new-color: #yyy; }
```

ローカル確認: `cd frontend && npm run check:all`

---

## アイコン管理

すべての UI アイコンは `frontend/src/constants/icons.tsx` から import する。
`lucide-react` からの直接 import は ESLint が禁止する。

追加手順: lucide-react で確認 → `constants/icons.tsx` に追加 → import → `aria-hidden="true"` 付与。
スコープ外: `BadgesPage.tsx` のユーザー定義絵文字、`lp/src/` 以下

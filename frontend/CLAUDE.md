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

新規ページ: ja.json + en.json の `"nav"` セクションに同キー追加 → `navKey="nav.xxx"` で参照。サブタイトルは `subtitleKey="xxx.subtitle"` で渡す（`.page-subtitle` クラスを直接 JSX に書かないこと・インラインスタイル禁止）。ページ右上ボタンは必ず `headerAction` プロップ経由（`position: fixed` で直接配置すると `.avatar-btn` と同座標に重なり不可視になる。`check:css-fixed-position` で自動ブロック）。

---

## i18n ハードコード検出（ESLint 自動強制）

JSX / TS(X) 内の日本語ハードコードは ESLint ルール `local/no-japanese-literal`（ADR-027）が自動検出。
`lint-staged` により **コミット前に自動ブロック**（`--max-warnings=0`）。

```bash
cd frontend && npm run lint   # 新規違反が 0 件であること
```

コメント内の日本語は OK。JSX / 文字列リテラル内は必ず `t()` 経由にすること。
DB 由来の値（ステータスコード・カテゴリキー等）は `// eslint-disable-next-line local/no-japanese-literal -- DB value` でコメント付き除外可。

---

## CSS 変数 / ダークモード

新規 CSS 変数のうち**色トークン**は必ず `:root` と `:root.force-dark` の両方に追加（片方のみ禁止）。
寸法・サイズ・スペーシング等の非色トークンは `tokens.css` の `:root` のみに追加（`force-dark` 不要）。
詳細: `docs/adr/ADR-067-design-token-enforcement.md`。ローカル確認: `cd frontend && npm run check:all`

**初めて触る場合**: `docs/onboarding/design-system.md`（5分）を先に読む。

## CSS 詳細度（stylelint 自動検出）

子孫セレクタ（例: `.page-header-actions .btn-ghost`）は詳細度 (0,2,0) で単純クラス (0,1,0) より高い。
コンテナ側で `font-size` 等を変更しても子孫セレクタに上書きされる。
CSS プロパティを変更する際は対象クラスの子孫セレクタを必ず grep で確認すること。

意図的なスコープ限定には `/* stylelint-disable-next-line no-descending-specificity -- intentional */` を付与。
確認: `cd frontend && npm run check:stylelint`

---

## アイコン管理

すべての UI アイコンは `frontend/src/constants/icons.tsx` から import する。
`lucide-react` からの直接 import は ESLint が禁止する。

追加手順: lucide-react で確認 → `constants/icons.tsx` に追加 → import → `aria-hidden="true"` 付与。
スコープ外: `BadgesPage.tsx` のユーザー定義絵文字、`lp/src/` 以下

---

## E2E テスト更新ルール

**UI 文字列・ナビゲーション・コンポーネント構造を変更したら `frontend/tests-e2e/` の該当 spec を同一 PR で更新すること。**

対象例:
- `ja.json` の `"nav.*"` キー変更 → scene1-dashboard.spec.ts のナビ検証を更新
- 新機能追加（自動選択・バッジ挙動変更等） → 関連 scene の mock・assertion を更新
- コンポーネントの CSS クラス名変更 → セレクタを更新

確認: `cd frontend && npx playwright test --project=chromium`

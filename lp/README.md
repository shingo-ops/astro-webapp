# SalesAnchor LP

salesanchor.jp の LP（ランディングページ）+ Privacy / Terms / Data Deletion の 4 ページ静的サイト。

| 項目 | 内容 |
|---|---|
| スタック | Astro 4 + Tailwind CSS 3 + Tailwind Typography |
| 配置 | salesanchor リポジトリ同居の `lp/` 配下 |
| デプロイ | `lp/dist/` を VPS の `/var/www/salesanchor/` に rsync（GitHub Actions） |
| nginx | 既存 `nginx/nginx.conf` の `salesanchor.jp` server block で配信中 |

## ローカル開発

```
cd lp
npm install
npm run dev
```

ブラウザで http://localhost:4321 を開く。

## ビルド

```
cd lp
npm run build
```

成果物: `lp/dist/`

## ディレクトリ

```
lp/
├── package.json
├── astro.config.mjs
├── tailwind.config.mjs
├── tsconfig.json
├── public/
│   ├── favicon.svg
│   └── og-image.png      # 1200×630, ロゴ + キャッチコピー（要差し替え）
└── src/
    ├── styles/global.css   # Noto Sans JP self-host + Tailwind
    ├── layouts/
    │   └── BaseLayout.astro   # title/description/canonical/noindex/ogImage props
    ├── components/
    │   ├── Header.astro       # ロゴ + ナビ + ログインボタン
    │   └── Footer.astro       # 運営者情報 + リーガルリンク
    └── pages/
        ├── index.astro        # LP 本体（A1〜A6）
        ├── privacy.astro      # プライバシーポリシー（A8）
        ├── terms.astro        # 利用規約（A9）
        └── data-deletion.astro # データ削除（A10）
```

## 本文の埋め方

各ページの `【...】` プレースホルダを実コンテンツに差し替えてください。長文ページ（privacy / terms / data-deletion）は `<article class="prose prose-slate ...">` でラップ済みのため、`<h1>` `<h2>` `<p>` `<ul>` をそのまま書けば Tailwind Typography が自動整形します。

参考素材:
- `privacy_policy_v12.docx` v1.2 → `pages/privacy.astro`
- `terms_of_service.docx` v1.0 → `pages/terms.astro`
- `data_deletion_instructions.docx` v1.0（ユーザー向け簡略版） → `pages/data-deletion.astro`
- `use_case_descriptions.docx` v1.0（運営者情報） → `pages/index.astro`

## デザイントークン

`tailwind.config.mjs` で定義:
- カラー: `brand-50/100/500/600/700/900`（青系、`#3b82f6` 起点）
- フォント: Noto Sans JP（self-host via `@fontsource`）
- 最大幅: `max-w-reading` (65ch、長文向け)

## 関連ドキュメント

- `docs/PHASE5_DOMAIN_CUTOVER_RUNBOOK.md` — Phase 5 ドメイン切替手順
- Meta App Review チェックリスト v1.1（Google Doc）— セクション A 参照

## 本番デプロイ

GitHub Actions の `deploy.yml` で `lp/dist/*` を VPS の `/var/www/salesanchor/` に rsync する追加ジョブを実装予定（次の PR）。それまでは手動デプロイ:

```
cd lp
npm run build
rsync -avz --delete dist/ ubuntu@49.212.137.46:/var/www/salesanchor/
```

`docker compose up -d --no-deps nginx` で反映。

## TODO

- [ ] og-image.png 作成（1200×630, ロゴ + キャッチコピー）
- [ ] 4 ページの本文を `【...】` プレースホルダから実コンテンツに差し替え
- [ ] Lighthouse でパフォーマンス・アクセシビリティ・SEO を 90 点以上に
- [ ] GitHub Actions deploy ジョブ追加
- [ ] sitemap.xml / robots.txt（必要なら `@astrojs/sitemap` integration）

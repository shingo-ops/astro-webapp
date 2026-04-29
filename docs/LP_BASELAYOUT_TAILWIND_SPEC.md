# LP BaseLayout / Tailwind 仕様書

| 項目 | 内容 |
|------|------|
| 起草日 | 2026-04-29 |
| 対象 | salesanchor リポジトリ同居の LP 4 ページ（index / privacy / terms / data-deletion） |
| 採用スタック | Astro 4.x + Tailwind CSS 3.x + Tailwind Typography プラグイン |
| 配置 | `salesanchor/lp/` 配下 |
| ステータス | 仕様確定待ち（scaffold 着手前） |

---

## 0. 前提

- **採用スタック**: Astro + Tailwind CSS 3 + Tailwind Typography プラグイン
- **配置**: `salesanchor/lp/` 配下
- **scaffold（プロジェクト雛形作成）**: まだ未着手。本仕様確定 → 私（Hikky-dev）が scaffold 一括投入 → しんごさんが各ページ本文を記述、という流れ

---

## 1. BaseLayout.astro の Props 仕様

```ts
export interface Props {
  title: string;              // <title> + og:title。"プライバシーポリシー" など。
                              // BaseLayout 側で " | SalesAnchor" を自動付与
  description: string;        // meta description + og:description (~120字推奨)
  canonical?: string;         // canonical URL。省略時は現在のパスから自動生成
  noindex?: boolean;          // 検索エンジン除外（default: false）
  ogImage?: string;           // OG 画像。省略時 /og-image.png
  bodyClass?: string;         // <body> 追加 class（特殊な背景色など、稀に使う）
}
```

**しんごさんが書く側のイメージ:**

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
---
<BaseLayout
  title="プライバシーポリシー"
  description="SalesAnchor が取り扱う個人情報の利用目的・保管・削除方針を定めたポリシーです。"
>
  <!-- ここに本文 -->
</BaseLayout>
```

→ `<title>プライバシーポリシー | SalesAnchor</title>` が自動で出力されます。

---

## 2. Header / Footer は **BaseLayout に組み込み済み**

各ページで個別 import は **不要**。BaseLayout が責任を持つので、しんごさんは本文だけに集中できます。

```astro
<!-- BaseLayout.astro 内部（イメージ）-->
<body>
  <Header />        <!-- ロゴ + ナビ（Privacy / Terms / Data Deletion / Login）-->
  <main>
    <slot />        <!-- ← ここに各ページの中身が入る -->
  </main>
  <Footer />        <!-- 運営者情報 + リーガルリンク 3 点 + コピーライト -->
</body>
```

---

## 3. 本文を包む要素

- **`<main>` は BaseLayout が提供**します（A11y のランドマーク役割）
- **ページ側は `<article>` か `<section>` から書き始める**（セマンティック整合）
- 長文（privacy / terms / data-deletion）は `<article class="prose prose-slate max-w-3xl mx-auto px-4 py-12">` で書けば Tailwind Typography が見出し / 段落 / リスト / コードを綺麗に整形します
- LP（index）は構造が複雑なので独自に `<section>` を積んでいく形

### 長文ページのテンプレ

```astro
<BaseLayout title="プライバシーポリシー" description="...">
  <article class="prose prose-slate max-w-3xl mx-auto px-4 py-12">
    <h1>プライバシーポリシー</h1>
    <p>制定日: 2026-04-23</p>

    <h2>1. 事業者情報</h2>
    <p>...</p>

    <h2>2. 取得する個人情報</h2>
    <ul>
      <li>...</li>
    </ul>
  </article>
</BaseLayout>
```

→ `prose` 内の `h1/h2/h3/p/ul/ol/blockquote` は自動で整形（フォントサイズ / 行間 / 余白）。手動で Tailwind class を当てる必要はありません。

### LP（index）のテンプレ

```astro
<BaseLayout title="TCG輸出業者向け CRM" description="...">
  <section class="bg-brand-50 py-20">
    <div class="max-w-5xl mx-auto px-4 text-center">
      <h1 class="text-4xl md:text-6xl font-bold text-brand-900">
        SalesAnchor
      </h1>
      <p class="mt-4 text-xl text-gray-700">
        TCG 輸出業者のための統合 CRM
      </p>
    </div>
  </section>

  <section class="py-16">
    <!-- 4本柱 -->
  </section>
</BaseLayout>
```

---

## 4. Tailwind config 仕様

### 4-1. カラーパレット

| トークン | 値 | 用途 |
|---|---|---|
| `brand-50` | `#eff6ff` | hero 背景・薄い帯 |
| `brand-500` | `#3b82f6` | primary ボタン |
| `brand-600` | `#2563eb` | primary ボタン hover |
| `brand-900` | `#1e3a8a` | 見出し |
| `gray-*` | Tailwind デフォルト | 本文・borders |

`bg-brand-50`, `text-brand-900`, `bg-brand-500 hover:bg-brand-600` のように使えます。

### 4-2. フォント

```
font-family: "Noto Sans JP", Hiragino Sans, "Yu Gothic", system-ui, sans-serif
```

- 日本語: Noto Sans JP（CDN ではなく self-host で FCP 短縮、scaffold 時に組み込み）
- 数字・英字も同フォントで統一

### 4-3. ブレークポイント（Tailwind デフォルト）

| プレフィックス | 幅 | 用途 |
|---|---|---|
| なし | 〜639px | スマホ（mobile-first） |
| `sm:` | 640px〜 | 大きめスマホ |
| `md:` | 768px〜 | タブレット |
| `lg:` | 1024px〜 | PC |
| `xl:` | 1280px〜 | 大型 PC |

→ しんごさんは **モバイルファースト**で書いて、PC 拡張は `md:` `lg:` で。

### 4-4. Typography プラグイン

- `prose` 基本クラス + `prose-slate`（落ち着いた色味）+ `prose-lg`（読みやすい大きさ）が指定できる
- `max-w-prose` で 65ch 制限（読みやすい横幅）

### 4-5. tailwind.config.mjs（scaffold で生成予定）

```js
import typography from '@tailwindcss/typography';

export default {
  content: ['./src/**/*.{astro,html,js,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          900: '#1e3a8a',
        },
      },
      fontFamily: {
        sans: ['"Noto Sans JP"', 'Hiragino Sans', '"Yu Gothic"', 'system-ui', 'sans-serif'],
      },
      maxWidth: {
        reading: '65ch',
      },
    },
  },
  plugins: [typography],
};
```

---

## 5. ディレクトリと配置

```
salesanchor/
├── lp/
│   ├── package.json
│   ├── astro.config.mjs
│   ├── tailwind.config.mjs
│   ├── public/
│   │   ├── favicon.ico
│   │   ├── og-image.png            ← 1200×630px、SalesAnchor ロゴ + キャッチコピー
│   │   └── fonts/                  ← Noto Sans JP self-host
│   └── src/
│       ├── layouts/
│       │   └── BaseLayout.astro    ← Hikky-dev が scaffold で作成
│       ├── components/
│       │   ├── Header.astro        ← Hikky-dev が scaffold で作成
│       │   └── Footer.astro        ← Hikky-dev が scaffold で作成
│       └── pages/
│           ├── index.astro         ← しんごさんが本文記述
│           ├── privacy.astro       ← しんごさんが本文記述
│           ├── terms.astro         ← しんごさんが本文記述
│           └── data-deletion.astro ← しんごさんが本文記述
```

---

## 6. 進め方の提案

私（Hikky-dev）の側で scaffold を一括投入できます:

- `lp/` ディレクトリ作成
- Astro + Tailwind + Typography プラグインのセットアップ
- BaseLayout / Header / Footer の実装
- ページ 4 つを「**プレースホルダ**」付きで生成（しんごさんが本文を埋める形）
- README 追加（`npm run dev` でローカル確認可能）

→ scaffold 完了後にしんごさんが各ページの本文を書き、Hikky-dev 側で Lighthouse / レスポンシブ / SEO を最終チェック、という分担がスムーズです。

---

## 7. 確認したい点（しんごさん）

| 項目 | 内容 |
|---|---|
| **A** | scaffold を Hikky-dev が即投入してよいですか？（30〜60 分で完成 → ブランチ push） |
| **B** | カラーパレット: 上記の青系（`brand-500 #3b82f6`）でよいですか？それとも salesanchor.jp 既存 LP と統一したい色がありますか？（既存 LP の `www/salesanchor/index.html` を見て合わせることも可能） |
| **C** | og-image.png はしんごさん側でデザインですか？（暫定でロゴ + テキストの簡易版を Hikky-dev 側で作ることも可） |
| **D** | しんごさんが書く本文は markdown 風で書いてもらって Hikky-dev が astro へ反映、でも OK ですか？それとも astro 直書きしますか？ |

---

## 8. メモ

- Meta App Review チェックリスト v1.1 セクション A（A1〜A12）と整合
- `data-deletion.astro` は **ユーザー向け簡略版**（Meta レビュアーが見る公開ページ）。signed_request を受け取る POST エンドポイントは別途 `backend/app/routers/meta.py` で実装（B1〜B7）
- LP 4 ページの実装は **docx 4 点（privacy_policy_v12.docx 等）の共有後** に着手する（本文素材として）

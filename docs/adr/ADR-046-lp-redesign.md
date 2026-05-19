# ADR-046: Landing Page Redesign — English-only, Professional SaaS Style

- **日付**: 2026-05-19
- **ステータス**: Proposed
- **起案者**: Web Claude (Planner) via Shingo
- **対象範囲**: `lp/`
- **関連 ADR**: ADR-013（ロゴ統一、LP は当時 Scope外）、ADR-022（アプリUI 刷新、LP は Scope外）、ADR-027（アプリ i18n、LP は対象外）

---

## 1. 背景

現行 LP（`lp/`、Astro 4.16 + Tailwind 3.4 構成）は Meta App Review 提出という当面の主目的に対し、以下3点で最適化されていない。

1. **言語設計の不統一**
   - `lp/src/pages/index.astro`: 日本語 100%
   - `lp/src/pages/privacy.astro` / `data-deletion.astro`: 日英バイリンガル（日本語メイン＋`<small>` で英訳）
   - `lp/src/pages/deletion-status.astro`: 日本語 + JS インライン内に英語ラベル混在

2. **ビジュアル水準が現代の B2B SaaS LP に達していない**
   - Tailwind の基本トークン + 独自 `brand-*` のみで構成。UI ライブラリ未導入
   - 現代の参照群（Linear / Attio / Resend / Cron 等）との差が大きい

3. **Meta App Review 担当者（米国 SF、英語ネイティブ）にとって読解負荷が高い**
   - 実体性訴求（実在企業の運営、本気の SaaS であること）の伝達が弱い

なお `lp/src/pages/privacy.astro` v1.3 (2026-04-30, 全 453 行) は APPI / Meta Platform Terms 準拠の 13 章構成で法的網羅性が高い。**情報資産としての維持価値が高いため、内容は維持・英訳を主・日本語版を削除する反転刷新**とする（白紙化しない）。

---

## 2. 決定（What）

LP 全 5 ページを **英語完全化 + プロフェッショナル SaaS スタイル**に刷新する。

### 2-1. 対象ファイル

| ファイル | 現状行数 | 現状言語 |
|---|---|---|
| `lp/src/pages/index.astro` | 174 | 日本語 100% |
| `lp/src/pages/privacy.astro` | 453 | 日英バイリンガル |
| `lp/src/pages/data-deletion.astro` | 103 | 日英バイリンガル |
| `lp/src/pages/deletion-status.astro` | 169 | 日本語 + JS 英語混在 |
| `lp/src/pages/terms.astro` | 未調査 | 未調査 |

加えて、共通レイアウト・コンポーネント:
- `lp/src/layouts/BaseLayout.astro`（OG / Twitter / facebook-domain-verification メタタグ含む）
- `lp/src/components/Header.astro`
- `lp/src/components/Footer.astro`

### 2-2. デザイン方向性

**参照軸**: Linear / Attio / Resend / Cron 系
- ミニマル、余白重視、タイポグラフィで魅せる
- ダーク基調または明るめミニマル（具体トーンは Generator 判断）
- プロダクトショット中心（あれば）、装飾的イラスト排除
- 英文プロフェッショナルフォント（例: Inter）を採用、`@fontsource/noto-sans-jp` は削除

**UI ライブラリ方針**: 既存通り Tailwind 3.4 + `@tailwindcss/typography` + 独自 `brand-*` トークンのみで完結。shadcn / Radix / daisyUI 等は導入しない。

### 2-3. コアメッセージング

- **Hero headline**: `"The CRM built for cross-border TCG exporters."`
- **Subline**: Generator が hero headline と整合するよう起案（30-50 語目安）
- **Primary CTA**: `"Book a demo"`（mailto:support@salesanchor.jp または将来の予約フォーム導線）
- **Secondary CTA**: `"Sign in"` → `app.salesanchor.jp`

### 2-4. index.astro のセクション構成（現行 A1-A6 を踏襲、内容は完全リライト）

| # | 現行 | 刷新後の意図 |
|---|---|---|
| A1 | ヒーロー | 同上。新 headline / subline / CTA で刷新 |
| A2 | 想定ユーザー | "Who it's for" — TCG B2B 輸出業者の具体ペルソナ |
| A3 | 主要機能 4 カード | "Features" — Unified inbox / Structured catalog / Automated invoicing / AI insights |
| A4 | Meta データ利用方針 | "How we use Meta data" — Meta 審査必須セクションとして英語で再記載 |
| A5 | データ保管・セキュリティ | "Security & infrastructure" — TLS 1.3 / Fernet / PostgreSQL RLS |
| A6 | 運営者情報 | "About the operator" — HIGH LIFE JPN 情報（住所・代表者・連絡先） |

セクション順序や追加削除は Generator の判断に委ねる。ただし A4（Meta データ利用方針）と A6（運営者情報）は Meta 審査必須要素として**省略不可**。

---

## 3. Why（事業上の目的）

| # | 目的 | 優先度 |
|---|---|---|
| 1 | Meta App Review 担当者への実体性訴求（米国 SF・英語ネイティブ対応） | 最優先 |
| 2 | 将来の海外 B2B 顧客（TCG 業者）への営業ツール兼用 | 中 |
| 3 | コーポレートサイトとしての最低限の体裁（Footer の会社情報で必要十分） | 低 |

(1) は今回の発火点。(2) は同じデザインに `"Book a demo"` CTA を置くことで追加工数ゼロで兼用可能、と判断。

設計の不統一（背景 §1-1）を根本解消するもっともシンプルな手段が「完全英語化」である。バイリンガル維持は短期的に整合性コストが膨らみ続けるため、**今回は完全英語化を選択し、日本語版の再導入は将来の別 ADR に委ねる**。

---

## 4. Scope 外

以下は本 ADR の対象外。混入した場合、Reviewer は Scope creep として `request-changes` すべき。

- **Tailwind v4 移行**: v3.4 のまま維持。v4 移行は別 ADR で検討
- **アプリ本体（`frontend/`）のデザイン変更**: ADR-022 の Scope
- **アプリ本体の i18n 対応**: ADR-027 の Scope
- **日本語版 LP の再導入**: 将来別 ADR
- **新規 Astro / UI コンポーネントライブラリの導入**: shadcn / Radix / daisyUI 等は不要
- **バックエンド API 変更**: Data Deletion Callback の URL・レスポンス形式・HMAC 検証ロジックは完全維持
- **ドメイン構成変更**: `salesanchor.jp`（LP）/ `app.salesanchor.jp`（アプリ）/ `api.salesanchor.jp`（API）の現行構成を維持
- **`facebook-domain-verification` メタタグの削除**: 維持必須

---

## 5. 事業上の制約（刷新後も維持必須）

### 5-1. 会社情報の表示

以下は刷新後も全 LP 上で英語表記により維持される必要がある。

| 項目 | 値 | 現状参照 |
|---|---|---|
| 運営者 | HIGH LIFE JPN | `index.astro:152`, `privacy.astro:42-44`, `Footer.astro:24-26`, `data-deletion.astro:97` |
| 代表者 | Shingo Tanizawa | 同上 |
| 住所（英語） | 2F, Nishi-Shinjuku Mizuma Building, 3-3-13 Nishi-Shinjuku, Shinjuku-ku, Tokyo 160-0023, Japan | `privacy.astro:48` |
| 連絡先 | support@salesanchor.jp | `privacy.astro:423-429`, `Footer.astro:24-26` |

住所は `index.astro:156` と `privacy.astro:47` に日本語で重複ハードコードされているため、英語版に一本化する。

### 5-2. privacy.astro v1.3 の章構成と法的網羅性

- APPI（個人情報保護法）準拠の章立てを維持
- Meta Platform Terms 準拠の章立てを維持
- 13 章構成を維持
- バージョン番号と最終更新日を更新（v1.4 / 2026-MM-DD）
- **内容（言及されている法令・データ種別・保持期間・削除手順）は実質的に変更しない**
- 日本語版を削除し、現状の英訳を主にし、英語の質を向上させる

### 5-3. Data Deletion 連携の機能維持

| ファイル | 維持すべき機能 |
|---|---|
| `data-deletion.astro` | Meta 経由（Facebook 設定から削除）とメール直接の 2 方式の説明、削除タイムライン、削除できないデータの明記 |
| `deletion-status.astro` | `?code=DEL-YYYYMMDD-xxxx` クエリパラメータ受け取り、`https://api.salesanchor.jp/api/v1/meta/deletion-status` への fetch ロジック、ステータス表示（received / processing / completed）、`noindex=true` |
| `BaseLayout.astro` | `facebook-domain-verification` メタタグ、OG / Twitter メタタグ（英語版に整合） |

### 5-4. ナビゲーション整合性

- Header / Footer のリンクが全 5 ページ間で破綻しないこと
- `app.salesanchor.jp` への "Sign in" 導線を維持

---

## 6. 検証要件（Reviewer / Evaluator へ）

### Evaluator method

このセクションは Generator が PR 本文に転記する想定:

- [x] Layer 1: Playwright (default) — 全 5 ページ表示確認、`deletion-status.astro` の `?code=...` フロー、Header/Footer ナビ整合性
- [ ] Layer 2: Claude in Chrome — 不要（ログイン関与なし）
- [ ] Skip — 該当しない（UI 全面刷新のため必須）

### 追加検証

- Meta App Review 提出前に、しんごさん（人間）が刷新後 `privacy.astro` を法務観点で最終レビューすること（自動化困難）
- `facebook-domain-verification` メタタグの値が現行から変わっていないこと（Reviewer 確認）

---

## 7. 3 点セット要件（ADR-025）の適用判断

ADR-025 は「外部システムと状態を共有する新機能（OAuth / Webhook / Cron 等）」を対象とする。

本 ADR は**新規の外部連携を追加しない**（既存の Data Deletion Callback 機能の表示層を刷新するのみ）。したがって 3 点セット要件（機能本体 / 状態検証スクリプト / 監視・通知）は本 ADR の対象外と判断する。

ただし、§5-3 に既存連携機能の維持要件を明示し、Evaluator の Playwright で動作確認することで、回帰検知の責務を果たす。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| 英語デフォルト＋日本語トグル維持（i18next 等） | ❌ 却下。設計の不統一を根本解消できず、ADR-027（アプリ i18n）と Scope が混線する |
| index.astro のみ先行刷新 | ❌ 却下。Meta 審査担当は privacy / data-deletion も必ず読むため、ページ間のデザイン分裂が生じる |
| privacy.astro v1.3 を白紙化して書き直し | ❌ 却下。法的網羅性の毀損リスクが大きい |
| 本 ADR（5 ページ完全英語化＋デザイン刷新、UI ライブラリは追加せず） | ✅ 採用 |

---

## 9. 未決事項（Generator 判断に委ねる）

以下は本 ADR では決めず、Generator の判断に委ねる:

- ダーク基調 / ライト基調 / 両対応（prefers-color-scheme）の選択
- 具体的なフォント選定（Inter / Geist / IBM Plex Sans / その他）
- セクション順序の微調整、追加削除（A4 / A6 は省略不可）
- PR の段階分割（1 PR で 5 ページ刷新、またはページ単位の複数 PR、いずれも可）
- プロダクトショット画像の生成有無（必須ではない）
- "Book a demo" CTA の遷移先（mailto: / 外部予約フォーム / 空のアンカー、いずれも可）

---

## 10. 起案者の認知限界（しんごさんへの注記）

本 ADR は Web Claude（Plan モード相当）が起案。以下を明記:

- `terms.astro` の現状は未調査。Generator が PR 起こす際にあわせて読むこと
- `tailwind.config.mjs` の現状トークン（`brand-*` の具体値）は未調査。Generator が現状を読んで判断
- 現状の OG / Twitter メタタグ画像 URL は未確認。英語化に伴い OG 画像の差し替えが必要かは Generator 判断

---

## 変更履歴

- 2026-05-19: 初版起案（Web Claude via Shingo）

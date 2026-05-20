# ADR-054: LP Full Restructure — HubSpot-Style Layout + frontend Brand Color Unification

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `lp/src/pages/index.astro` / `lp/tailwind.config.mjs` (必要に応じ) / `lp/src/components/Header.astro`
- **関連 ADR**: ADR-046 / ADR-047 / ADR-049 (LP 段階的整備、本 ADR で構造を全面差し替え)、ADR-052 (取り下げ、本 ADR で吸収)

---

## 1. 背景

ADR-046 → ADR-047 → ADR-049 で omni.chat 系構造の LP を構築したが、しんごさんから **HubSpot 風レイアウト**への全面差し替え方針が提示された。

加えて、frontend アプリのブランドカラー実態を偵察した結果:

| トークン | 実態 | LP 現状 | 差分 |
|---|---|---|---|
| Primary Blue | `#1877F2` | brand-500 一致 | ✅ |
| Hover Blue | `#166FE5` | brand-600 一致 | ✅ |
| Sidebar 背景 | 白 (`#ffffff`) | — | LP 側で再現 |
| Page 背景 | `#f5f7fa` | bg-white | 統一 |
| Text Primary | `#1a202c` | text-gray-900 | 統一 |
| Font | Inter | Inter | ✅ |
| **Dark Navy `#1a365d`** | **未使用** | bg-blue-900 ハードコード | **削除** |

偵察結果の `--nav-brand-bg: #1a365d` は frontend CSS に定義はあるが **アプリ UI で実使用されていない**。LP 側でも採用しない。Footer ダーク背景は Tailwind の `gray-900` (`#1f1f1f`) を採用する。

**参照プロトタイプ**: `docs/proposals/adr-054-prototype.html`（Web Claude が起案した HubSpot 風 HTML プロトタイプ。Generator はこれを参照して Astro 実装を行う）

---

## 2. 決定（What）

### 2-1. index.astro の全面書き換え

セクション構成:

| # | セクション | 内容 |
|---|---|---|
| **S1** | Hero (split) | 左: ヘッドライン + サブライン / 右: 資料請求フォーム |
| **S2** | Feature tabs | 5 タブ切替: Sales / Marketing / Customer / Data / AI |
| **S3** | Footer (dark) | ダーク背景、リンク、会社情報 |

S4-S6 (Ecosystem diagram / Metrics band / Why us 4-column) は **削除**。HubSpot 系では機能タブが主軸。

### 2-2. Hero (S1) 詳細

**左カラム**:
- ヘッドライン: `"The CRM built for cross-border TCG exporters."` (ADR-046 継承)
- サブライン (ADR-047 3 拍子継承):
  - "Unify every channel, every customer, every deal — in one place."
  - "Control your records and workflows with structure."
  - "Analyze what's working and find your next move."

**右カラム** (form-card):
- 見出し: `"Request a brochure"`
- フィールド:
  - Name (required)
  - Company name (required)
  - Email (required)
  - Phone (optional)
  - Company size (select: 1-10 / 11-50 / 51-200 / 201-500 / 501+)
- 送信ボタン: `"Send request →"`
- 注記: `"Our team will follow up shortly."`
- **送信方式**: mailto (`mailto:support@salesanchor.jp?subject=Brochure%20request`)。Astro の form は body にフィールド値を query string で埋め込む簡易実装

**バッジ / 電話番号は配置しない**。

### 2-3. Feature tabs (S2)

5 タブ:

| Tab id | Heading | 機能箇条書き例 |
|---|---|---|
| sales | "Sales enablement" | Pipeline / customer record / email + call unification / AI priority scoring / sales report / team goal tracking |
| marketing | "Marketing automation" | Lead capture form / email campaigns / social integration / AI content / segmentation / marketing report |
| customer | "Customer experience" | Support ticketing / chatbot / NPS / interaction history / SLA |
| data | "Unified data" | CRM database / custom properties / API integration / data hygiene / segmentation / export-import |
| ai | "AI automation" | Conversation summary / auto follow-up / next best action / lead scoring / sales forecast / workflow automation |

各タブ:
- 見出し
- 説明文 (1-2 文)
- 機能箇条書き 6 項目 (2 カラム grid)
- "Starter plan" や料金リンクは **削除** (β 段階、誇大広告回避)
- 右側に画像プレースホルダー (`bg-brand-50` 等) + アイコン + "Product screenshot — coming soon"

切替: vanilla JavaScript で `display: none/grid` を切り替え（外部ライブラリ追加禁止）。

### 2-4. Header

現状の `lp/src/components/Header.astro` を維持しつつ:
- ロゴ画像: 維持 (frontend と統一済)
- ナビゲーション: Privacy / Terms / Data Deletion / Sign in を維持
- 電話番号は **追加しない** (HubSpot プロトタイプの `0120-000-000` は採用しない)
- 背景: `#fcfcfa` または白

### 2-5. Footer (S3)

ダーク背景 (`bg-gray-900`) で以下を配置:
- 会社情報:
  - HIGH LIFE JPN
  - Representative: Shingo Tanizawa
  - 2F, Nishi-Shinjuku Mizuma Building, 3-3-13 Nishi-Shinjuku, Shinjuku-ku, Tokyo 160-0023, Japan
  - support@salesanchor.jp
- リンク: Privacy Policy / Terms / Data Deletion
- Copyright: `© 2026 HIGH LIFE JPN. All rights reserved.`

### 2-6. ブランドカラー方針

LP 側の Tailwind トークン (`brand-*`) はすでに frontend と一致しているため **変更不要**。`brand-navy` トークンの追加は **行わない** (frontend で未使用のため)。

ハードコードされた `bg-blue-900` 等があれば `bg-gray-900` または `bg-brand-700/800` に置換。

### 2-7. 他ページの不変

`privacy.astro` / `terms.astro` / `data-deletion.astro` / `deletion-status.astro` は **無変更**。

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | HubSpot 風の資料請求フォーム導線で B2B 商談化を促進 | 最優先 |
| 2 | frontend アプリとブランドカラー統一、ユーザ体験の一貫性 | 高 |
| 3 | omni.chat 系の補助セクション (S4-S6) を整理し、視覚的フォーカスを Hero + 機能タブに集中 | 中 |
| 4 | Meta App Review 担当への印象は「実在 SaaS の資料請求ページ」として強化 (副次効果) | 中 |

---

## 4. Scope 外

- バックエンド API 変更 (`api.salesanchor.jp` 配下不変)
- privacy / terms / data-deletion / deletion-status の内容変更
- アプリ本体 (`frontend/`) のデザイン変更
- 資料請求フォームの **本格的なバックエンド連携** (Formspree / Getform / 独自 API)。本 ADR は mailto のみ
- 電話番号、ISO 認証、顧客テスティモニアル、料金プラン表示
- 動画背景、製品実 UI スクショ撮影 (プレースホルダーで OK)
- Tailwind v4 移行
- Header の電話番号追加

---

## 5. 事業上の制約 (最重要)

### 5-1. 既存コピー資産の継承

ADR-046 ヘッドラインと ADR-047 3 拍子サブラインは **完全保持**。

### 5-2. Meta App Review 必須要素

- `facebook-domain-verification` メタタグ維持 (`BaseLayout.astro`)
- 会社情報 (HIGH LIFE JPN / 住所 / 連絡先) 維持
- Privacy / Data Deletion 導線維持

### 5-3. 言語

完全英語 (ADR-047 継承)。日本語化しない。

### 5-4. プレースホルダー禁止事項

S2 機能タブの右側画像枠は **空白オミット禁止** (ADR-049 §5-1 の学習継承):
- 背景色 (`bg-brand-50` 等) + アイコン (絵文字または SVG) + "Product screenshot — coming soon" テキストで配置

### 5-5. 誇大広告禁止

`"2024 Award"` / `"Best Sales Tool"` / `"使いやすさ No.1"` / `"成果実績 No.1"` バッジは **削除確定**。料金 (`月額2,000円〜` 等) も β 段階のため記載しない。

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright — Hero 表示 / フォーム描画 / 5 タブ切替動作 / Footer 表示 / レスポンシブ / mailto リンク生成
- [ ] Layer 2
- [ ] Skip

### Reviewer 追加観点 (機械的確認)

- [ ] `index.astro` に Hero (split) / Feature tabs (5 枚) / Footer の 3 構造があるか
- [ ] S4-S6 (Ecosystem diagram / Metrics band / Why us 4-column) が **完全削除** されているか
- [ ] `"2024 Award"` / `"Best Sales Tool"` / `"No.1"` / `月額` などのバッジ・料金文言が **混入していないか**
- [ ] フォーム送信が mailto 方式であるか (`<form action="mailto:..." ...>` 等)
- [ ] Header に電話番号が **追加されていないか**
- [ ] `bg-blue-900` / `#1a365d` のハードコード値が残っていないか
- [ ] Footer 背景が `bg-gray-900` か
- [ ] `facebook-domain-verification` メタタグ維持
- [ ] 既存ヘッドライン `"The CRM built for cross-border TCG exporters."` と 3 拍子サブライン継承

### 追加検証 (しんごさん)

- 本番反映後、ブランドカラーの統一感を確認
- フォーム送信動作を実際に試す (mailto がメーラーを起動するか)
- 5 タブ切替が JS で動作するか

---

## 7. 3 点セット要件

該当しない (外部システム新規連携なし、mailto はメール仕様)。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. ADR-047/049 の omni.chat 系構造を維持し、コピーだけ調整 | ❌ 却下。しんごさん方針転換 (HubSpot 風) |
| B. 日本語化 + 国内向け LP | ❌ 却下。Meta App Review 英語要件、しんごさん「英語維持」確定 |
| C. フォーム送信を Formspree など SaaS 連携 | ❌ 却下。Meta 提出を遅らせない、将来別 ADR |
| D. アプリと LP を 1 リポジトリ統合 | ❌ 却下。範囲外、長期検討 |
| **E. HubSpot 風 split Hero + 5 機能タブ + Footer (本案)** | ✅ 採用 |

---

## 9. 未決事項 (Generator 判断)

- フォーム要素の Astro 実装方法 (静的 form + mailto / island で動的)
- 5 タブ切替の実装 (vanilla JS / Astro client:load / Alpine 等)。**外部ライブラリ追加禁止**、vanilla JS 推奨
- 機能タブの右側画像プレースホルダーのアイコン具体 (絵文字 vs SVG)
- Hero 右フォームの max-width / レスポンシブ縦並び切替の breakpoint
- mailto body の改行エンコード方式

---

## 10. 起案者の認知限界

- HubSpot プロトタイプ HTML はしんごさんが提示したものを参照。実 HubSpot サイトと一字一句一致は確認していない
- frontend アプリの実 UI スクショ (ダッシュボード画面) はしんごさんから提供されたものを参照。サイドバー白背景 / Primary Blue ハイライト / カード白 + shadow の構造を確認
- ADR-052 (Header h-16 + favicon) は本 ADR で吸収。PR #414 はすでに MERGED 済み（develop に反映済み）
- 本 ADR は ADR-053 の pipeline バグ修正適用 **前** に push される可能性あり。その場合 Reviewer 自動 APPROVE が誤判定される可能性。手動 Reviewer / Evaluator 起動が必要

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

# ADR-057: LP Premium Restyle — HubSpot Construct + Dark Navy Hero + Hub Card Grid

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `lp/src/pages/index.astro` / `lp/src/layouts/BaseLayout.astro` (font 追加のみ) / `lp/tailwind.config.mjs` (確認のみ)
- **関連 ADR**: ADR-054 (LP HubSpot 風差し替え、本 ADR で品質向上)、ADR-049 (S3-S6 削除済み)

---

## 1. 背景

ADR-054 で salesanchor.jp を HubSpot 風レイアウトに差し替え本番反映済み。しかし、しんごさんから「チープに見える」フィードバック。具体的に判明した問題:

| 項目 | 現状 (ADR-054 実装) | 問題 |
|---|---|---|
| Hero 背景 | bg-gray-50 (薄グレー) | インパクト不足 |
| H1 フォント | Inter bold のみ | 単調 |
| H1 コピー | 機能説明的 ("The CRM built for cross-border TCG exporters.") | 引き込まれない |
| フォームカード影 | shadow-sm (ほぼなし) | 浮き上がらない |
| 機能セクション | タブ切替式 5 枚 | クリックしないと内容が見えない |
| ブランドカラー使用 | brand-500 が CTA のみ | 全体的に白・グレー基調で単調 |
| Closing CTA | なし | LP のクライマックスが無い |
| Footer | 3 列、シンプル | 品質感に欠ける |

しんごさんから HubSpot 英語版 (hubspot.com) の構造・フレーズ・見せ方を Sales Anchor ブランドカラーで応用した完全な実装案 HTML が提供された。本 ADR はそれを Astro/Tailwind 統合する。

---

## 2. 決定（What）

### 2-1. セクション構成の刷新

| # | セクション | 内容 | 旧 ADR-054 との差分 |
|---|---|---|---|
| **S1** | Hero (Dark Navy + Blue Glow) | 左: eyebrow + H1 (serif + italic accent) + desc + 3 badges / 右: フォーム (深い影) | 背景刷新、H1 構文変更、badges 追加 |
| **S2** | Problem Band | 3 課題カード ("Disconnected tools" / "Cross-border complexity" / "Small teams, hundreds of deals") | **新規追加** |
| **S3** | Hub Card Grid | 3×2 グリッド: Sales / Marketing / Customer / Data / AI / Catalog & Invoicing | タブ切替 → 全可視 Hub カード |
| **S4** | AI Split Section | 左: AI agents 3 step / 右: ロボット icon visual | **新規追加** |
| **S5** | Closing CTA | ダーク背景 + 大型 H2 + 2 ボタン (Request brochure / Sign in) | **新規追加** |
| **S6** | Footer (3 col, premium) | ロゴ + ブランド文 / Operator / Legal | ADR-054 の Footer 構造を品質向上 |

### 2-2. H1 コピーの方針

HubSpot 構文応用:

```
The game changer
isn't your spreadsheet.
It's context.  ← italic + brand blue
```

ADR-046 で確定した `"The CRM built for cross-border TCG exporters."` は **descriptor として残す**（H1 ではなく、Hero desc やメタタグで利用継続）。

### 2-3. ブランドカラー方針 (frontend 統一)

| トークン | 値 | 用途 |
|---|---|---|
| `--brand` | `#1877f2` | CTA / アクセント / フォーカスリング |
| `--brand-dark` | `#0f5fc8` | hover |
| `--hero-bg` | `#0a1628` (Dark Navy) | Hero / Closing CTA / Footer |
| `--bg-subtle` | `#f0f6ff` | Problem Band / AI Split 背景 |
| `--ink` | `#111827` | 本文 |
| `--ink-inv` | `#f0f6ff` | ダーク背景上のテキスト |

`#0a1628` は **frontend では未使用** の新規ダークネイビー。LP 専用色として `lp/tailwind.config.mjs` または CSS 変数で管理。

### 2-4. フォントの追加

`DM Serif Display` を追加（Hero H1 / Section H2 / Closing CTA で使用）。Inter は本文継続。

Google Fonts URL:
```
https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Inter:wght@300;400;500;600;700&display=swap
```

### 2-5. 実装方針

**Generator は提供された HTML をそのまま採用しない**。Astro/Tailwind プロジェクトに統合する形で実装:

1. **CSS は Tailwind utility class で書き直し**: 提供 HTML の `<style>` ブロック内 CSS を Tailwind class で再表現。複雑な radial-gradient 等は `style` 属性 or `lp/tailwind.config.mjs` の extension で対応
2. **CSS 変数 (`--brand` 等) は `lp/tailwind.config.mjs` の brand トークンで代替**: 既存の `brand-500` (`#1877f2`) と一致するため、新規トークン追加は最小限
3. **JavaScript は不要**: ADR-054 のタブ切替 JS を **削除**（Hub Card Grid は全可視）
4. **既存ファイル維持**: `BaseLayout.astro` / `Footer.astro` / `Header.astro` は最小修正、`index.astro` の `<body>` 内を全面書き換え

### 2-6. 既存セクションの扱い

| 旧セクション | 扱い |
|---|---|
| ADR-054 Tab buttons (5 タブ) | **削除** |
| ADR-054 Tab panels (5 枚) | **削除** (Hub Card Grid に統合) |
| ADR-054 Footer | **品質向上**（3 列構造維持、ロゴ + ブランド文追加） |
| ADR-046/047 ヘッドライン | Hero desc やメタタグで保持 |

### 2-7. レスポンシブ要件

| breakpoint | 挙動 |
|---|---|
| `≥ 1024px` | Hero 2 col / Hub Card 3 col / AI Split 2 col |
| `768px - 1023px` | Hero 1 col / Hub Card 2 col / Problem Band 2 col / AI Split 1 col |
| `< 640px` | 全 1 col / H1 34px / Section title 32px |

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | LP の視覚品質を「チープ」から「プロ品質」へ引き上げ、Meta App Review レビュアーの印象を強化 | 最優先 |
| 2 | しんごさん本来の事業要件（B2B 顧客への価値訴求、商談獲得）を満たす完成度に到達 | 最優先 |
| 3 | HubSpot 英語版の証明済み構文・見せ方を取り入れることで、独自リサーチコスト削減 | 高 |
| 4 | frontend ブランドカラーとの統一感を維持しつつ、LP 独自の「掘り下げた色使い」(Dark Navy + Blue Glow) を実現 | 中 |

---

## 4. Scope 外

- **frontend アプリ (`frontend/`) への影響**: ダークネイビー `#0a1628` は LP 専用
- **他ページ (privacy / terms / data-deletion / deletion-status)**: 無変更
- **バックエンド API 変更**: なし
- **フォーム送信を Formspree 等に置換**: mailto 維持 (ADR-054 継承)
- **ヒーロー画像 / 動画 / アニメーション素材の制作**: 絵文字 + CSS グラデーションで対応、別 ADR で素材化検討
- **Tailwind v4 移行**: 別 ADR
- **新規 UI ライブラリ導入**: shadcn / Radix 等は導入しない
- **Hub Card "Learn more" リンクの遷移先実装**: `#` プレースホルダーで OK、別 ADR で詳細ページ作成

---

## 5. 事業上の制約 (最重要)

### 5-1. ADR-046〜054 の制約継承

- `facebook-domain-verification` メタタグ維持
- 会社情報維持 (HIGH LIFE JPN / Shingo Tanizawa / 英語住所 / `support@salesanchor.jp`)
- 言語完全英語維持
- Privacy / Terms / Data Deletion / Sign in 導線維持
- フォーム mailto 維持

### 5-2. プレースホルダー禁止事項

| セクション | 配置必須 |
|---|---|
| S1 badges (3 枚) | "Built for: TCG Exporters" / "Workflow: Zero Excel tabs" / "Scale: 100s of B2B deals" 必須配置、空白オミット禁止 |
| S2 Problem cards (3 枚) | 3 課題すべて実装、削減不可 |
| S3 Hub Cards (6 枚) | Sales / Marketing / Customer / Data / AI / Catalog & Invoicing **全 6 枚必須**、削減不可 |
| S4 AI Steps (3 枚) | Deal AI / Data AI / Customer AI **全 3 枚必須** |

### 5-3. 誇大広告チェック

| 文言 | 採否 |
|---|---|
| "Resolves over 65% of buyer inquiries automatically" | ⚠️ **要確認**: β段階で実績数値がない場合、削除または「Can resolve buyer inquiries automatically, around the clock」に変更 |
| "around the clock" / "24/7" | ✅ 機能仕様、誇大広告ではない |
| "hundreds of B2B deals" | ✅ アスピレーション、誇大広告ではない |
| 数値バッジ (Award / No.1 等) | ❌ ADR-054 §5-5 継承、配置禁止 |

### 5-4. フォントロード最適化

`<link rel="preconnect">` / `<link rel="preconnect" crossorigin>` を維持。font-display: swap を必ず指定。

### 5-5. アクセシビリティ

- `aria-label` (Header logo / Sign in)
- フォーム `<label for>` の正しい紐付け維持
- `required` フィールドの視覚 + semantic 表示
- Hero H1 の `<em>` は装飾、意味的 emphasis ではないため `role="presentation"` を検討

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright (or HTML fallback) — 全 5 ページ表示確認、各セクション存在確認、レスポンシブ
- [ ] Skip — UI 大規模変更のため必須

### Reviewer 追加観点 (機械的確認)

- [ ] Hero H1 が "The game changer / isn't your spreadsheet. / It's context." (italic em with brand color) 構造か
- [ ] Hero 背景が `#0a1628` (Dark Navy) + radial-gradient (Blue Glow) か
- [ ] Problem Band 3 カードが配置されているか
- [ ] Hub Card Grid 6 枚すべて配置されているか (Sales / Marketing / Customer / Data / AI / Catalog & Invoicing)
- [ ] AI Split Section の 3 step (Deal AI / Data AI / Customer AI) が配置されているか
- [ ] Closing CTA セクションが配置されているか
- [ ] Footer がロゴ + ブランド文 + Operator + Legal の 3 列構造か
- [ ] タブ切替 JS (`.tab-btn`, `.tab-panel`) が **削除** されているか
- [ ] DM Serif Display フォントがロードされているか
- [ ] `facebook-domain-verification` メタタグ維持
- [ ] mailto 送信維持
- [ ] §5-3 誇大広告チェック: "65%" 等の検証必要文言の検出

### 追加検証 (しんごさん)

- 本番反映後、`https://salesanchor.jp/` を目視
- 「チープ」感が解消されているか
- HubSpot 英語版 (hubspot.com) と並べて見て、構造的に同系統と感じるか
- アプリ (app.salesanchor.jp) のブランドカラー (#1877f2) と統一感があるか
- Hero / Closing CTA / Footer のダークネイビーが効果的に機能しているか

---

## 7. 3 点セット要件

該当しない (外部システム新規連携なし)。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. ADR-054 維持、コピーだけ調整 | ❌ 却下。視覚品質が根本的に不足 |
| B. しんごさん提供 HTML をそのまま採用 (Astro 統合なし) | ❌ 却下。Tailwind / 既存コンポーネントとの整合性破壊 |
| C. Tailwind v4 移行 + デザイントークン全面刷新 | ❌ 却下。スコープ外、別 ADR |
| **D. しんごさん提供 HTML を Astro/Tailwind に統合 (本案)** | ✅ 採用 |

---

## 9. 未決事項 (Generator 判断)

- CSS 変数 (`--brand`, `--hero-bg` 等) を `lp/tailwind.config.mjs` の theme.extend で定義するか、`<style>` ブロックに残すか (前者推奨)
- `#0a1628` (Dark Navy) を `brand-navy` トークンとして tailwind config に追加するか
- Hero badge の具体文言 (badges 3 枚) は提供 HTML 通り採用 or 微調整
- §5-3 で要確認とした "Resolves over 65%" 文言の最終決定 (削除 or 言い換え)
- AI Split Section の右側 visual (現状: 🤖 絵文字大) の差し替え検討余地
- Footer ロゴ画像のサイズ (`h-32px`) の妥当性

---

## 10. 起案者の認知限界

- 提供 HTML はしんごさんが Web Claude (別セッション or ChatGPT 等) から取得したと推測。実 HubSpot サイトとの構文一致度は本 Web Claude が直接確認していない
- frontend アプリ実 UI のスクショ確認は ADR-054 で実施済み、ブランドカラー方針は継承
- ADR-057 自体が ADR-056 (人間介在最小化) マージ後の **初の本格 UI ADR**。完全自動化フロー (Reviewer/Evaluator → automerge to develop) で進む想定
- 番号衝突確認: Terminal CC が `ls docs/adr/ADR-*.md | sort | tail -5` で再確認
- 提供 HTML の `<style>` ブロック内 CSS 量が多いため、Generator が Tailwind utility class への変換で意図を失う可能性。原 HTML をリポジトリ内 `docs/proposals/adr-057-prototype.html` として保管し、Generator が参照できるようにする想定

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

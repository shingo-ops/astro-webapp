# ADR-047: LP Copy Refocus — Customer-First Voice + Visual Polish

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (Planner) via Shingo
- **対象範囲**: `lp/`
- **関連 ADR**: ADR-046（補完・修正）、ADR-013（アプリ本体のブランドアセット、Scope 分離）

---

## 1. 背景

ADR-046 を実装した PR #403 が develop に merge され、本番 `https://salesanchor.jp/` に反映された。確認の結果、以下 3 つの構造的問題が顕在化した。

### 1-1. コピーが顧客に向いていない（最重要）

ADR-046 §3 (Why) で優先順位を次のように設計したことが根本原因:

```
| 1 | Meta App Review 担当者への実体性訴求 | 最優先 |
| 2 | 将来の海外 B2B 顧客への営業ツール兼用 | 中    |
```

この優先順位が **構造的に逆**。Generator は ADR §Why に忠実に書いたため、本番 LP のコピーが「Sales Anchor は◯◯です / データは TLS 1.3 で暗号化されます」型の **自己紹介＋コンプライアンス訴求** になっている。これは Linear / Attio / Resend が絶対にやらない書き方であり、想定顧客（TCG B2B 輸出業者）に対して「この CRM を使えば自分のビジネスがどう変わるか」を伝えていない。

正しい因果は **「顧客に響く本物の LP を作る → そのプロ品質が結果として Meta レビュアーに『実体ある SaaS』と伝わる」**。Meta 審査通過は経路であって目的ではない。

### 1-2. ヒーローに巨大ロゴ画像が残った

`lp/src/pages/index.astro:36-40` に `<img src="/logo.png" class="max-w-2xl">` が配置され、ヒーローセクションの主役になっている。ADR-046 §2-2 で参照軸とした Linear / Attio / Resend では、ヒーローの主役は **ヘッドラインのタイポグラフィ**であり、巨大ロゴは置かない。ADR-046 §2-2「装飾的イラスト排除 / タイポグラフィで魅せる」の精神に反する状態。

### 1-3. ファビコンが仮アイコンのまま

`lp/public/favicon.svg`（298B）は手書きジオメトリの仮アイコンで、正式の錨ロゴと一致しない。`frontend/public/favicon.png`（31KB）に正式錨ロゴの PNG 版が存在するが、`lp/public/` には未配置。apple-touch-icon.png も lp 側に未配置。

| ファイル | lp/public | frontend/public | 整合 |
|---|---|---|---|
| favicon.svg | 298B（仮） | 298B（同じ仮） | 仮アイコン重複 |
| favicon.png | なし | 31KB（正式） | lp 欠落 |
| apple-touch-icon.png | なし | 44KB | lp 欠落 |
| logo.png | 211KB | 62KB | 異なる |

---

## 2. 決定（What）

3 つの問題を **1 本の ADR** にまとめて解決する。論点はそれぞれ独立に見えるが、すべて「ADR-046 が達成したかった『Linear/Attio/Resend 系のプロ品質 LP』の完成」という同一目的に収束する。

### 2-1. §Why の優先順位を反転

LP の主目的を次のように設定し直す（§3 で詳述）:

| # | 目的 | 優先度 |
|---|---|---|
| 1 | TCG B2B 輸出業者（想定顧客）への価値訴求 | 最優先 |
| 2 | (1) を実現することで結果として Meta App Review 担当者にも「実体ある SaaS」と認識される | 副次効果 |

### 2-2. 全コピーを顧客視点に全面リライト

#### 主訴求軸

しんごさんの言葉「全ての情報を一元管理して情報を統制して分析するツール」を 3 拍子で展開:

- **Unify** — every channel, every customer, every transaction in one place
- **Control** — structured records, defined workflows, no information falling through cracks
- **Analyze** — see what's working, find your next move

この 3 拍子を全ページの基底メッセージとする。

#### コピー方針（必須）

- **主語は "You" / "Your team"**（"We" / "Sales Anchor is" 型の自社紹介は禁止）
- **問題提起 → 解決提示の構造**（"What it is" ではなく "What you can do"）
- **TCG 輸出業者の現場の言葉**（"Instagram DM"、"international invoice"、"cross-border"、"B2B trade" は実体ある言葉）
- **スペック羅列禁止**（"TLS 1.3 / Fernet 暗号化 / PostgreSQL RLS" のような技術スペックは LP 本文から削除、詳細は `privacy.astro` に集約）
- **複数ペルソナ対応**: A (Excel/DM カオス勢) / B (B2B 輸出ビギナー) / C (既存 CRM 不適合勢) の共通課題に絞る

#### セクション別の方針

| Section | ADR-046 までの内容 | ADR-047 での扱い |
|---|---|---|
| A1 Hero | Headline "The CRM built for cross-border TCG exporters." + 既存 subline | Headline 維持、subline を Unify/Control/Analyze 3 拍子で書き直し |
| A2 Who it's for | "TCG B2B 輸出業者向け説明文" | 3 ペルソナの **共通課題シーン** を描写。「Excel と Chatwork と Instagram DM を行き来する週末」のような具体描写 |
| A3 Features | 4 カード（機能名 + 説明） | カードのラベルを「機能名」から「You can ◯◯」型に変換。各カードに 1 行の **顧客がこれで変わること** |
| A4 Meta data policy | Meta Graph API データ取り扱いポリシー | **維持必須**（Meta 審査要件）。ただし平易な英語に整える。スペック羅列は不可 |
| A5 Security | TLS 1.3 / Fernet / RLS のスペック羅列 | **「安心」軸に転換**。"Your data is encrypted, isolated per tenant, and never sold." 程度の 1-2 文に圧縮。技術スペックは `privacy.astro` に移譲 |
| A6 Operator info | 会社情報セクション | **Footer に統合**、独立セクション廃止。LP 本文の流れを邪魔しない |

### 2-3. ヒーローから巨大ロゴ画像を削除

`lp/src/pages/index.astro:36-40` の `<img src="/logo.png">` を削除。ヒーローは Headline / Subline / CTA のタイポグラフィ主体に。

ブランドはヘッダーロゴと favicon で十分認識される（Linear / Attio / Resend と同じ構造）。

### 2-4. ファビコンを正式錨ロゴに統一

- `frontend/public/favicon.png`（正式錨ロゴ 31KB）を `lp/public/favicon.png` にコピー
- `frontend/public/apple-touch-icon.png`（44KB）を `lp/public/apple-touch-icon.png` にコピー
- `lp/public/favicon.svg`（仮アイコン）は削除可、または正式錨 SVG が `frontend/` に存在すれば差し替え
- `lp/src/layouts/BaseLayout.astro:55` の `<link rel="icon">` を複数フォーマット対応に更新:
  ```html
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon.png" />
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
  ```

### 2-5. Header ロゴの統一

`lp/public/logo.png`（211KB）と `frontend/public/logo.png`（62KB）が別ファイル。Generator が両者を比較し、**同じデザインの別解像度なら frontend 版に統一**、**別バージョンならしんごさんに確認**。

---

## 3. Why（事業上の目的）

| # | 目的 | 優先度 |
|---|---|---|
| 1 | **TCG B2B 輸出業者という想定顧客への価値訴求** — 3 拍子（Unify / Control / Analyze）でビジネス変化を伝える | 最優先 |
| 2 | (1) を実現することで結果として Meta App Review 担当者にも「実体ある真っ当な SaaS」と認識される | 副次効果 |
| 3 | ADR-046 が達成したかった Linear / Attio / Resend 系のプロ品質 LP を完成させる（ヒーロー画像 / ファビコン問題の解消） | 並行 |

### ADR-046 からの根本的転換

ADR-046 の Why は「Meta 審査通過」を経路ではなく目的化していた。ADR-047 はこれを反転し、**顧客価値訴求が達成されれば Meta 審査も自然に通過する**という因果に直す。Generator はこの §Why を読んで、コピー全体のトーンを「自社紹介」から「顧客への約束」に転換する。

---

## 4. Scope 外

以下は本 ADR の対象外。混入した場合、Reviewer は Scope creep として `--request-changes` する。

- **バックエンド API 変更**: Data Deletion Callback / `api.salesanchor.jp` 配下は変更しない
- **`privacy.astro` の内容変更**: ADR-046 で英語化済み（v1.4）の 13 章構造は維持。A5 から移譲された技術スペック詳細を追記するのみ可
- **`terms.astro` / `data-deletion.astro` / `deletion-status.astro` の内容変更**: ADR-046 完了済み
- **Tailwind v4 移行**: 別 ADR
- **アプリ本体（`frontend/`）のブランドアセット変更**: ADR-013 の領域
- **`og-image.png` の差し替え**: 別 ADR で扱う余地あり、本 ADR では対象外
- **新規 UI ライブラリ導入**: shadcn / Radix / daisyUI は導入しない（ADR-046 と同じ方針）
- **ドメイン構成変更**: 維持

---

## 5. 事業上の制約（刷新後も維持必須）

ADR-046 §5 で定めた制約を **全て継承**:

- 会社情報の表示（HIGH LIFE JPN / Shingo Tanizawa / 英語住所 / `support@salesanchor.jp`）— 移譲先は Footer に統合可
- `privacy.astro` v1.4 の 13 章構造 / APPI / Meta Platform Terms 準拠
- Data Deletion 連携（2 方式説明 / `?code=` フロー / `api.salesanchor.jp/api/v1/meta/deletion-status` 参照）
- `facebook-domain-verification` メタタグ
- ナビゲーション整合性（全 5 ページ間のリンク破綻なし、`app.salesanchor.jp` "Sign in" 導線）

### A4 Meta data policy セクションの維持

Meta App Review 要件のため、A4 セクション自体は **省略不可**。コピーは平易な英語に整えるが、扱うデータ種別 / 利用目的 / 保存期間 / 削除導線の 4 点は明示する。

---

## 6. 検証要件（Reviewer / Evaluator へ）

### Evaluator method

Generator が PR 本文に転記する想定:

- [x] Layer 1: Playwright (default) — 全 5 ページ表示確認、Header / Footer ナビ整合性、favicon 表示、apple-touch-icon の HTTP 200 応答
- [ ] Layer 2: Claude in Chrome — 不要
- [ ] Skip — 該当しない

### Reviewer 追加観点

通常のコードレビューに加え、以下を **目視で確認**:

- [ ] LP 本文に **"We are" / "Sales Anchor is" / "Sales Anchor provides"** などの自社紹介開始フレーズが残っていないか
- [ ] **TLS / Fernet / RLS / PostgreSQL** などの技術スペック単語が `privacy.astro` 以外（特に index.astro A5）に残っていないか
- [ ] ヒーローセクションに `<img src="/logo.png">` の巨大表示が残っていないか
- [ ] favicon が `/favicon.svg`（仮）のみではなく、`/favicon.png` + `/apple-touch-icon.png` を含むか

### 追加検証（人間）

- しんごさんが新コピーを **顧客視点で音読** し、「これなら TCG 輸出業者に響く」と判断
- A2 のシーン描写が、実在する顧客課題と一致しているか確認

---

## 7. 3 点セット要件（ADR-025）の適用判断

本 ADR は **外部システムとの新規状態共有を伴わない**（既存の Data Deletion Callback は維持のみ）。したがって 3 点セット要件は対象外。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| ADR-046 を Revise として書き直す | ❌ 却下。merge 済み、履歴が複雑化 |
| 3 問題を独立 3 ADR（コピー / ヒーロー画像 / ファビコン）に分ける | ❌ 却下。すべて「ADR-046 の完成」という同一目的、独立させる意味なし |
| ヒーロー画像問題だけ hot-fix、コピーは後で別 ADR | ❌ 却下。ヒーロー画像を削除すると残ったコピーの薄さが露呈する、同時対応すべき |
| 本 ADR（3 問題を 1 本に統合） | ✅ 採用 |

---

## 9. 未決事項（Generator 判断に委ねる）

以下は本 ADR では決めず、Generator の判断に委ねる:

- 具体的なヒーロー Subline 文言（3 拍子の表現方法）
- A3 各機能カードの「You can ◯◯」型ラベル文言
- A2 顧客シーン描写の具体内容（Excel / Chatwork / Instagram DM を行き来する週末、のような描写）
- A5 セキュリティセクションの 1-2 文の具体表現
- A6 を Footer に統合する具体的な配置
- `lp/public/logo.png` を frontend 版に置き換えるか維持するかの判断（解像度比較で）
- `favicon.svg` を削除するか正式 SVG に差し替えるか
- セクション間の余白 / タイポ階層の微調整

---

## 10. 起案者の認知限界

本 ADR は Web Claude（Plan モード相当）が起案。以下を明記:

- **A2-A6 の現状コピー本文は未確認**。これは意図的（§9）で、Generator が現状に引きずられず白紙から書き直せるようにするため
- `lp/public/logo.png`（211KB）と `frontend/public/logo.png`（62KB）の中身が同じデザインか別バージョンかは未確認
- `frontend/public/` に正式錨ロゴの SVG 版があるかは未確認（PNG のみの想定）

これらは Generator が PR 作成時に補完する。

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

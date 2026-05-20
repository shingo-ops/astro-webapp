# ADR-049: LP Section Completion Hot-fix — S3 Carousel Cards + S4 Ecosystem Diagram + S5 Metrics Band + S6 Why-us 4-column

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `lp/src/pages/index.astro`
- **関連 ADR**: ADR-047（補完 hot-fix、構造を継承）、ADR-046（補完）、ADR-048（Web Claude 位置づけ、並行起案中）

---

## 1. 背景

ADR-047 を実装した PR #405 が develop → main に reflect され、本番 `https://salesanchor.jp/` に新 LP が公開された。確認の結果、ADR-047 §2-2 で指示した S1-S9 構成のうち、**S3 が部分実装、S4 / S5 / S6 が完全欠落** の状態で本番反映されている:

| Section | ADR-047 §2-2 指定 | 本番現状 |
|---|---|---|
| S1 Hero | タイポ主体、3 拍子サブライン | ✅ 実装 |
| S2 Value lead | "Sound familiar?" 問題提起 | ✅ 実装 |
| **S3 Feature carousel** | 見出し + **製品スクショ** + 個別 CTA | ⚠️ **テキストのみ、画像なし、個別 CTA なし** |
| **S4 Ecosystem diagram** | 中央 Sales Anchor + 周囲チャネル接続図 | ❌ **完全欠落** |
| **S5 Metrics band** | 言葉系訴求カード | ❌ **完全欠落** |
| **S6 Why us 4-column** | 4 カラム特長 | ❌ **完全欠落** |
| S7 Meta data policy | Meta 審査要件 | ✅ 実装 |
| S8 Final CTA | "Ready to scale?" 強調 | ⚠️ Hero と同じ CTA のみ |
| S9 Footer | 会社情報統合 | ✅ 実装 |

結果として、omni.chat 系の **視覚的・商業的な部分**（製品スクショ / 接続図 / 数値訴求 / 4 カラム）が全て欠落し、Linear/Attio 系のミニマルテキスト LP に逆戻りしている。**「omni.chat 系に転換した意味」が実装で達成されていない**。

しんごさんの本番確認時のフィードバック「メインにマージされたが変化した？ってぐらいしょぼい」がこの状態を端的に示している。

### 1-1. ADR-047 起案ミスの構造的原因

ADR-047 §9 未決事項で次のように書いた:

```
S3 製品スクショ:
  デフォルト: 案 A を試みて、不可能なら案 C にフォールバック
S4 エコシステム接続図:
  案 A: Generator が SVG でシンプルな放射状図を作る
  デフォルト: 案 A
```

これは Generator に「不可能ならオミット可」という暗黙のシグナルを送っていた。Generator は誠実にこれを読み、素材調達が難しい / SVG 自作の判断が立たない場合、**セクション自体を完全にオミット** することを選択した。

ADR-047 §5 制約に「S3-S6 は実装必須、素材未調達ならプレースホルダーでもよい」と明記すべきだった。これは Web Claude（起案者）の構造的ミス。

### 1-2. Meta App Review 直前のタイミング

しんごさんは現状で screencast 撮影 → 提出を進めることもできたが、Strategy B（hot-fix を先）を選択。理由:

- Meta App Review はリジェクトされると再提出に数週間かかる
- screencast 内 UI と LP のブランド統一感を保ちたい
- 当初要望（「ダサい LP にしたくない / プロのアプリっぽい仕様」）の達成

ADR-049 は **Meta App Review 提出前の最終整備** という位置づけ。

---

## 2. 決定（What）

S3 を補完し、S4 / S5 / S6 を新規追加することで、ADR-047 §2-2 で指示した S1-S9 構成を **完成** させる。

### 2-1. S3 Feature carousel の補完

既存の 4 枚テキストカードを omni.chat 風カルーセル形式に拡張する:

- **既存維持**: 4 枚のカード見出し（"You can respond to every channel from one screen" 等）と説明文
- **追加要素 (each card)**:
  - **製品スクショ画像枠**: 当面プレースホルダー（後述 §9）
  - **個別 CTA**: "See it in action" → mailto:support@salesanchor.jp?subject=Demo%20request（Hero CTA と同じ宛先で OK）
  - **レイアウト**: omni.chat の機能カルーセル風に、各カードを **画像 + テキスト + CTA の大型ブロック**として配置（縦並び or 横並びは Generator 判断）

### 2-2. S4 Ecosystem diagram の新規追加

S3 の直後に新規セクションを配置:

- **見出し例**: "One platform, every channel" など（Generator 判断）
- **中央**: Sales Anchor（テキストロゴ or 錨アイコン）
- **周囲**: 7 つの主要チャネル
  - Messenger
  - Instagram
  - WhatsApp
  - LINE
  - Discord
  - Telegram
  - Email
- **任意追加**: 関連ツール（Stripe / Shopify / 配送業者など、Generator 判断で 0-3 個）
- **接続線**: 中央から周囲への線（点線 or 実線、SVG）
- **実装方法**: インライン SVG を Astro コンポーネントとして配置

### 2-3. S5 Metrics band の新規追加

S4 の直後に新規セクションを配置:

- **形式**: 横並び 3-4 カードの強調バンド
- **数値表記**: **言葉系訴求のみ**（β 段階で誇大広告にならないため）:
  - "7 channels" — in one inbox
  - "Hundreds of B2B orders" — per operator per month
  - "Zero information lost" — every conversation tracked
- **タイポ**: 数値部分を大型フォント、説明文を小型で
- **背景色**: Salesanchor 青系のアクセント（薄い青 or グレー）でセクション全体を強調

### 2-4. S6 Why us 4-column の新規追加

S5 の直後 / S7 (Meta data policy) の直前に新規セクションを配置:

- **形式**: 横並び 4 カラム（モバイルでは縦並び）
- **見出し例**: "Why Sales Anchor" など
- **4 カラム内容**:
  - **Set up fast** — Quick onboarding, no lengthy implementation
  - **Scale with confidence** — Built for B2B trade volume
  - **Direct support** — Talk to the team that built it
  - **Built for cross-border trade** — TCG export workflows in mind
- 各カラムに小型アイコン（任意、Generator 判断）

### 2-5. 既存セクションの維持

S1 / S2 / S7 / S8 / S9 の **コピーと構造は変更しない**。本 ADR の Scope は **S3 補完 + S4-S6 新規追加** のみ。

### 2-6. 全体構造の確認

刷新後の本番 LP は以下の流れになる:

```
S1 Hero
  ↓
S2 Value lead ("Sound familiar?")
  ↓
S3 Feature carousel (4 cards with image plates + CTAs)  ← 補完
  ↓
S4 Ecosystem diagram (SVG, center + 7 channels)  ← 新規
  ↓
S5 Metrics band (3-4 word-based metric cards)  ← 新規
  ↓
S6 Why us (4 columns)  ← 新規
  ↓
S7 Meta data policy
  ↓
S8 Final CTA
  ↓
S9 Footer
```

---

## 3. Why（事業上の目的）

| # | 目的 | 優先度 |
|---|---|---|
| 1 | ADR-047 §2-2 で指示した omni.chat 系構造を **完成** させる（実装漏れの補完） | 最優先 |
| 2 | しんごさんの当初要望「ダサい LP にしたくない / プロのアプリっぽい仕様」を達成 | 高 |
| 3 | Meta App Review 提出前の最終整備 — screencast Demo との完成度整合 | 高 |
| 4 | LP を読んだ顧客（TCG B2B 輸出業者）に "見て理解できる" 視覚的価値訴求を実現 | 中 |

---

## 4. Scope 外

- **S1 / S2 / S7 / S8 / S9 への変更**: 既に実装済み、本 ADR では **不変**
- **動画背景ヒーロー**: β 段階で素材なし、ADR-047 と同じ方針で対象外
- **顧客テスティモニアル**: β 段階で実績なし、対象外
- **ISO 認証バッジ**: 未取得、対象外
- **実 UI スクショの本格撮影**: S3 はプレースホルダーで OK、本格撮影は将来別 ADR
- **バックエンド API 変更**: なし
- **privacy.astro / terms.astro / data-deletion.astro / deletion-status.astro の変更**: ADR-046 / ADR-047 で完了済み
- **Tailwind v4 移行**: 別 ADR
- **アプリ本体（`frontend/`）のブランドアセット変更**: ADR-013 の領域
- **新規 UI ライブラリ導入**: shadcn / Radix / daisyUI は導入しない

---

## 5. 事業上の制約（**最重要**）

### 5-1. 実装必須セクションの明示（ADR-047 起案ミスからの教訓）

- **S3, S4, S5, S6 は実装必須**。素材未調達でも **プレースホルダー** で配置すること
- **空白セクションとしてオミットすることは禁止**
- プレースホルダーの定義:
  - **S3 画像枠**: CSS で枠線 + 中央テキスト（例: "Product screenshot — coming soon"）+ 背景色（薄い Salesanchor 青）でも可
  - **S4 Ecosystem 図**: SVG 自作（複雑なデザインでなくてよい、単純な中央 + 周囲の図形でも OK）
  - **S5 Metrics**: 言葉系訴求カードのみ、画像不要
  - **S6 4 column**: テキストのみで OK、アイコンは任意
- **「実装難しいから飛ばす」は本 ADR で明確に禁止**

### 5-2. 既存セクションの保護

- S1 Hero のヘッドライン "The CRM built for cross-border TCG exporters." は不変
- S1 サブライン（3 拍子）は不変
- S2 "Sound familiar?" の問題提起は不変
- S7 Meta data policy の 5 つの bullet は不変
- S9 Footer の会社情報（HIGH LIFE JPN / 住所 / 連絡先）は不変
- 全 5 ページ間のナビゲーション整合性

### 5-3. ADR-046 / ADR-047 の制約継承

- `facebook-domain-verification` メタタグ維持
- `api.salesanchor.jp/api/v1/meta/deletion-status` エンドポイント参照維持
- 顧客視点コピー方針継承（"You" 主語、自社紹介禁止、スペック羅列禁止）
- Salesanchor 青系ブランドカラー統一
- Inter フォント維持

### 5-4. 視覚的判断基準

実装後、しんごさんが本番 LP を omni.chat と並べて見て **「視覚的に同系統」と認識できる** ことを判断基準とする。「テキストばかりで omni.chat とは別系統」と感じた場合は失敗。

---

## 6. 検証要件

### Evaluator method

Generator が PR 本文に転記する想定:

- [x] Layer 1: Playwright (default) — S3 (4 cards + image plates + CTAs) / S4 (SVG diagram visible) / S5 (metrics band) / S6 (4 column) の表示確認、レスポンシブ
- [ ] Layer 2: Claude in Chrome — 不要
- [ ] Skip — 該当しない

### Reviewer 追加観点（目視 + 機械的確認）

- [ ] S3 の 4 カードそれぞれに **画像枠 + テキスト + 個別 CTA "See it in action"** が存在するか
- [ ] S4 Ecosystem diagram が **SVG として実装** され、中央 Sales Anchor + 7 つのチャネル が視覚的に確認できるか（テキストリストではダメ）
- [ ] S5 Metrics band が **横並び強調表示**で実装されているか（普通の段落として埋もれていない）
- [ ] S6 Why us が **横並び 4 カラム**で実装されているか（縦並び単純リストではない）
- [ ] S1 / S2 / S7 / S8 / S9 の既存テキストが変更されていないか
- [ ] Tailwind v3.4 のまま、v4 移行されていないか
- [ ] 自社紹介フレーズ（"We are" / "Sales Anchor is" 等）の混入なし
- [ ] 技術スペック単語（TLS / Fernet / RLS）が privacy.astro 以外に再登場していないか

### 追加検証（しんごさん）

- 本番反映後、`https://salesanchor.jp/` と `https://omni.chat/` を並べて見て、**視覚的に同系統**と認識できるか
- 「メインにマージされたが変化した？ってぐらいしょぼい」感覚が解消されているか
- S5 数値訴求が β 段階の実態と乖離していないか（誇大広告チェック）

---

## 7. 3 点セット要件（ADR-025）の適用判断

本 ADR は **外部システムとの新規状態共有を伴わない**。3 点セット要件は対象外。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| **A. 現状で Meta 提出を先、改善は後** | ❌ 却下（しんごさんが Strategy B 選択） |
| **B. ADR-047 を Revise として書き直す** | ❌ 却下。merge 済み、履歴複雑化 |
| **C. 4 セクション（S3-S6）を別々の 4 つの ADR に分割** | ❌ 却下。全て omni.chat 系完成という同一目的、独立性なし |
| **D. ADR-049 で 4 セクションを 1 本にまとめて補完** | ✅ 採用 |

---

## 9. 未決事項（Generator 判断に委ねる）

### 素材調達

- **S3 製品スクショプレースホルダー**:
  - **デフォルト**: CSS で枠 + テキスト "Product screenshot — coming soon" + Salesanchor 青系背景
  - 実 UI 撮影に成功した場合は実画像を使用してもよい
  - **空白オミットは禁止**（§5-1）
- **S4 Ecosystem diagram の具体ビジュアル**:
  - **デフォルト**: 中央 Sales Anchor のテキスト or 錨アイコン + 周囲に 7 チャネルを放射状配置、線で接続
  - レイアウトは放射状 / hub-spoke / 円形配置のいずれでも可
  - SVG の複雑さは問わない、**視覚的にエコシステム接続と認識できればよい**
- **S5 数値訴求の具体表現**:
  - **デフォルト**: "7 channels in one inbox" / "Hundreds of B2B orders / operator / month" / "Zero information lost — every conversation tracked" の 3 枚
  - **重要**: 具体 % や倍数（"50% 効率化" 等）は使わない（誇大広告回避）
- **S6 4 カラムの具体テキスト**:
  - **デフォルト**: "Set up fast" / "Scale with confidence" / "Direct support" / "Built for cross-border trade"
  - 各カラムの説明文は Generator が 1-2 文で書く
- **S4 / S6 のアイコン使用**: 使用してもしなくてもよい

### レイアウト判断

- S3 カードの縦並び / 横並び
- S4 図の配置サイズ
- S5 カードの 3 枚 / 4 枚
- S6 4 カラムのモバイル時の挙動
- 各セクション間の余白

### その他

- PR コメントでしんごさんに確認するか、Generator が自律的に判断するかは Generator の自由

---

## 10. 起案者の認知限界

本 ADR は Web Claude（外部補助 Planner）が起案。以下を明記:

- 本番 LP の実物はしんごさんから提供されたスクリーンショット + テキスト抜粋で確認した範囲（2026-05-20 時点）
- 本番 CSS や HTML の構造詳細は未確認、Generator が現状 `lp/src/pages/index.astro` を読んで判断
- S3 の既存テキストカード 4 枚の現状実装（縦並び / 横並び / div 構造）は未確認
- 番号衝突確認: ADR-048 と並行して push される可能性があるため、Terminal CC が `ls docs/adr/ADR-*.md | sort | tail -5` で再確認すること
- ADR-049 自体が「ADR-047 の起案ミスを補完するための ADR」を Web Claude（ADR-047 起案者と同一）が書いている **構造**。これは ADR-048 で正式化した「外部補助 Planner の自己訂正サイクル」の最初の事例

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

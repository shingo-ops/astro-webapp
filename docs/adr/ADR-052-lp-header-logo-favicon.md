# ADR-052: LP Header Logo Sizing + Favicon Finalization

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `lp/src/components/Header.astro` / `lp/src/layouts/BaseLayout.astro` / `lp/public/favicon.*`
- **関連 ADR**: ADR-046 / ADR-047 / ADR-049 (LP 段階的整備)

---

## 1. 背景

本番反映 (`https://salesanchor.jp/`) 確認で 2 点の最終整備が必要:

1. **Header ロゴが小さすぎる** — `lp/src/components/Header.astro:14` で `h-12 w-auto` (48px 高) のため、ヘッダー上で視覚的に弱い
2. **ファビコンが正式ロゴになっていない** — ADR-049 で `lp/public/favicon.png` / `apple-touch-icon.png` を frontend 版にコピーする方針だったが、本番タブには錨マークが反映されていない

---

## 2. 決定（What）

### 2-1. Header ロゴ拡大

`lp/src/components/Header.astro:14` のサイズを調整:

- 現状: `h-12 w-auto` (48px)
- 変更後: `h-16 w-auto` または `h-20 w-auto` (64-80px、Generator 判断で omni.chat 系の Header 比率に合わせる)

### 2-2. ファビコン正式化の確認と修正

ADR-049 で指示済みだが本番に反映されていない可能性。Generator が以下を確認・修正:

1. `lp/public/favicon.png` が `frontend/public/favicon.png` (31KB 正式錨ロゴ) と一致しているか
2. `lp/public/apple-touch-icon.png` が `frontend/public/apple-touch-icon.png` (44KB) と一致しているか
3. `lp/src/layouts/BaseLayout.astro` の `<link rel="icon">` が `/favicon.png` を参照しているか (SVG 仮アイコンではなく)
4. キャッシュ問題で反映されていない場合、ファイル名を `favicon-v2.png` のように変更してキャッシュバスト

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | LP 視覚完成度の最終整備 — Meta App Review 提出前に解消 | 最優先 |
| 2 | ブランド認知の強化 — Header / favicon は LP 全ページで表示される | 高 |

---

## 4. Scope 外

- S1-S9 セクション本文の変更
- 他ページ (privacy / terms / data-deletion / deletion-status) のレイアウト変更
- バックエンド変更
- フォント変更
- 配色変更

---

## 5. 事業上の制約

- ADR-046 / ADR-047 / ADR-049 の制約を全継承
- Salesanchor 青系ブランドカラー維持
- ヘッダーロゴ拡大によるレスポンシブ崩れがないこと (モバイルで Header が縦に伸びすぎない)

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright — Header ロゴサイズ確認 + favicon の HTTP 200 + 正しい錨ロゴが表示されているか
- [ ] Layer 2
- [ ] Skip

### Reviewer 追加観点

- [ ] Header ロゴが `h-12` より大きいクラスになっているか
- [ ] `lp/public/favicon.png` の MD5 が `frontend/public/favicon.png` と一致するか
- [ ] `BaseLayout.astro` の `<link rel="icon">` が `.png` 参照になっているか (`.svg` だけではない)

### 追加検証 (しんごさん)

- 本番タブのファビコンが錨ロゴになっているか目視
- Header ロゴが視覚的に強くなったか目視

---

## 7. 3 点セット要件

該当しない。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. Header ロゴ拡大のみ、favicon は別 ADR | ❌ 2 件とも 1 file 級の最小修正、1 ADR で十分 |
| B. 本 ADR (Header + favicon 同時修正) | ✅ 採用 |

---

## 9. 未決事項 (Generator 判断)

- Header ロゴの具体サイズ (`h-16` or `h-20`)
- favicon キャッシュバスト戦略 (ファイル名変更 vs HTTP header)
- レスポンシブ調整の詳細

---

## 10. 起案者の認知限界

- 本番タブで favicon が錨ロゴになっていない事実はしんごさんのスクリーンショットで確認、原因 (ファイル未配置 / キャッシュ / 参照ミス) は未特定
- ADR-049 実装時に favicon コピーが実際に行われたかは PR #408 の diff 未確認
- 本 ADR は ADR-051 自動化適用後の **最初の自動 Reviewer / Evaluator** が動く ADR になる想定

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

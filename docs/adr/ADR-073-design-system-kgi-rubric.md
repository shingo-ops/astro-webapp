# ADR-073: デザインシステム KGI 100% ルーブリック

- **Status**: Accepted
- **Date**: 2026-05-26
- **Author**: Claude Code (Hikky-dev)
- **PO**: しんごさん

---

## 背景

デザインシステム・デザイントークン・シングル・ソース・オブ・トゥルースの3概念に沿った管理を
達成するための定量的なゴール定義が必要。「100%」を主観ではなく機械的に検証できる基準として定める。

---

## KGI 評価基準（5項目）

| # | 評価軸 | 重み | 計測方法 |
|---|--------|------|---------|
| 1 | 全共有コンポーネントに Storybook stories が存在する | 25% | `npm run check:stories` が PASS |
| 2 | 全トークンカテゴリが DesignSystemPage で視覚確認できる | 25% | 色・文字・余白・影・角丸・重なり順・アニメの7カテゴリが揃っている |
| 3 | トークン違反を CI が自動ブロックする | 20% | `npm run check:all` と `build-storybook` が CI で緑 |
| 4 | 未使用・未整理トークンがゼロ | 15% | `npm run audit:unused-tokens` の出力が 0件 |
| 5 | ドキュメント・ルールが揃っている | 15% | i18n例外ポリシー・オンボーディング導線・Storybook i18n設定が存在する |

**100%の定義**: 上記5項目が全て PASS した状態。

---

## 各評価軸の合否判定

### 軸1: stories カバレッジ（25%）

合格条件:
- `frontend/src/components/` 配下の**視覚コンポーネント**全件に `.stories.tsx` が存在する
- `npm run check:stories` が終了コード 0 で完了する

除外リスト（UI表示がないためstories対象外）:
- `ProtectedRoute.tsx` — 認証ガードのみ

### 軸2: DesignSystemPage カバレッジ（25%）

合格条件（7カテゴリ全てのセクションが `/design-system` に存在する）:
- ✅ Color Tokens（実装済み）
- ✅ Typography Roles（実装済み）
- ✅ Spacing（実装済み — SpacingSection, DesignSystemPage.tsx）
- ✅ Shadow（実装済み — ShadowSection, DesignSystemPage.tsx）
- ✅ Border Radius（実装済み — RadiusSection, DesignSystemPage.tsx）
- ✅ Z-index（実装済み — ZIndexSection, DesignSystemPage.tsx）
- ✅ Motion（実装済み — MotionSection, DesignSystemPage.tsx）

### 軸3: CI 自動ブロック（20%）

合格条件:
- `npm run check:all` が全チェックをパスする（PR マージ要件）
- `build-storybook` が CI の必須ステップとして存在し緑になる
- `npm run check:stories` が `check:all` に含まれている

### 軸4: トークン監査（15%）

合格条件:
- `npm run audit:unused-tokens` が 0件を報告する
- opacity トークン（0.7〜0.9帯の5トークン）の意味整理が完了し ADR に記録されている

### 軸5: ドキュメント（15%）

合格条件:
- `docs/design-system/storybook-i18n-policy.md` が存在する
- `docs/onboarding/claude-code.md` にデザインシステム導線が追加されている

---

## 対象外（スコープ外）

- Figma / デザインツールとのトークン連携（チーム規模に対してコスト過大）
- ビジュアルリグレッションテスト（Chromatic等）（現フェーズでは手動確認で代替）
- opacity トークン統廃合（視覚的影響があるため PO の目視承認後に別 PR で対応）

---

## 関連ADR

- ADR-067: デザイントークン強制ルール（CI・ESLint）
- ADR-027: UI国際化

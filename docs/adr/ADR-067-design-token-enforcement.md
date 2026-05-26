# ADR-067: デザイントークン強制システム（Design Token Enforcement）

**Status:** Accepted  
**Date:** 2026-05-21（Phase 0）〜 2026-05-24（Phase 5 完了）  
**Authors:** shingo-ops, Hikky-dev  

---

## 背景・課題

Meta Business Suite 風 UI（ADR-022）とダークモード（ADR-033）の実装後、以下の問題が顕在化した:

1. CSS / TSX に hex色（`#1877F2`）やマジックナンバー（`opacity: 0.5`）が直書きされ、ダークモード切替時に色が変わらない箇所が発生
2. デザイン値（色・スペーシング・z-index等）が複数ファイルに分散し、一括変更ができない状態
3. 規約が口頭・チャットのみで存在し、機械的な強制手段がなかった

---

## 決定

**デザイントークン（CSS Custom Properties）を唯一の真実（Single Source of Truth）とし、その逸脱を CI と ESLint で機械的にブロックする。**

---

## 実装フェーズ

| Phase | 内容 | コミット |
|-------|------|---------|
| 0 | ESLint hex色禁止 + check-css-hardcoded-colors.js + check-dark-parity.js | `271308e` |
| 1・2 | 全ファイルの hex色違反修正 | `5b13658` |
| 3 | var() フォールバック hex 排除・ダークモード変数追加 | `68bd464` |
| 4 | opacity / zIndex 数値禁止 ESLint + check-css-hardcoded-values.js | `17b784d` |
| 5 | sidebar/badge padding トークン化・width/height/minWidth 数値禁止 ESLint | この ADR 作成時 |

---

## トークン構造（2層）

```
src/tokens.css     — スケール・セマンティック・コンポーネントトークン（色以外）
src/index.css      — カラートークン（:root ライト / :root.force-dark ダーク）
```

### コンポーネントトークン（tokens.css）

| トークン | 値 | 用途 |
|---------|----|------|
| `--sidebar-item-padding-collapsed` | `11px 14px` | サイドバー折り畳み時 |
| `--sidebar-item-padding-expanded`  | `11px 20px` | サイドバー展開時 |
| `--sidebar-sub-item-padding`       | `8px 16px 8px 56px` | サブナビアイテム |
| `--badge-padding-y` | `var(--space-2px)` | バッジ縦余白 |
| `--badge-padding-x` | `var(--space-2)` | バッジ横余白 |
| `--min-width-input-md` | `200px` | 検索バー等の中型入力 |
| `--input-width-month` | `60px` | 2桁数値入力（月） |
| `--input-width-qty`   | `70px` | 数量入力 |
| `--input-width-weight`| `80px` | 重量・小数点入力 |
| `--input-width-year`  | `90px` | 年・金額入力 |

---

## 強制ルール

### ESLint（frontend/eslint.config.js）

| 対象 | ルール |
|------|--------|
| hex色 | `style={{ color: "#fff" }}` → 禁止 |
| opacity | `style={{ opacity: 0.5 }}` → 禁止 |
| zIndex | `style={{ zIndex: 50 }}` → 禁止 |
| width | `style={{ width: 24 }}` → 禁止（文字列は許可） |
| height | `style={{ height: 24 }}` → 禁止（文字列は許可） |
| minWidth | `style={{ minWidth: 120 }}` → 禁止（文字列は許可） |

### npm scripts（frontend/package.json）

| コマンド | 内容 |
|---------|------|
| `check:css-colors` | CSS ファイルの hex 色ハードコード検出 |
| `check:css-var-fallbacks` | var() フォールバック hex 禁止 |
| `check:css-values` | opacity / border-radius / z-index 数値ハードコード検出 |
| `check:dark-parity` | :root と :root.force-dark の変数一致検査 |
| `check:all` | 上記全実行 |

---

## 許可される例外

1. **パーセンテージ文字列**: `width: "100%"`, `height: "auto"` — 数値ではなく文字列なので ESLint 対象外
2. **@media ブレークポイント**: CSS 変数は @media 条件式で使用不可。`constants/breakpoints.ts` と `tokens.css` で値を同期管理
3. **ComingSoonPage 64px アイコン**: 1箇所のみの特殊値。tokens.css コメントに記録済み
4. **calc() 式**: `width: "calc(100% - var(--sidebar-width-expanded))"` — 文字列なので ESLint 対象外
5. **opacity: 0 / opacity: 1**: 可視性の完全オン/オフ（アニメーション @keyframes、tooltip 表示制御、アクセシビリティ対応など）は `0` と `1` のみ直書き許可。`--opacity-*` トークンは中間値（0.5等）専用

---

## 新規トークン追加手順

1. `src/tokens.css` の `:root {}` に追加
2. 色トークンの場合は `src/index.css` の `:root {}` と `:root.force-dark {}` 両方に追加
3. `npm run check:dark-parity` でパリティ確認
4. この ADR の「コンポーネントトークン」表を更新

---

## 関連 ADR

- ADR-022: Meta Business Suite 風 UI リデザイン
- ADR-027: UI 国際化（i18n）
- ADR-033: ライト/ダークテーマ切り替え
- ADR-068: プラットフォームブランドアセット管理

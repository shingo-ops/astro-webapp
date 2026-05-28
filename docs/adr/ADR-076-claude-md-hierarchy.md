# ADR-076: CLAUDE.md 階層構造標準化 + サイズ上限改定

- **Status**: Accepted
- **Date**: 2026-05-28
- **Author**: Claude Code (Hikky-dev)
- **PO**: しんごさん

---

## 背景

`backend/CLAUDE.md` の行数上限（45行）が実際のルール需要を下回り、ルール追加のたびに具体例（✅/❌）が圧縮・削除される問題が発生した。圧縮によって AI エージェントの判断材料が失われ、誤実装リスクが生じる。また、CI の「CLAUDE.md line count check」が Branch Protection の必須チェックに未登録のため、CI 失敗でも PR がマージできる状態だった。

---

## 決定

### 1. サイズ上限の改定

| ファイル | 旧上限 | 新上限 | 理由 |
|---------|-------|-------|------|
| `backend/CLAUDE.md` | 45行 | 70行 | 必要なルール量に対してバッファが不足していた |
| `frontend/CLAUDE.md` | 60行 | 90行 | 同上（frontend 固有ルールは DSL 例示を含むため） |
| `CLAUDE.md`（ルート） | 120行 | 120行 | 変更なし |

### 2. 階層構造の標準化（CLAUDE.md 命名規則）

詳細ルールをサブディレクトリの CLAUDE.md に分割できる。命名規則:

```
backend/CLAUDE.md              ← 要約（上限70行）
backend/db/CLAUDE.md           ← DB・マイグレーション詳細（必要になったら作成）
backend/tenant/CLAUDE.md       ← テナント操作詳細（必要になったら作成）

frontend/CLAUDE.md             ← 要約（上限90行）
frontend/components/CLAUDE.md  ← コンポーネントルール詳細（必要になったら作成）
```

**ファイル名は必ず `CLAUDE.md` にすること。** 他の名前（`migration.md` 等）は Claude Code が自動ロードしない。

### 3. CI 監視対象の拡張

- トリガーパスを `**/CLAUDE.md`（全サブディレクトリ対応）に変更
- `check-claude-size.js` に未登録 CLAUDE.md の自動検出警告を追加
- 新規 CLAUDE.md を追加した場合は `LIMITS` 配列に登録すること

### 4. CI を Branch Protection 必須チェックに登録

`CLAUDE.md line count check` を develop・main 両 Ruleset の `required_status_checks` に追加。CI 失敗時はマージ不可。

---

## 理由

1. **ルール品質の保持**: 上限が小さすぎると具体例が削除され AI の判断精度が低下する
2. **Anthropic 公式推奨**: 200行超で AI の遵守率が低下すると公式ドキュメントに明記
3. **命名規則の統一**: `CLAUDE.md` という名前のファイルのみ Claude Code が自動ロードする（公式仕様）
4. **機械的強制**: CI を必須チェックにしないと超過しても PR がマージできてしまう

---

## 外部エビデンス

| 事例 | 内容 | 効果 |
|------|------|------|
| Anthropic 公式 | CLAUDE.md は 200行以内推奨。4段階階層をサポート | 公式仕様として確認済み |
| 個人実践事例 | 471行 → 61行（87%削減）で AI 一貫性が顕著に改善 | 分割による整理効果 |
| OpenAI AGENTS.md | 150行以下を目標、200行超でサブディレクトリ分割推奨 | 類似ツールでの同方針 |

---

## 否定した選択肢

| 選択肢 | 否定理由 |
|--------|---------|
| テキストリンク方式（`詳細: rules/migration.md`） | Claude Code はリンク先ファイルを自動読み込みしない（公式仕様） |
| 上限据え置き（45行/60行維持） | ルール追加ごとに圧縮が繰り返される根本原因を解消できない |
| @import 記法 | コンテキスト削減にならない（展開してインライン挿入される）。管理複雑性が増す |

---

## 強制の仕組み

| 仕組み | 担当ファイル | 効果 |
|--------|------------|------|
| サイズチェック CI | `.github/workflows/check-claude-size.yml` | PR 時に全 CLAUDE.md を検査 |
| サイズチェックスクリプト | `frontend/scripts/check-claude-size.js` | 未登録 CLAUDE.md の自動検出警告 |
| pre-commit フック | `frontend/.husky/pre-commit` | コミット前にローカルで検査 |
| Branch Protection | develop Ruleset #16619490 / main Ruleset #15777895 | CI 失敗時にマージ不可 |

---

## 関連

- `frontend/scripts/check-claude-size.js` — サイズチェックスクリプト本体
- `.github/workflows/check-claude-size.yml` — CI ワークフロー
- ADR-012 — What/How 分離（CLAUDE.md を薄く保つ方針の起点）

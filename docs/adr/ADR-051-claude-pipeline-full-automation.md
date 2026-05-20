# ADR-051: claude-pipeline Full Automation — Reviewer / Evaluator Auto-Trigger

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `.github/workflows/claude-pipeline.yml` / `docs/proposals/agents-role-clarification-prompt.md`
- **関連 ADR**: ADR-042 (4 エージェント体制), ADR-048 (Web Claude 位置づけ), ADR-050 (Release PR workflow)

---

## 1. 背景

エビデンス調査結果:

| フェーズ | 現状の自動化 |
|---|---|
| Generator (実装 + PR 作成) | ✅ 自動 (claude-pipeline.yml `claude-worker` job) |
| Reviewer (コードレビュー) | ❌ 手動 (人間が Terminal CC に指示) |
| Evaluator (UI/UX 評価) | ❌ 手動 (人間が Terminal CC に指示) |
| merge | ✅ 手動 (しんごさん、設計通り) |

`claude-pipeline.yml` の job は `claude-worker` 単一のみ。Reviewer / Evaluator ジョブが定義されていない。`agents-role-clarification-prompt.md` でも CLAUDE.md でも、Reviewer / Evaluator は「手動起動」が暗黙の正規仕様だった。

これはしんごさん環境・パートナー (ひとし) 環境の両方で同じ。人間が PR ごとに「Reviewer 起動 → 結果待ち → Evaluator 起動 → 結果待ち → merge」と細かい操作を繰り返している。

**正規フローの本来の姿**:

```
ADR push → claude-pipeline 自動起動
  → Generator が実装 + PR 作成
  → Reviewer 自動起動 → APPROVE / REQUEST_CHANGES
  → Evaluator 自動起動 (Skip 宣言なら飛ばす)
  → 両 APPROVE 完了通知 (Discord)
  → 人間が diff 確認 + merge
```

---

## 2. 決定（What）

### 2-1. claude-pipeline.yml に 2 job 追加

既存の `claude-worker` job (Generator) に加えて、以下 2 job を追加:

```yaml
jobs:
  claude-worker:
    # 既存 Generator job (変更なし)

  reviewer:
    needs: claude-worker
    if: ${{ needs.claude-worker.outputs.pr_number != '' }}
    runs-on: ubuntu-latest
    steps:
      - Run Claude Code as Reviewer
        # claude -p with reviewer agent
        # input: PR number, ADR path
        # output: gh pr review <PR> --approve / --request-changes
      - Discord 通知 (Reviewer 結果)

  evaluator:
    needs: reviewer
    if: ${{ needs.reviewer.outputs.decision == 'APPROVED' }}
    runs-on: ubuntu-latest
    steps:
      - Check PR body for Evaluator method
        # Skip 宣言ありなら gh pr review --approve で終了
      - Run Claude Code as Evaluator (Layer 1)
        # claude -p with evaluator agent
        # input: PR number
        # output: gh pr review <PR> --approve / --request-changes
      - Discord 通知 (Evaluator 結果 / 最終 merge 待ち通知)
```

### 2-2. トリガー条件

| トリガー | 起動する job |
|---|---|
| ADR push (`docs/adr/ADR-*.md` 追加) | claude-worker → reviewer → evaluator |
| PR への commit push (修正 push) | reviewer → evaluator (claude-worker は走らない) |
| `gh pr review --request-changes` 後の修正 push | reviewer → evaluator (再判定) |

### 2-3. REQUEST_CHANGES 時のフロー

```
Reviewer REQUEST_CHANGES
  → claude-pipeline が Generator job を再起動
  → Generator が同じ PR ブランチに修正 push
  → Reviewer 再判定
  → APPROVE なら Evaluator へ
```

これは ADR-042 の「Generator は同じ PR ブランチに修正 push、新 PR を作らない」と整合。

### 2-4. agents-role-clarification-prompt.md への反映

「フロー全体図」と「Reviewer / Evaluator の起動」セクションを **「自動起動」** に書き換える:

```markdown
## 起動方法 (ADR-051 以降)

| エージェント | 起動 |
|---|---|
| Generator | claude-pipeline.yml `claude-worker` job (自動) |
| Reviewer | claude-pipeline.yml `reviewer` job (自動) |
| Evaluator | claude-pipeline.yml `evaluator` job (自動) |
| 最終 merge | 人間 (手動) |

人間が個別に Terminal CC に「reviewer.md でレビューしてくれ」と指示する必要は **ない**。
PR が立った時点で自動的に Reviewer → Evaluator が順次起動する。
```

### 2-5. 既存 grep 11 項目への追加

```bash
# 新規追加 (ADR-051)
grep -c "claude-pipeline.yml.*自動" ~/.claude/agents/reviewer.md
grep -c "claude-pipeline.yml.*自動" ~/.claude/agents/evaluator.md
```

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | しんごさん・ひとしさん両環境の手動起動負荷をゼロにする | 最優先 |
| 2 | Web Claude が PR ごとに「Reviewer 起動指示文」「Evaluator 起動指示文」を生成する冗長な往復を解消 | 高 |
| 3 | ADR-042 が定義した 4 エージェント体制の理想形を完成させる | 高 |

---

## 4. Scope 外

- Generator job (claude-worker) の **既存ロジック変更** (修正なし、needs 関係を追加するのみ)
- Reviewer / Evaluator の **判断ロジック変更** (既存 `~/.claude/agents/*.md` を流用)
- 最終 merge の自動化 (人間が判断、ADR-042 §設計通り)
- Discord 通知フォーマットの全面刷新 (新規通知の追加のみ)
- self-hosted runner / GitHub-hosted runner の切り替え議論
- Playwright MCP の環境構築 (Evaluator が Layer 1 を実行できない問題は別 ADR)

---

## 5. 事業上の制約

- ADR-042 / ADR-048 / ADR-050 の運用を破壊しない
- `agents-role-clarification-prompt.md` の grep 11+2 項目 (ADR-050 で追加済) を破壊しない
- 既存の `--delete-branch` 判定ルール (ADR-050) を Reviewer / Evaluator の自動提案にも適用
- しんごさん環境とひとしさん環境の出力が等価 (ADR-048 §2-3)
- Web Claude は ADR ファイルの直接 commit/push しない (ADR-048 §5-1)

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright — workflow YAML 変更は UI なしだが、新 job 自体の動作確認が必要
- [ ] Layer 2: Claude in Chrome — 不要
- [ ] Skip — 該当しない (新 job の実動作確認が必要)

実体的には Evaluator は claude-pipeline.yml の **新 job が実際に起動する PR を 1 本通す** ことで動作確認となる。

### Reviewer 追加観点

- [ ] `.github/workflows/claude-pipeline.yml` に `reviewer` job と `evaluator` job が定義されている
- [ ] `needs:` 関係が claude-worker → reviewer → evaluator になっている
- [ ] `if:` 条件が正しい (PR 番号取得失敗時に reviewer が走らない、REQUEST_CHANGES 時に evaluator が走らない)
- [ ] PR 本文の Evaluator method 宣言を読み取って Skip 判定するロジックがある
- [ ] Discord 通知が各 job で発火する
- [ ] `agents-role-clarification-prompt.md` の起動方法セクションが更新されている

### 動作確認 (人間)

ADR-051 マージ後、次の本物 ADR (例: 何でもよい小規模 ADR) を 1 本通して:

1. ADR push 後、Generator が自動起動するか
2. PR open 後、Reviewer が自動起動するか
3. Reviewer APPROVE 後、Evaluator が自動起動するか
4. Evaluator が Skip 宣言を正しく判定するか
5. 両 APPROVE 後、Discord に「merge 待ち」通知が来るか
6. しんごさんが Terminal CC に Reviewer 起動指示を **出さなくて済む** か

---

## 7. 3 点セット要件

該当しない (外部システムとの新規状態共有なし、内部 CI ワークフロー拡張のみ)。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. 現状維持 (手動起動継続) | ❌ 却下。両環境で人間負荷継続、Web Claude 往復冗長化 |
| B. Reviewer のみ自動化、Evaluator は手動 | ❌ 却下。中途半端、Evaluator Skip 判定も自動化したい |
| C. 別ワークフロー (reviewer-pipeline.yml / evaluator-pipeline.yml) として分離 | △ 検討余地あるが管理対象が増える |
| **D. claude-pipeline.yml に job 追加 (本案)** | ✅ 採用。単一ワークフローで完結 |

---

## 9. 未決事項 (Generator 判断に委ねる)

- Reviewer / Evaluator job の self-hosted runner 利用可否 (claude-worker と同じ runner で問題ない想定)
- claude -p のプロンプト構築 (Reviewer / Evaluator の入力フォーマット)
- Discord 通知の文言 (既存通知パターンに合わせる)
- REQUEST_CHANGES → Generator 再起動のトリガー方法 (PR comment trigger or push trigger)
- Reviewer / Evaluator job がタイムアウトした場合のリトライ戦略
- Playwright MCP の環境構築が必要な場合のフォールバック (Layer 1 HTML 解析、現状で PR #405 / #408 で実績あり)

---

## 10. 起案者の認知限界

- `claude-pipeline.yml` の最新版は web_fetch で取得不可、しんごさんが Terminal CC で内容確認した結果に依拠
- Generator が `claude -p` を使う具体的なプロンプト形式は未確認 (現実装の `claude-worker` step を Generator が読んで判断)
- self-hosted runner のキャパシティ (並列 job 数の制限) は未確認
- Evaluator が Playwright MCP 不在環境で実行された場合の挙動は PR #405/#408 実績ベース (HTML 解析代替で APPROVE 出していた)
- ADR-051 自体を実装する PR が立った時、その PR が ADR-051 の自動化対象になる「自己適用」状態が発生 → 初回は手動起動、2 回目以降は自動という移行が必要
- 番号衝突確認は Terminal CC が `ls docs/adr/ADR-*.md | sort | tail -5` で実施

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

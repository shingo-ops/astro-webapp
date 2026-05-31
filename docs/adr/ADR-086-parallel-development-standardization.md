# ADR-086: 複数エージェント並行開発の標準化 — worktree / AEON / Evidence Registry / Release Gate

- **Status**: Proposed
- **Date**: 2026-05-31
- **Deciders**: shingo-ops (PO), Claude Code / Codex
- **Related**: ADR-074, ADR-076, ADR-081, ADR-042, ADR-056

---

## Context（背景）

Sales Anchor では、Claude Code と Codex を並行稼働させる前提が既にある。
しかし、並行作業の「入口」「実行」「証拠」「リリース」が複数の文書とスクリプトに分散しており、
以下の無駄が繰り返し発生しやすかった。

1. 同じ feature ブランチを別ターミナルで共有してしまう
2. worktree 外で作業を始めて、ブランチ干渉や編集消失が起きる
3. 実行根拠がチャット履歴に残るだけで、後から再現できない
4. `develop -> main` の後に `main -> develop` の back-merge を忘れやすい
5. Reviewer / Evaluator / release の責務境界が曖昧になりやすい

既に以下の仕組みは存在する。

- `scripts/new-worktree.sh`
- `scripts/validate-worktree-start.sh`
- `scripts/check-active-work-format.sh`
- `scripts/check-stale-worktrees.sh`
- `scripts/aeon-dispatch.sh`
- `scripts/aeon-delivery.sh`
- `scripts/aeon-release.sh`
- `.claude-pipeline/active-work.md`
- `tasks/todo.md`
- `docs/ai-agents/evidence-registry.md`
- `docs/PARALLEL_TERMINAL_GUIDE.md`
- `docs/ai-agents/aeon-operation.md`
- `docs/agents/governance.md`

ただし、**「どれを正本として、どの順番で使うか」** が1枚にまとまっていないと、定着と再利用が弱い。
そこで、並行開発の標準を1つの ADR として固定する。

---

## Decision（決定）

複数エージェント並行開発は、次の 4 層を正本として標準化する。

### 1. 実行の正本

- **作業開始は必ず `bash scripts/new-worktree.sh feature/morimoto/<topic>` から始める**
- feature ブランチ作業は **1 ブランチ = 1 worktree** に固定する
- worktree 外での feature 作業は `scripts/validate-worktree-start.sh` でブロックする

### 2. 占有の正本

- 進行中の作業は `.claude-pipeline/active-work.md` に記録する
- ここを並行作業の **唯一の真実（SSoT）** とする
- 新規 worktree 作成時は自動登録し、終了時は削除する
- 重複が見つかったら STOP して開始しない

### 3. 進捗と証拠の正本

- タスクの現在地・次の一手・根拠は `tasks/todo.md` に記録する
- 実行根拠、コマンド出力、PR、merge commit、レビュー結果は `docs/ai-agents/evidence-registry.md` に記録する
- 「チャットで覚えている」は証拠にしない

### 4. delivery / release の正本

- 実装の実行は `scripts/aeon-delivery.sh`
- main 反映は `scripts/aeon-release.sh`
- delivery と release を混ぜない
- `develop -> main` の後は、**同じ運用日に `main -> develop` の back-merge を完了させる**
- release は merge commit で行う（squash 禁止）

---

## Standard Operating Flow

```text
1. tasks/todo.md を読む
2. .claude-pipeline/active-work.md を読む
3. 関連 runbook を読む
4. bash scripts/new-worktree.sh feature/morimoto/<topic>
5. bash scripts/validate-worktree-start.sh
6. 必要なら scripts/aeon-dispatch.sh / scripts/aeon-delivery.sh で実装・調査
7. evidence-registry.md に一次情報を残す
8. PR を作成する
9. Reviewer / Evaluator を通す
10. scripts/aeon-release.sh で main へ昇格する
11. main 反映後に back-merge を完了する
12. tasks/todo.md と active-work.md を閉じる
```

---

## Evidence Requirements（成功判定の証拠）

並行開発を「成功した」と扱うには、最低限次の証拠が必要。

| 証拠 | 何を示すか |
|------|------------|
| worktree path | 他ターミナルと分離された個室で作業した |
| `.claude-pipeline/active-work.md` | 同じ機能エリアの重複がなかった |
| `tasks/todo.md` | 現在地・次の一手・根拠が明示されていた |
| PR 番号 | 変更がレビュー対象になった |
| Reviewer の承認 | 設計レビューが通った |
| CI 成功 | 実装が自動検証に通った |
| merge commit SHA | main / develop に実際に入った |
| `docs/ai-agents/evidence-registry.md` | 根拠が一次情報として残った |

証拠が欠ける場合は、成功ではなく `CONTINUE_OBSERVATION` と扱う。

---

## Operational Policy（運用ルール）

- 1つのエージェントは 1 つの worktree だけを使う
- 同じ feature ブランチを複数エージェントで共有しない
- 同じタスクに対して複数の release lane を走らせない
- 既存の back-merge が残っている場合、次の release PR は作らない
- 変更の説明は、ファイル・PR・コマンド出力で裏付ける
- 例外運用は `docs/ai-agents/evidence-registry.md` に明記する

---

## Governance Review Program

```yaml
Governance Review Program:
  Policy: 複数エージェント並行開発の標準化
  Owner: shingo-ops
  Start Date: 2026-05-31
  End Date: 2026-08-31
  Observation Period: 90 days
  Review Frequency: Weekly
  Review Count: 4
  Review Location: docs/ai-agents/evidence-registry.md
  Evidence Sources:
    - tasks/todo.md
    - .claude-pipeline/active-work.md
    - PR history
    - merge commit SHA
    - scripts/check-task-state.sh
    - scripts/check-active-work-format.sh
    - scripts/check-stale-worktrees.sh
  Why Review: 並行作業の無駄、衝突、back-merge 手戻りが減っているかを確認するため
  What To Review:
    - 同一ブランチ重複
    - stale worktree 件数
    - back-merge 遅延
    - PR rework rate
    - CI failure rate
  How To Review:
    - 先週比 / 直近 4 週平均で比較する
    - 根拠がない場合は保留にする
  How Much To Review:
    - 週次で完了 PR の代表サンプルを確認する
  KGI: AEON Mainline Delivery Completion Rate
  KPI:
    - worktree 逸脱件数
    - back-merge 遅延件数
    - evidence 欠落件数
    - PR rework rate
  Success Criteria:
    - worktree 逸脱 0
    - evidence 欠落 0
    - back-merge 遅延の反復なし
    - release PR が Reviewer / CI を通過
  Failure Criteria:
    - 同じブランチの重複
    - 監査証跡なしの完了報告
    - back-merge の反復忘れ
  Completion Criteria:
    - 90 日の観測で安定
    - 標準化が運用側に定着
  Root Cause Trigger:
    - 同じ失敗が 3 回以上再発
    - 数値が 20% 以上悪化
  Standardization Decision: STANDARDIZE
```

---

## Consequences（影響）

### 得られること

- 作業開始時の迷いが減る
- 別ターミナルによる編集衝突を減らせる
- PR のレビュー対象が小さくなる
- 証拠が残るので、後から再現しやすい
- release / back-merge の抜け漏れを減らせる

### 失うこと・注意点

- `tasks/todo.md` と `evidence-registry.md` の更新が必須になる
- release は serial になるので、同時に複数本は走らせない
- worktree cleanup を怠ると stale entry が増える

---

## Acceptance Criteria

- [ ] `scripts/new-worktree.sh` 起点の作業開始が標準手順として文書化されている
- [ ] `.claude-pipeline/active-work.md` が並行作業の SSoT として文書化されている
- [ ] `tasks/todo.md` と `docs/ai-agents/evidence-registry.md` の役割分担が明確である
- [ ] `develop -> main` と `main -> develop` の順序が標準化されている
- [ ] Governance Review Program が明記され、継続観測の条件が定義されている


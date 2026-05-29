# AEON Operation Guide

`Claude Code` から同じ terminal session で `Codex` を呼び、AEON の delivery から release までを回すための正本手順。

## Purpose

- 同一ターミナルから AEON を起動する手順を固定する
- delivery と release の責務を分離する
- 実行根拠を `docs/ai-agents/evidence-registry.md` に残す

## Canonical Commands

```bash
bash scripts/aeon-delivery.sh --smoke "AEON smoke validation: start all stages and return no-op reports only. Do not modify files. Do not inspect beyond what is needed to confirm the runner path. Stop after the stage sequence completes or the first blocker is found."
bash scripts/aeon-delivery.sh "..."
bash scripts/aeon-release.sh [PR番号]
```

## Fixed Flow

1. `research`
2. `planner`
3. `architect`
4. `generator`
5. `evaluator`
6. `reviewer`
7. `release` は必要時のみ別実行

## Role Routing

| Role | Entry |
|------|-------|
| `research` | `scripts/codex-research.sh` |
| `planner` | `scripts/codex-planner.sh` |
| `architect` | `scripts/codex-architect.sh` |
| `generator` | `scripts/codex-generator.sh` |
| `evaluator` | `scripts/codex-evaluator.sh` |
| `reviewer` | `scripts/codex-reviewer.sh` |
| `release` | `scripts/aeon-release.sh` |

## Preconditions

- `tasks/todo.md` を読む
- `.claude-pipeline/active-work.md` を読む
- 関連 runbook を読む
- `scripts/validate-worktree-start.sh` が通る状態である

## Completion Criteria

- `aeon-delivery.sh` が最後まで到達する
- `generator` が PR を作成する
- `reviewer` が結果を返す
- `main` 昇格は `scripts/aeon-release.sh` で別実行する

## Operational Rules

- `delivery` と `release` を混ぜない
- `main` への昇格は Reviewer とは別の明示ステップにする
- 実行根拠と例外は `docs/ai-agents/evidence-registry.md` に記録する
- smoke validation は起動経路確認用であり、実装差分の評価ではない

## Evidence

この運用方針は `scripts/aeon-delivery.sh`, `scripts/aeon-release.sh`, `docs/ai-agents/aeon-routing.md`, `docs/ai-agents/kpi.md`, `docs/ai-agents/evidence-registry.md` で裏付ける。

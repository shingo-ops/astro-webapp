# AEON Routing

Claude Code から同一ターミナルで AEON エージェントを起動するための実行ルート定義。
正本の運用手順は [AEON Operation Guide](./aeon-operation.md) を参照する。

## Goal

- `Claude Code` が shell から `Codex` 担当エージェントを呼び出せること
- そのまま PR 作成、Evaluator、Reviewer、release を経由して `main` まで到達できること
- 途中の決定根拠は `docs/ai-agents/evidence-registry.md` に残すこと

## Entry Point

Single entry point:

```bash
bash scripts/aeon-dispatch.sh <role> [prompt...]
```

For end-to-end delivery, use:

```bash
bash scripts/aeon-delivery.sh [--generator=exec|auto|interactive] [prompt...]
```

For release to main, use:

```bash
bash scripts/aeon-release.sh [PR番号]
```

Supported roles:

| Role | Runtime target | Notes |
|------|----------------|------|
| `generator` | `scripts/codex-generator.sh` | スプリント実装用。`--auto` で自動承認モードを使える |
| `research` | `scripts/codex-research.sh` | non-interactive Codex research |
| `planner` | `scripts/codex-planner.sh` | non-interactive Codex planning |
| `architect` | `scripts/codex-architect.sh` | implementation readiness check |
| `reviewer` | `scripts/codex-reviewer.sh` | PR / sprint review |
| `evaluator` | `scripts/codex-evaluator.sh` | Playwright-based evaluation |
| `release` | `scripts/aeon-release.sh` | main への安全な昇格 |

## Same-Terminal Rule

- すべての AEON 呼び出しは、`Claude Code` が動いている同じ terminal session から起動する
- 別ターミナルの TUI 起動は必須ではない
- `scripts/aeon-dispatch.sh` は `codex exec` / `codex-generator.sh` を子プロセスとして起動する
- `scripts/aeon-delivery.sh` は research → planner → architect → generator → evaluator → reviewer を同じ terminal session で順に起動する
- `scripts/aeon-release.sh` は Reviewer で APPROVED になった PR を main へ安全に昇格する

## Delivery KGI

The top-level KGI for this route is `AEON Mainline Delivery Completion Rate` in `docs/ai-agents/kpi.md`.

Observed sequence:

1. `Claude Code` dispatches a role
2. `Codex` completes the requested AEON task
3. Local commit is created when applicable
4. PR is opened
5. Evaluator passes
6. Reviewer approves
7. `scripts/aeon-release.sh` で main へ merge commit される
8. `main` への反映完了

## Operational Notes

- `research / planner / architect / reviewer / evaluator` use non-interactive Codex wrappers
- `generator` uses the existing interactive Codex wrapper
- `release` uses the safe merge wrapper and requires a main-targeted PR
- Use `docs/ai-agents/evidence-registry.md` to log any routing change or exception

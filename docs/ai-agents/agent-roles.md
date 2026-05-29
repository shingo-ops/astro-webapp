# AI Agent Roles

Canonical runtime definitions live in `.claude/agents/`.
Detailed reference docs live in `docs/agents/`.
Canonical output schemas live in `docs/schemas/`.

This file remains a lightweight index for the older `docs/ai-agents/` operating notes.

Sales Anchor の Codex CLI 運用では、Agent ごとに責務・権限・読取範囲を分離する。デフォルトは `gpt-5`、深い調査・設計・Governance のみ `gpt-5.5` を使う。`o4-mini` は使用禁止。

## Common Rules

- 対象範囲を明示してから作業する
- repo 全体探索は禁止する
- `.env`、secret、auth token、API key は読まない・書かない
- `node_modules`、`.next`、`dist`、`build`、`coverage` は探索しない
- すべての提案に `evidence` / `confidence` / `tradeoff` を含める

## Roles

| Agent | Profile | Responsibility | Permission | Canonical definition |
|-------|---------|----------------|------------|----------------------|
| Research | `research` | Evidence Package Generator | read-only | `.claude/agents/research.md` |
| Planner | `planner` | Evidence Based Design Planner | read-only | `.claude/agents/planner.md` |
| Architect | `architect` | Implementation Readiness Architect | read-only | `.claude/agents/architect.md` |
| Generator | `generator` | Scoped Implementation Agent | workspace-write | `.claude/agents/generator.md` |
| Reviewer | `reviewer` | Implementation Compliance Reviewer | read-only | `.claude/agents/reviewer.md` |
| Evaluator | `evaluator` | Playwright Evidence Agent | read-only | `.claude/agents/evaluator.md` |
| Governance | `governance` | Development Operating System Owner | read-only | `.claude/agents/governance.md` |

## Handoff Contract

各 Agent は次の形式で次工程へ渡す。

```text
scope:
  included:
  excluded:
evidence:
  - path:
    finding:
confidence: high | medium | low
tradeoff:
next_agent:
requested_action:
```

## Escalation

対象外ファイルの読取、追加ファイル作成、広範囲検索、外部ネットワーク、不可逆操作が必要な場合は、理由・対象・上限・代替案を提示して確認を取る。

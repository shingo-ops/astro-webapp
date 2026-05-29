# AEON Delivery Flow

`Claude Code` から同じ terminal session で AEON の delivery flow を進めるための手順。
正本の運用手順は [AEON Operation Guide](./aeon-operation.md) を参照する。

## Goal

- `Claude Code` から `Codex` を呼び出し、研究・設計・実装・評価・レビューまでを同じ端末で回す
- delivery の根拠を `docs/ai-agents/evidence-registry.md` に残す
- PR 作成までを自動化し、最終 merge は `scripts/aeon-release.sh` で安全に行う

## Entry Point

```bash
bash scripts/aeon-delivery.sh [--generator=exec|auto|interactive] [prompt...]
```

Default mode:

- `generator=exec`
- research / planner / architect / evaluator / reviewer are dispatched non-interactively through Codex wrappers

## Sequence

1. `research`
2. `planner`
3. `architect`
4. `generator`
5. `evaluator`
6. `reviewer`

## Notes

- `generator=exec` is the default to keep the flow scriptable
- `generator=auto` preserves the existing auto-approval wrapper behavior
- `generator=interactive` is available when a human wants to steer the implementation manually
- `generator` opens the PR after the implementation is committed
- merge is a separate release action and should use `scripts/aeon-release.sh`

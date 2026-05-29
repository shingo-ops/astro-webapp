# AEON Release

`Claude Code` から同じ terminal session で AEON delivery の PR を `main` へ安全に昇格するための手順。
正本の運用手順は [AEON Operation Guide](./aeon-operation.md) を参照する。

## Goal

- `scripts/aeon-delivery.sh` で作成された PR を、`main` 向けの安全な release 入口で昇格する
- merge は `merge commit` で行い、branch protection と整合させる
- release の判断根拠を `docs/ai-agents/evidence-registry.md` に残す

## Entry Point

```bash
bash scripts/aeon-release.sh [PR番号]
```

If PR number is omitted, the script reads `.pr-number` from the current worktree.

## Checks

1. `scripts/validate-worktree-start.sh`
2. Current PR has `baseRefName == main`
3. Current PR has `reviewDecision == APPROVED`
4. Current PR has `mergeStateStatus == CLEAN`
5. `.pr-number` matches the owned PR when present
6. `gh-pr-merge-safe.sh` performs the ownership-safe merge

## Notes

- release is a separate action from delivery
- use `scripts/aeon-delivery.sh` to reach the PR / review stage
- use `scripts/aeon-release.sh` only after Reviewer approval and the repo policy checks

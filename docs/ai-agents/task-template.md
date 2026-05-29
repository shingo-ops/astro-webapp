# AI Agent Task Template

Codex Agent に作業を渡すときは、対象範囲と禁止事項を先に固定する。

```text
task:
agent: research | planner | generator | reviewer | evaluator | governance
profile:
objective:

scope:
  read:
    - 
  write:
    - 
  excluded:
    - .env
    - node_modules
    - .next
    - dist
    - build
    - coverage

constraints:
  - repo 全体探索禁止
  - secrets / auth 情報を読まない・書かない
  - o4-mini 使用禁止

required_output:
  - evidence:
  - confidence: high | medium | low
  - tradeoff:
  - changed_files:
  - verification:

acceptance_criteria:
  - 

handoff:
  next_agent:
  requested_action:
```

## タスク台帳レコード（tasks/todo.md 用）

進行中タスクを `tasks/todo.md` の表に登録するときのフォーマット。
**全フィールド必須**。空欄・「???」・「TBD」は `check-task-state.sh` がエラーとして検出する。

```text
| タスク名 | 担当 | 現在地 | 次の一手 | 根拠 | 更新日 |
```

| フィールド | 説明 | 有効な値の例 |
|----------|-----|-----------|
| タスク名 | ADR番号またはチケット名を含む簡潔な名前 | `監視VPS移行（ADR-080）` |
| 担当 | 実行者またはブロック理由 | `Agent` / `PO待ち` / `CI待ち` |
| 現在地 | ファイル確認またはコマンド実行で確認した現在の状態 | `M1未着手（VPS未契約）` |
| 次の一手 | 次に実行する具体的アクション（抽象的な「進める」は不可） | `runbook Phase 1 Step 1-1 を実行` |
| 根拠 | 現在地の確認に使った一次情報 | `PR #1134 マージ確認済み` / `ADR-080 §Phase1 参照` |
| 更新日 | この行を最後に更新した日付（YYYY-MM-DD） | `2026-05-29` |

### 完了行の移動

タスクが完了したら「## 完了（直近）」テーブルに移動し、完了日と PR を記入する。
完了後 30 日を超えた行は削除してよい。

---

## Generator Addendum

Generator に渡す場合は、Planner が変更可能ファイルを明示する。

```text
allowed_write_files:
  - path:
    reason:
    verification:

change_budget:
  max_files:
  max_lines:
  forbidden_changes:
    - unrelated refactor
    - dependency install
    - destructive operation
```

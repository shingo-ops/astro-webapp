# ADR-074: Worktree強制によるエージェントPR混入防止

- **ステータス**: Accepted
- **起案日**: 2026-05-26
- **起案者**: shingo-ops (PO)
- **決定者**: Claude Code (Hikky-dev)

---

## 背景（What / Why）

並行稼働する複数のAIエージェントが、互いの変更を含めてPRを作成してしまう事例が発生した。
エージェントAがエージェントBの変更もまとめてコミット・PRするため、レビューが困難になり、
誤ったコードが混入するリスクがあった。

根本原因は2つ:
1. **共有作業ディレクトリ**: エージェントがメインリポジトリで作業すると、同一ディレクトリに複数エージェントの変更が混在する
2. **ブランチ変更干渉**: エージェントBが `git checkout` を実行すると、エージェントAのブランチが変わってしまう

---

## 決定事項（Decision）

**Gitのworktree機能を使い、各エージェントを物理的に独立したディレクトリ（個室）に隔離する。**
さらに、個室以外での作業開始・push を機械的にブロックする2層の強制チェックを導入する。

### 採用したアプローチ

| 層 | タイミング | スクリプト | 目的 |
|----|----------|----------|------|
| 始まり | 作業開始前 | `scripts/validate-worktree-start.sh` | メインリポジトリでの feature ブランチ作業をブロック |
| 終わり | push/PR前 | `scripts/validate-pr-ownership.sh` | worktree 外からの push をブロック |

**中央設定ファイル**: `.claude/agent-config.sh` に共通値を集約（Design Tokens と同じ思想）

---

## スコープ

**対象**:
- AIエージェント（Claude Code）による並行開発
- `feature/*` ブランチでの作業

**対象外**:
- `main` / `develop` ブランチでの確認・読み取り作業
- GitHub Actions CI（`GITHUB_ACTIONS=true` で自動スキップ）
- 人間開発者の通常作業（エラーメッセージで正しい手順を案内）

---

## 強制フロー

```
エージェント起動
    ↓
bash scripts/validate-worktree-start.sh
    ├── 失敗: 「個室を作ってから再起動して」と案内 → STOP
    └── 通過: 作業開始

... 実装 ...

git push / PR作成前
    ↓
bash scripts/validate-pr-ownership.sh（pre-push フック経由で自動実行）
    ├── 失敗: worktree 外 / 未登録 / develop 乖離 → STOP
    └── 通過: push 実行
```

---

## 実装ファイル

| ファイル | 役割 |
|---------|------|
| `.claude/agent-config.sh` | 共通設定の SSoT（worktree パス、ベースブランチ等） |
| `scripts/validate-worktree-start.sh` | 作業開始時チェック（始まりの防衛） |
| `scripts/validate-pr-ownership.sh` | push 前チェック（終わりの防衛） |
| `scripts/new-worktree.sh` | 個室（worktree）作成 + active-work.md 自動登録 |
| `frontend/.husky/pre-push` | validate-pr-ownership.sh の自動呼び出し |
| `~/.claude/scripts/worktree-only-guard.sh` | Claude Code PreToolUse フック（Edit/Write/Bash を自動インターセプト） |
| `.claude/agents/generator.md` | Step 0 に validate-worktree-start.sh 呼び出しを追加 |
| `.claude/agents/evaluator.md` | Step 0 に validate-worktree-start.sh 呼び出しを追加 |
| `.claude/agents/reviewer.md` | Step 0 に validate-worktree-start.sh 呼び出しを追加 |

---

## 自動リカバリー機能（2026-06-02 追加）

### 背景

メインリポジトリで起動した Claude Code が Edit/Write を試みるたびに `worktree-only-guard.sh` がブロックし、
Claude が手動で `new-worktree.sh` を実行してから再開するという「ブロック→リトライ」パターンが1日18件以上発生していた。

### 決定

`worktree-only-guard.sh` がブロック時に自動リカバリーを試みる3ケース分岐を追加した。

| ケース | 条件 | 動作 | ログイベント |
|--------|------|------|------------|
| 1 | このブランチの worktree が既に存在する | 既存パスを Claude に通知 | `worktree_redirect` |
| 2 | worktree が存在しない + ブランチが未チェックアウト | `git worktree add` で自動作成してパスを通知 | `worktree_auto_created` |
| 3 | ブランチがメインリポジトリでチェックアウト済み | `git checkout develop` → `new-worktree.sh` の2ステップ手順を表示 | `worktree_bypass_blocked` |

### 設計判断

- ケース2で `new-worktree.sh` を呼ばず `git worktree add` をインライン実行した理由：`new-worktree.sh` は `set -e` + `git fetch` を含むため、ネットワーク障害時にガードが予期しない exit 1 で終了するリスクがある
- 自動作成後も `exit 1` を返す（Claude に `cd` 先を伝えて移動させる）理由：Claude Code セッションの作業ディレクトリはフックスクリプトから変更できないため
- ケース3で自動作成を諦める理由：git は同一ブランチを複数 worktree でチェックアウトすることを禁止しているため

---

## 横展開（新しい開発者への配布）

`.claude/agents/` と `scripts/` はリポジトリに git 管理されているため、
`git pull` だけで全員に自動配布される。手動のセットアップは不要。

---

## ロールバック

緊急時は環境変数でバイパス:
```bash
SKIP_PR_OWNERSHIP_CHECK=1 git push origin HEAD
```

または `scripts/validate-pr-ownership.sh` を削除すれば pre-push フックも自動無効化される。

---

## 代替案と棄却理由

| 案 | 棄却理由 |
|----|---------|
| `isolation: worktree` フロントマター | GitHub Issue #50357: `claude --agent <name>` から呼ぶと無視される既知バグ |
| git add -A 禁止のドキュメント化のみ | 読み飛ばし可能。機械的な強制がない |
| 単一エージェントに限定 | 並行開発の速度メリットを失う |

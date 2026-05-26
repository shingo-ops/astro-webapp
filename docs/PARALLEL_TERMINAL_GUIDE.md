# 複数ターミナル並行開発ガイド

複数のターミナルで同時に開発作業を進める際の安全な手順と注意点をまとめます。

## なぜコンフリクトが起きるのか

`develop ↔ main` のコンフリクトは主に4つのパターンで発生します。

| パターン | 何が起きるか |
|---------|------------|
| P1: 長期分岐 | develop が main より大幅に先行した状態でリリース PR を開く |
| P2: 同一ファイル並行編集 | 複数 feature branch が `InboxPage.css` / `schedule.css` などを同時編集 |
| P3: 非同期 pull | Terminal A で PR merge → Terminal B が pull 前に commit/push |
| P4: incomplete rebase | `git pull --rebase` 実行中に別ターミナルから push → abort |
| P5: ブランチ切り替えによる編集消失 | 別ターミナルで `git checkout` → 未コミット編集が上書きされて消える |

---

## 正しい並行開発の手順

### 1. 作業開始前（必須）

```bash
# develop を最新化してから feature ブランチを切る
git fetch origin
git checkout develop
git merge --ff-only origin/develop
git checkout -b feature/morimoto/<トピック名>
```

### 2. 各ターミナルでの作業ルール

- **1つのターミナル = 1つの feature ブランチ**（同じブランチを複数ターミナルで共有しない）
- 作業中は `develop` / `main` ブランチには触れない
- push する前に必ず `git status` でステージング状態を確認する

### 3. 他ターミナルの PR がマージされたとき

```bash
# 現在の feature ブランチで最新 develop を取り込む
git fetch origin
git rebase origin/develop
# ※ rebase 中は他のターミナルで push しないこと（P4 防止）
```

### 4. 絶対禁止事項

- `git pull --rebase` の実行中に別ターミナルから `git push`
- 2つのターミナルで同じ feature ブランチを同時編集
- `InboxPage.css` / `schedule.css` / `tokens.css` / `index.css` への複数 PR 同時オープン
- `.claude-pipeline/active-work.md` を確認せずに新しい作業を開始する

### 4.5. 作業開始前の重複チェック（SSoT 確認・必須）

**新しいターミナルで作業を始める前に `.claude-pipeline/active-work.md` を必ず確認すること。**

このファイルが「誰が今何を担当しているか」の唯一の真実（SSoT）。

```bash
# 確認コマンド
cat .claude-pipeline/active-work.md
```

重複が見つかった場合 → **STOP → しんごさんに確認してから開始する**

`scripts/new-worktree.sh` を使えば自動で記入される（手動記入不要）。

### 5. AI エージェントを並行起動するとき（P5 対策・推奨）

**原則: 新しい並行作業は必ず Worktree で起動する**

Worktree = エージェントごとに独立した作業ディレクトリを用意する仕組み。
ブランチ切り替えが不要になり、P5（編集消失）が構造的に発生しなくなる。

```bash
# 標準スクリプトで起動（ブランチ名を指定するだけ）
bash scripts/new-worktree.sh feature/morimoto/<トピック名>

# Claude Code も同時起動したい場合
bash scripts/new-worktree.sh feature/morimoto/<トピック名> --claude
```

**作業完了後のクリーンアップ（必須）**

```bash
git worktree remove ~/worktrees/salesanchor/<ブランチ名>
git branch -d feature/morimoto/<トピック名>
# 定期的に: git worktree prune
```

**注意: lockfile（package-lock.json）の Single-Writer Rule**

複数の Worktree で同時に `npm install` を実行しない。
lockfile が衝突して 5,000行 差分が発生する（レビュー不可能になる）。
`npm install` は1つの Worktree（または main ディレクトリ）でのみ実行すること。

---

## 自動化された安全機構

### Git フック（ローカル）

| フック | 何を防ぐか |
|--------|-----------|
| `pre-push` | rebase 進行中の push を禁止（P4防止） |
| `pre-commit` | lint + 設計ルール違反のコミットを禁止 |

### Git Worktree（P5防止）

| コマンド | 用途 |
|---------|------|
| `bash scripts/new-worktree.sh <ブランチ>` | 新しい独立作業ディレクトリを作成 |
| `git worktree list` | 現在の worktree 一覧を確認 |
| `git worktree remove <パス>` | 作業完了後のクリーンアップ |
| `git worktree prune` | 不要な worktree を一括削除 |

### GitHub Actions（リモート）

| ワークフロー | 何をするか |
|------------|-----------|
| `auto-release-pr.yml` | develop push 時に develop→main PR を自動起票（P1防止） |
| `frontend-check.yml` | PR ごとに `npm run check:all` を実行 |
| `active-work-lint.yml` | `active-work.md` 変更時に列数フォーマット（6列）を検証（PR#916） |

### CODEOWNERS（並行 PR 警告）

`.github/CODEOWNERS` で以下のホットスポットファイルに `@shingo-ops` を設定済み。

- `frontend/src/pages/inbox/InboxPage.css`
- `frontend/src/pages/schedule.css`
- `frontend/src/tokens.css`
- `frontend/src/index.css`

---

## git pull の設定推奨値

```bash
git config pull.rebase false   # pull は merge（rebase しない）
git config pull.ff only        # fast-forward のみ
```

---

## develop → main のリリース手順

```bash
# ① develop → main の PR は自動起票される（auto-release-pr.yml）
# ② しんごさん（PO）が GitHub 上でマージ
# ③ deploy.yml が自動起動（本番デプロイ）
```

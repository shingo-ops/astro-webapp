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

---

## 自動化された安全機構

### Git フック（ローカル）

| フック | 何を防ぐか |
|--------|-----------|
| `pre-push` | rebase 進行中の push を禁止（P4防止） |
| `pre-commit` | lint + 設計ルール違反のコミットを禁止 |

### GitHub Actions（リモート）

| ワークフロー | 何をするか |
|------------|-----------|
| `auto-release-pr.yml` | develop push 時に develop→main PR を自動起票（P1防止） |
| `frontend-check.yml` | PR ごとに `npm run check:all` を実行 |

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

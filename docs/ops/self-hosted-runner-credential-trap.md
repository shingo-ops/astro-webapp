# Self-hosted Runner Credential Trap（過去事故と対策）

## TL;DR

**self-hosted runner で `actions/checkout@v4` を使うとき、必ず `with: token: ${{ secrets.PIPELINE_PAT }}` を指定すること**。デフォルトの GITHUB_TOKEN だけだと、runner ホストの `~/.gitconfig` の credential helper にフォールバックして失敗するパターンを観測している。

---

## 事故概要（2026-05-07）

### 症状

`Claude Max Auto-Pipeline` の `Checkout Code` ステップが intermittent に失敗:

```
fatal: could not read Username for 'https://github.com': terminal prompts disabled
The process '/usr/local/bin/git' failed with exit code 128
```

連続 failure を観測した run id: `25483842602`, `25480597758` ほか。

### 真因

`actions/checkout@v4` は内部で:

1. runner ホストの `~/.gitconfig` を temp directory に **コピー**
2. その temp dir に `HOME` を override
3. local extraheader (`AUTHORIZATION: basic ***`) を設定
4. `git fetch` で対象 SHA を取得

ところが Hitoshi の Mac の `~/.gitconfig` には日常開発用の credential helper:

```ini
[credential "https://github.com"]
    helper = !/usr/local/bin/gh auth git-credential
```

が設定されている。temp HOME へのコピーで helper も継承される。GITHUB_TOKEN による extraheader 認証が何らかの理由で拒否されると、git は credential helper にフォールバック → helper が credential を返せず → 端末からの username 入力を試みて、`terminal prompts disabled` で fatal exit。

### 修正

PR #299 で `actions/checkout@v4` に PAT (`secrets.PIPELINE_PAT`) を明示渡しに変更。これにより extraheader が確実に通り、helper へのフォールバックが発火しなくなる。

連続2回 dispatch 成功を確認（run `25495411878`, `25495531166`）。

---

## なぜ runner 側の対処をしなかったか（検討した選択肢）

### 案 A: runner の `~/.gitconfig` から credential helper を削除

**却下**: Hitoshi の日常 git 操作（VSCode / iTerm 等）は gh auth helper に依存している。共通リソースなので影響範囲が広い。

### 案 B: runner 起動時に `GIT_CONFIG_GLOBAL` を空ファイルに向ける

**却下**: `actions/checkout@v4` は `GIT_CONFIG_GLOBAL` を見ず、`process.env.HOME + '/.gitconfig'` を直接参照してコピーする。`GIT_CONFIG_GLOBAL` を設定しても checkout の挙動は変わらない。

### 案 C: runner 起動時に `HOME` を runner 専用 dir に切り替え

**却下リスク高**: HOME 変更は `gh` CLI、`npm`、`ssh` 等他ツールの状態探索先を全て変える。`Run Claude Code` ステップで `claude` CLI が認証を引けなくなる、`gh pr create` が ssh / token を見失う等の副作用が読みきれない。

### 採用: 案 D - workflow 側で PAT 明示渡し

`actions/checkout@v4` の `with: token` 指定。runner ホストに一切手を加えず、ワークフロー単位で完結する。

---

## 新規 self-hosted runner workflow を追加する人へ

`runs-on: self-hosted` の workflow で `actions/checkout` を使う場合、**必ず以下のいずれかを満たすこと**:

```yaml
- name: Checkout Code
  uses: actions/checkout@v4
  with:
    token: ${{ secrets.PIPELINE_PAT }}     # ← この行を必ず追加
```

または、もし `secrets.PIPELINE_PAT` を使えない事情がある場合:

- runner ホストに credential helper が無いことを `git config --global --list | grep credential` で事前確認
- セルフチェック workflow を準備して、helper 混入時に CI で気づける状態を作る

---

## PAT の運用

| 項目 | 値 |
|---|---|
| Secret 名 | `PIPELINE_PAT` |
| 種類 | classic PAT |
| Owner | Hitoshi (Hikky-dev) |
| Scopes | `repo`, `workflow` |
| Expiration | 90 days |
| Rotation tracking | https://github.com/shingo-ops/salesanchor/issues/300 |

90 日サイクルで rotation。詳細は Issue #300。

---

## 関連 PR / Issue

- PR #299 — checkout に PAT 明示渡し
- Issue #300 — PAT rotation リマインダー
- 失敗 run のログ: GitHub Actions UI から `id=25483842602` 等で参照可

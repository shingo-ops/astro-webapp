# Claude Code 運用ガードレール調査レポート（ADR-040）

作成日: 2026-05-17  
依頼元: ADR-040  
調査者: Claude Code (Generator)

---

## Codebase reconnaissance

ADR-040 は「調査ADR」であり、コード実装ではなくドキュメント・設定の確認が中心となる。  
対象 referent を以下に記録する。

| Referent Type | ADR 内表現 | 確認コマンド | Hit | 実体 file:line | Action |
|---|---|---|---|---|---|
| Document | `CLAUDE.md` — ADR起案フロー記述 | `grep -n "develop から切る" CLAUDE.md` | 1 hit | `CLAUDE.md:70` | Confirmed |
| Document | `CLAUDE.md` — VPS SSH 禁止規定 | `grep -n "VPS.*禁止\|SSH.*禁止" CLAUDE.md` | **0 hit** | なし | **NOT FOUND** |
| Document | `CLAUDE.md` — feature ブランチ命名規則 | `grep -n "feature/morimoto" CLAUDE.md` | 1 hit | `CLAUDE.md:70` | Confirmed |
| Workflow | `.github/workflows/` — PR ベースブランチ検証 | `grep -rn "base.*branch\|ベースブランチ" .github/workflows/` | 0 hit（通知のみ） | なし | **NOT FOUND** |
| Workflow | `.github/workflows/` — PR コミット数異常検知 | `grep -rn "commit.*count\|コミット.*数.*check" .github/workflows/` | 0 hit | なし | **NOT FOUND** |
| Workflow | `.github/workflows/` — ADR専用 lint | `grep -rn "adr.*lint\|lint.*adr" .github/workflows/` | 0 hit | なし | **NOT FOUND** |
| ADR | `ADR-012` — What/How 役割分担フロー | `ls docs/adr/ADR-012*` | 1 hit | `docs/adr/ADR-012-what-how-separation.md` | Confirmed |
| Config | `.claude/settings.json` — deny/disallow 設定 | `cat .claude/settings.json` | 0 hit（deny なし） | `.claude/settings.json` | **NOT FOUND** |
| Config | `claude-pipeline.yml` — `--base develop` ハードコード | `grep "base develop" .github/workflows/claude-pipeline.yml` | 1 hit | `claude-pipeline.yml:130` | Confirmed |

---

## 現状の事実（コード・設定から確認できたこと）

### 調査項目1: 既存ガードレールの存在確認

#### CLAUDE.md に存在するルール

**ADR起案フロー**（`docs/adr/ADR-012-what-how-separation.md` + `CLAUDE.md` 実装フローセクション）:

```
1. Shingo が Web Claude に「○○を実現したい」と話す
2. Web Claude が ADR（What/Why/Scope）に落とす
3. Shingo が ADR を develop に push（Terminal Claude Code 経由）
4. パートナー Claude Code が claude-pipeline.yml により自動起動し、実装 + PR 作成
5. CI 緑なら Shingo が PR 本文を確認してマージ
```

`CLAUDE.md` ブランチ運用ルール（CLAUDE.md:70–74）に以下が明記されている:
- `develop` から `feature/morimoto/` ブランチを作成すること
- ブランチ名は `feature/morimoto/作業内容を英語で` とすること
- `gh pr create` でPR作成後、`develop` へマージすること
- `develop` および `main` への直接コミット禁止

**VPS 操作の禁止規定**:
- `CLAUDE.md` に「VPS コンテナの落とし穴」セクション（`/app` が appuser 権限で書込不可、`/tmp` が tmpfs 等）は存在する
- しかし、「Terminal Claude Code から VPS への SSH 接続禁止」という**明示的な禁止規定は存在しない**（grep 0 hit）
- 「不可逆操作は必ず PO 確認」セクションは存在するが、SSH 接続はここに列挙されていない

**feature ブランチの命名・運用ルール**:
- `CLAUDE.md:70`: `feature/morimoto/` プレフィックスが明記されている
- `develop` から切ることが明記されている

#### .github/workflows/ に存在するチェック

調査対象 9 ファイル: `discord-pr-notify.yml`, `e2e.yml`, `feedback-issue-triage.yml`, `test.yml`, `deploy.yml`, `schema-check.yml`, `qa-smoke.yml`, `claude-pipeline.yml`, `external-state-snapshot.yml`

| チェック種別 | 存在するか |
|---|---|
| PR のベースブランチ妥当性検証（main 向け PR をブロック等） | **なし** |
| PR 内コミット数の異常検知 | **なし** |
| ADR 起案 PR 専用の lint（ADR ファイル以外の変更を検知等） | **なし** |
| テナントスキーマ整合性チェック | あり（`schema-check.yml`） |
| バックエンドユニット・統合テスト | あり（`test.yml`） |
| デプロイ（main push 時） | あり（`deploy.yml`） |
| Discord PR 通知（ログのみ、検証なし） | あり（`discord-pr-notify.yml`） |

#### ADR-012 で定義したフローと現在の CLAUDE.md / workflow 定義との一致度

- CLAUDE.md の実装フローセクションは ADR-012 の記述と**一致している**
- `claude-pipeline.yml` は `--base develop` をハードコードしており、**pipeline 経由の PR は常に develop 向け**になる（`claude-pipeline.yml:130`）
- ただし、Interactive Terminal Claude Code（対話型）は pipeline の外であり、同じ制約を受けない

---

### 調査項目2: Terminal Claude Code の起動・実行環境

#### プロジェクト `.claude/settings.json` の内容

```json
{
  "permissions": {
    "allow": [
      "Bash(git status)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git branch:*)",
      "Bash(git fetch:*)",
      "Bash(git show:*)",
      "Bash(gh pr view:*)", "Bash(gh pr list:*)", "Bash(gh pr diff:*)",
      "Bash(gh run list:*)", "Bash(gh run view:*)",
      "Bash(gh workflow view:*)", "Bash(gh workflow list:*)",
      "Bash(gh issue view:*)", "Bash(gh issue list:*)",
      "Bash(docker compose ps)",
      "Bash(docker compose logs:*)"
    ]
  }
}
```

**重要な発見**:
- `allow` list は読み取り系コマンド（git status/diff/log, gh pr view 等）のみ
- `deny` / `disallow` リストは**存在しない**
- `allow` にないコマンド（`Bash(ssh:*)`, `Bash(git push:*)`, `Bash(git checkout -b:*)` 等）は Claude Code が**ユーザーの確認を求めたうえで実行可能**（ブロックされない）
- 破壊的操作（SSH, git push force 等）を**強制的にブロックする設定がない**

#### GitHub Actions `claude-pipeline.yml` の実行環境

- Runner: `self-hosted`（VPS 上またはローカル Mac に設置）
- ツール制限: `--disallowedTools "WebFetch WebSearch"`（Web アクセスのみ禁止）
- 許可ツール: `--allowedTools` に `Bash(ssh:*)` は**含まれない** → pipeline 内では SSH は使えない
- PR 作成: `gh pr create --base develop` にハードコード → pipeline 経由は常に develop 向け
- git 操作: `Bash(git checkout:*)`, `Bash(git switch:*)` は許可されているが、操作対象は checkout されたリポジトリ（Mac/Runner）

#### 「現在の作業環境が Mac か VPS か」を自己確認する仕組み

- 存在しない。Terminal Claude Code が起動されたマシンのカレントディレクトリのみが基準
- VPS 上の self-hosted runner で claude-pipeline.yml が起動した場合、**Claude Code は VPS 上で動作する**が、そのことは明示的に表示されない
- CLAUDE.md に「Terminal Claude Code は Mac で起動すること」という規定はない

---

### 調査項目3: 直近2回の違反の根本原因

#### 1回目違反: VPS SSH 接続試行

**確認できた事実**:
- CLAUDE.md に「VPS への直接 SSH 接続禁止」の明示規定なし
- `.claude/settings.json` に `Bash(ssh:*)` の deny 設定なし
- `claude-pipeline.yml` の `--allowedTools` に `Bash(ssh:*)` は含まれないが、Interactive Terminal Claude Code には pipeline の制約は適用されない

**根本原因の仮説（エビデンスベース）**:

| 候補 | エビデンス | 判定 |
|---|---|---|
| CLAUDE.md に SSH 禁止規定がない | grep 0 hit 確認 | **確定** |
| `.claude/settings.json` に deny 設定がない | settings.json 内容確認 | **確定** |
| Interactive Terminal Claude Code は pipeline の外 | pipeline は --allowedTools で制限、Interactive はしない | **確定** |
| Mac クローンがなく、VPS 上で作業せざるを得なかった | self-hosted runner が VPS 上に存在 | 可能性あり（VPS が唯一のrunnerの場合） |

#### 2回目違反: main ベースの feature ブランチ作成と PR #382

**確認できた事実**:
- CLAUDE.md:70 に「develop から feature ブランチを切る」と明記されているが、automated enforcement なし
- `claude-pipeline.yml:130` は `--base develop` をハードコード（pipeline 経由では main 向けにはならない）
- → 違反は**Interactive Terminal Claude Code を直接操作した**場合にのみ発生しうる

**19コミット混入の根本原因の仮説**:

`develop` が `main` より 19 コミット先行している状況で、feature ブランチを `develop` から切り、`main` 向けに PR を作成した場合:
- `feature/foo` ← `develop` から cut（19 コミット + 新規コミット含む）
- `gh pr create --base main` を実行
- GitHub の diff は `main..feature/foo` = `develop` の 19 コミット + 新規コミット
- → PR に 19 の無関係コミットが混入

これは CLAUDE.md のブランチルール（develop 向け PR）が守られなかった直接の結果であり、Terminal Claude Code が対話型で操作した際のプロセス逸脱と判断される。

---

## Claude Code の所見

### 調査項目4: ガードレール状況の判定

**結論: 「存在するが機能していない（一部不在）」の複合**

| 分類 | 対象 | 根拠 |
|---|---|---|
| **ガードレール不在** | VPS SSH 禁止規定 | CLAUDE.md に明示なし、settings.json に deny なし |
| **存在するが機能していない** | develop ブランチフロー | CLAUDE.md に記述あり・ADR-012 定義あり。しかし automated enforcement（workflow validation）がない |
| **pipeline のみ機能している** | `--base develop` PR 強制 | `claude-pipeline.yml:130` でハードコード済み。Interactive Terminal Claude Code には適用されない |
| **部分的に存在** | `.claude/settings.json` の制限 | allow list あり（読み取り系のみ）。deny list なし |

### 各原因に対する追加対策の選択肢

#### 対策A: CLAUDE.md への明示的禁止事項追加（即効性: 高、コスト: 低）

`CLAUDE.md` の「不可逆操作は必ず PO 確認」セクションに以下を追加:
- Terminal Claude Code から VPS（49.212.137.46）への直接 SSH 接続禁止
- `main` をベースにした feature ブランチ作成禁止
- Interactive Terminal Claude Code からの `gh pr create --base main` 禁止

#### 対策B: `.claude/settings.json` へ deny list 追加（即効性: 高、コスト: 低）

```json
{
  "permissions": {
    "deny": [
      "Bash(ssh:*)",
      "Bash(ssh-keygen:*)"
    ]
  }
}
```

効果: Interactive Terminal Claude Code が SSH を試みた場合、ユーザー確認なしにブロックされる。

注意: `git push` や `gh pr create --base main` を deny に追加すると正常操作も制限されるため、精密な設定が必要。

#### 対策C: GitHub Actions に PR ベースブランチ検証 workflow 追加（即効性: 中、コスト: 中）

```yaml
# .github/workflows/pr-base-guard.yml
on:
  pull_request:
    types: [opened, reopened, synchronize]
jobs:
  check-base:
    runs-on: ubuntu-latest
    steps:
      - name: Reject main-targeted PRs from non-emergency branches
        if: github.event.pull_request.base.ref == 'main' && !startsWith(github.event.pull_request.head.ref, 'hotfix/')
        run: |
          echo "ERROR: PRs to main must go through develop first."
          exit 1
```

効果: main 向け PR（hotfix 除く）を CI レベルで自動ブロック。

#### 対策D: PR コミット数異常検知（即効性: 中、コスト: 中）

PR 内コミット数が閾値（例: 20）を超えた場合に warning を出す step を追加。  
完全ブロックではなく警告にとどめることで誤検知による正常 PR のブロックを回避。

#### 対策E: 起動環境の明示（即効性: 高、コスト: 低）

CLAUDE.md に「Terminal Claude Code は Mac 上で起動すること。VPS 上での Interactive 実行禁止」を追加。  
self-hosted runner ラベルを `[self-hosted, mac]` と明示し、VPS runner と分離する。

---

### 推奨される次のADRの方向性

**最優先（1 ADR で対応可能）**:

- **対策 A + B + C の組み合わせ**: 
  1. CLAUDE.md に SSH 禁止・ベースブランチルールを明示（即効）
  2. `.claude/settings.json` に `deny: ["Bash(ssh:*)"]` を追加（即効）
  3. `.github/workflows/pr-base-guard.yml` を新設し main 向け PR を CI でブロック（構造的防止）

この3点セットにより:
- VPS SSH 違反: settings.json deny で**ブロック**（要 Shingo 承認なし、自動阻止）
- main ベース PR: workflow で **CI ブロック**（自動検知）
- ドキュメント: CLAUDE.md で明示（将来のセッション引き継ぎ）

**次ステップ**: 本レポートをもとに「ガードレール強化 ADR」を起案する。  
ADR のタイトル候補: `ADR-041: Claude Code ガードレール強化 — SSH 禁止 + PR ベースブランチ強制`

---

## 参照ファイル一覧

| ファイル | 内容 | 調査での役割 |
|---|---|---|
| `CLAUDE.md` | プロジェクト共通ルール | ガードレール存在確認（項目1・2） |
| `.claude/settings.json` | Claude Code ツール権限設定 | ツール制限の実態確認（項目2） |
| `.github/workflows/claude-pipeline.yml` | ADR 自動実装パイプライン | pipeline 内制約の確認（項目1・2） |
| `.github/workflows/discord-pr-notify.yml` | PR Discord 通知 | PR 検証ロジックの不在確認（項目1） |
| `docs/adr/ADR-012-what-how-separation.md` | What/How 役割分担定義 | フロー定義と実態の比較（項目1） |
| `.github/workflows/test.yml` | バックエンドテスト | 既存 CI チェック範囲の確認 |
| `.github/workflows/schema-check.yml` | スキーマ整合性チェック | 既存 CI チェック範囲の確認 |
| `.github/workflows/qa-smoke.yml` | QA スモークテスト（`salesanchor-vps` runner） | VPS self-hosted runner の存在確認（項目2・3） |

# ADR-042: Claude Code 運用ガードレール強化 + リリース運用統一

## ステータス

Accepted (2026-05-19、しんごさん承認済)

## 背景

ADR-040 (Claude Code ガードレール調査) で以下のガードレール不在が確認された:

1. CLAUDE.md に VPS SSH 禁止規定が不在
2. `.claude/settings.json` に `deny` / `ask` リストが不在
3. PR ベースブランチ検証 workflow が不在
4. main branch protection が不在

直近 2 回の Terminal Claude Code ワークフロー違反 (VPS への直接 SSH、main ベース feature ブランチで 19 commit 混入の PR #382) が発生し、構造的解決が必要。

加えて、2026-05-15〜17 の間に ADR-036/038/039/041/044 等が develop に landed したが、main 反映が止まり 2 日間 develop が本番未反映状態となった。develop → main の昇格運用が不明瞭で、しんご手書きの Release PR (#390 / #398) が場当たり的に発生していた。

本 ADR は **運用ルールを明文化 + 機械的ガードレール導入** により、これらの構造的問題を一括解決する。

### 関連 referent (起案時 reconnaissance)

| Referent | 確認方法 | 実体 | Action |
|---|---|---|---|
| `.github/workflows/deploy.yml` | `cat .github/workflows/deploy.yml` | `on: push: branches: [main]` で main push でデプロイ起動 | Confirmed (本 ADR では変更不要) |
| `.github/workflows/claude-pipeline.yml` | `grep "base develop" .github/workflows/claude-pipeline.yml` | `--base develop` ハードコード | Confirmed (Generator 用、本 ADR では維持) |
| `.claude/settings.json` permissions | `cat .claude/settings.json` | `allow` リストのみ、`deny` / `ask` なし | Confirmed (本 ADR で `ask` 追加) |
| `CLAUDE.md` ブランチ運用 | `grep -n "develop" CLAUDE.md` | `feature/morimoto/` から develop に PR の記述あり、ただし「main 直接 push 禁止」「リリース運用」記述なし | Confirmed (本 ADR で追記) |
| 既存 main branch protection | GitHub Settings UI 確認 | 設定なし (admin が直接 push 可、force push 可) | Confirmed (本 ADR で設定) |
| `.github/workflows/pr-base-guard.yml` | `ls .github/workflows/` | 不在 | Confirmed (本 ADR で新規) |
| `.github/workflows/promote-to-main.yml` | `ls .github/workflows/` | 不在 | Confirmed (本 ADR で新規) |
| 既存 4 エージェント定義 | `ls ~/.claude/agents/` | planner.md / generator.md / reviewer.md / evaluator.md 存在 | Confirmed (本 ADR では言及のみ、別 ADR で詳細改修) |

## What

### 1. 共通ルール (CLAUDE.md 追記)

`CLAUDE.md` に以下を新設:

#### 1-A. ブランチ運用 (全員共通、原則)

```markdown
## ブランチ運用 (全員共通、原則)

### 不変ルール
- すべての変更は develop ブランチ経由
- 原則として main への直接 push を廃止 (branch protection で機械的にブロック)
- 本番反映は「リリースボタン」(promote-to-main.yml workflow_dispatch) のみ
- main 向け PR は CI で全部 FAIL (pr-base-guard.yml)

### develop への作業フロー
1. feature ブランチを develop から切る (`feature/{author}/{task}`)
2. PR を develop に向けて作成
3. 起案者系統の Reviewer エージェント (または互いに) で review
4. approve 後 squash merge

### main への昇格 (リリースボタンのみ)
- Web UI (推奨): Actions タブ → "🚀 本番リリース (develop → main)" → Run workflow ボタン → 理由入力
- CLI (上級者): `gh workflow run promote-to-main.yml -f reason="ADR-XXX 完走"`
- 内部動作: develop HEAD を main に fast-forward push
- 直後に deploy.yml が main push を検知して自動デプロイ (約 5 分で本番反映)
- 失敗時 (conflict 等): Discord 通知 → 手動対応
- ※ "Run workflow" ボタン文字は GitHub 固定 (英語)、ワークフロー名・入力欄は日本語表示

### なぜ Release PR を使わないか
- develop merge 前に review 完了済
- main 化時点でレビュー対象はない (develop = main コピー)
- PR は review 痕跡を残す仕組み、review がなければ形骸化
- リリースボタンのほうが速く、ガードレールも明快 (1 経路のみ)
```

#### 1-B. 作業パターン A / B

```markdown
## 作業パターン

### パターン A: 単独開発
- 起案者: しんご (ADR or 仕様書)
- 実装者: しんご本人 (Generator 役)
- Reviewer 系統: しんご系 (本人が Reviewer エージェント起動 or 自己 review)
- Evaluator 系統: しんご系 (Layer 1 Playwright / Layer 2 Claude in Chrome / Skip)
- claude-pipeline 不使用
- 用途: しんごさんが自分で実装するもの (例: ADR-041 手書き)、Meta 申請関連、軽微な改修

### パターン B: Plan → 開発委譲
- 起案者 (Plan): しんご (ADR 起案、Generator 役として PR open、自分で merge)
- 配送経路: claude-pipeline (Plan をひとしに届ける配送機構)
- 実装者 (Generator): AI on Hikky-dev-Mac (ひとしが起動)
- Reviewer 系統: ひとし系
- Evaluator 系統: ひとし系 (Layer 1/2/Skip)
- 用途: 大規模実装、ひとし不在時の進行確保
- Generator の制約: Bash allow-list (ADR-039) / Codebase reconnaissance / QA Smoke (ADR-038)
```

#### 1-C. Claude Code プランニング規約

```markdown
## Claude Code でプランを練る際のルール

### プランモード必須
全員 (しんご・ひとし) は Claude Code で実装や設計のプランを練る際、
必ず Plan mode に自動切替してから検討を進めること。

### なぜ
- Plan mode は実行系ツール (Edit/Write/Bash 書込み系) を封じる安全モード
- プランニング段階で意図しないファイル変更やコマンド実行を防ぐ
- ADR / 設計判断 / 影響範囲調査などは Plan mode で行うことで、
  「考えながら触る」事故を構造的に防止する

### 運用
- セッション開始時 or 設計検討タスク受領時に自動的に Plan mode に入る
- 実装に入る判断ができた段階で ExitPlanMode を使って通常モードに戻る
- Claude Code 側で自動切替の hook を整備 (settings.json の SessionStart hook 等)

### Plan mode と通常モードの境界
| 段階 | モード |
|---|---|
| プランニング (ADR ドラフト / 影響範囲調査 / 設計検討) | Plan mode |
| 確定した実装 (commit / push / 設定変更) | 通常モード |
| Reviewer エージェント起動 | 通常モード (実行は agent 側で制御) |
```

#### 1-D. 4 エージェント役割定義

```markdown
## 4 エージェント役割定義 (Planner + Generator + Reviewer + Evaluator)

| 役割 | フェーズ | 担当 | 動作モード | 入出力 |
|---|---|---|---|---|
| Planner | ADR 起案前段、仕様書作成 | しんご (人間) | Claude Code Plan mode | アイディア → ADR/仕様書 |
| Generator | 実装 + PR 作成 + 修正 push | (パターン A) しんご本人 / (パターン B) AI on Hikky-dev-Mac | 通常モード | ADR/仕様書 → コード + `gh pr create` + Evaluator method 宣言 |
| Reviewer | コードレビュー (Loop 1、静的、ブラウザ不要) | エージェント (しんご系 or ひとし系) | エージェント | PR → `gh pr review --approve` or `--request-changes` |
| Evaluator | UI/UX ブラウザ評価 (Loop 2、動的) | エージェント (しんご系 or ひとし系) | Layer 1 Playwright (default) / Layer 2 Claude in Chrome (オプション) / Skip 可 | PR → `gh pr review --approve` or `--request-changes` |

### PR フロー (GitHub 標準準拠)
1. PR 作成 = 常に Generator (役割名、人間が Generator 役の場合も含む、人間は PR 作成しない)
2. 再レビュー依頼 = Generator (修正 push 後に再要求)
3. Reviewer/Evaluator は `gh pr review` のみ (PR 作成・merge しない)
4. 最終 merge = 人間 (ひとし or しんご) が `gh pr merge --squash`

### Evaluator method 宣言 (PR 本文)
```
## Evaluator method
- [x] Layer 1: Playwright (default — clean Chromium, reproducible, parallel-safe)
- [ ] Layer 2: Claude in Chrome (logged-in Chrome session required; reason: ___)
- [ ] Skip (no UI/UX change — backend only / docs / refactor / tests only)
```

### Evaluator method 選択基準
- frontend/src/ 変更 → Layer 1 必須
- Meta OAuth / Webhook 関連 → Layer 2 必須 (実 Meta セッション必要)
- 本番デプロイ後の目視 / Meta App Review 撮影前確認 → Layer 2 必須 (GIF 録画)
- backend のみ / docs / リファクタ / テストコードのみ → Skip 可
```

### 2. リリースボタン: `promote-to-main.yml` 新規

`.github/workflows/promote-to-main.yml` を新規作成:

```yaml
name: 🚀 本番リリース (develop → main)
on:
  workflow_dispatch:
    inputs:
      reason:
        description: "本番リリースの理由 (Discord通知に表示。例: ADR-038 完走 / Meta 撮影前緊急修正)"
        required: true
        type: string

jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: develop
          fetch-depth: 0
          token: ${{ secrets.PIPELINE_PAT }}

      - name: Fast-forward main to develop
        run: |
          git fetch origin main
          git merge-base --is-ancestor origin/main HEAD || {
            echo "::error::develop is not a fast-forward of main"
            exit 1
          }
          git push origin develop:main

      - name: Notify Discord
        if: always()
        run: |
          curl -H "Content-Type: application/json" \
            -d "{\"content\":\"$STATUS develop→main 昇格 by $ACTOR\n理由: $REASON\nSHA: $SHA\"}" \
            ${{ secrets.DISCORD_WEBHOOK_URL }}
        env:
          STATUS: ${{ job.status }}
          ACTOR: ${{ github.actor }}
          REASON: ${{ github.event.inputs.reason }}
          SHA: ${{ github.sha }}
```

### 3. PR ベースガード: `pr-base-guard.yml` 新規

`.github/workflows/pr-base-guard.yml` を新規作成:

```yaml
name: PR Base Branch Guard
on:
  pull_request:
    types: [opened, edited, reopened, synchronize]

jobs:
  reject-main-targeted:
    if: github.event.pull_request.base.ref == 'main'
    runs-on: ubuntu-latest
    steps:
      - name: Block main-targeted PRs
        run: |
          echo "::error::PRs targeting 'main' are not allowed."
          echo "Use the 'Promote develop to main' release button instead:"
          echo "  gh workflow run promote-to-main.yml -f reason='...'"
          exit 1
```

### 4. main branch protection 設定

GitHub Settings UI or `gh api` で以下を設定:

| 設定 | 値 |
|---|---|
| Restrict pushes that create matching branches | ✓ (direct push 禁止) |
| Allow force pushes | ✗ |
| Allow deletions | ✗ |
| Require a pull request before merging | ✓ (pr-base-guard で全部 NG になる経路と組み合わせ) |
| Do not allow bypassing the above settings | ✓ (admin bypass も原則オフ) |
| Restrict who can push to matching branches | PIPELINE_PAT を持つ workflow のみ (promote-to-main.yml) |

### 5. `.claude/settings.json` SSH ask リスト追加

```json
{
  "permissions": {
    "allow": [
      // 既存の読み取り系は維持
      "Bash(git status)", "Bash(git diff:*)", ...
    ],
    "ask": [
      // 追加: auto-mode でも必ず確認
      "Bash(ssh:*)",
      "Bash(ssh-keygen:*)",
      "Bash(ssh-add:*)",
      "Bash(scp:*)",
      "Bash(sftp:*)"
    ]
  }
}
```

Claude Code が SSH 系を実行しようとすると `--dangerously-skip-permissions` (auto-mode) であっても確認ダイアログが必須となる。ひとしさん本人が iTerm 等で SSH するのは影響なし (Claude Code 経由のみ制限)。

### 6. Planner 役割の正式化 (`~/.claude/agents/planner.md` 強化)

別途プロンプト ([[agents-role-clarification]]) を Claude Code に適用して、planner.md / generator.md / reviewer.md / evaluator.md の 4 ファイルを更新。本 ADR では Planner = Plan mode で起動・ADR/仕様書作成 という役割定義を確立。

## Why

### 運用整合性
- ADR-040 research が確認した 4 つのガードレール不在を一括解決
- 直近の違反 2 件 (VPS SSH / main ベース PR 19 commit) が構造的に再発不可能になる
- main / develop の divergent (PR #390/#398 等で発生していた) を新運用で原理的に防ぐ

### 役割と権限の明確化
- 「PR 作成 = Generator、レビュー = Reviewer/Evaluator、merge = 人間」の単一責任化
- GitHub 標準フロー準拠 (OSS / 業界標準と同じ)
- Mode B (External PR review) と Mode A の操作統一

### 認知負荷の削減
- 「全員 develop 経由」の 1 本ルール
- main 反映は「リリースボタン 1 クリック」の 1 経路
- 例外運用 (admin bypass 等) を残さないことで、判断分岐を排除

### 安全性
- `.claude/settings.json` ask で auto-mode でも SSH 系は確認必須 → Claude Code 暴走の SSH 自動実行を防止
- pr-base-guard で main 向け PR の誤作成を CI 段階でブロック
- main branch protection で直接 push を物理的に防止

## Scope外

- claude-pipeline.yml の state machine 順序逆転 (Generator → Reviewer → Evaluator) → 別 ADR (ADR-043 候補) で扱う
- Generator / Reviewer / Evaluator agent ファイルの詳細改修 → agents-role-clarification-prompt.md で別途適用
- migration 自動適用 (ADR-034) / 全テナント schema 整合性 (ADR-036) — 既に対応済
- QA Smoke Suite (ADR-038) / Codebase reconnaissance (ADR-039) — 既に対応済
- Static analysis bootstrap (旧 ADR-037 予約、番号衝突済) → 別 ADR で再起案

## 事業上の制約

- しんごさんの Meta 撮影スケジュールへの影響を最小化 (実装中の緊急対応が必要な場合は admin bypass を一時的に復活させる選択肢を残す)
- リリースボタン稼働後、ひとし不在時もしんごさん単独でリリースできる (Web UI 1 クリック)
- 移行期間 (1 ヶ月) は旧 Release PR 運用が万一発生しても警告のみで block しない (pr-base-guard を soft-warn に設定する選択肢)

## 関連 ADR

- [ADR-012](./ADR-012-what-how-separation.md) — What/How 役割分担 (本 ADR は実装/運用ルール側を強化)
- [ADR-029](./ADR-029-self-hosted-runner-fleet.md) — Self-hosted runner (本 ADR の promote-to-main.yml は GitHub Actions hosted runner)
- [ADR-040](./ADR-040-claude-code-guardrail-investigation.md) — research 起点
- [ADR-041](./ADR-041-meta-page-connection-fallback-implementation.md) — 旧運用 Release PR (#390) で本番反映済
- [ADR-045](./ADR-045-migration-055-deploy-automation.md) — 旧運用 Release PR (#398) で本番反映済 (旧運用 last 2 件目)
- 後続 ADR (state machine 順序逆転、別途起案予定)

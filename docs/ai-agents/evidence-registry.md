# Evidence Registry

AI Agent の判断根拠を残すための台帳。ADR、仕様、テスト結果、ログ、コード参照など一次情報を優先する。

## Entry Template

```text
id: EV-YYYYMMDD-001
date:
agent:
task:
scope:
evidence:
  - type: file | adr | command | log | external
    reference:
    summary:
confidence: high | medium | low
tradeoff:
decision:
follow_up:
```

## Current Entries

```text
id: EV-20260530-001
date: 2026-05-30
agent: Claude Code (orchestrator)
task: Codex の役割を Research・Planning に拡張し、非対話 exec ラッパーを整備
scope: AGENTS.md, memory/project_codex_adoption.md, scripts/codex-research.sh
evidence:
  - type: command
    reference: codex --help
    summary: codex exec サブコマンドが実装済みであることを確認（v0.134.0）
  - type: command
    reference: ls scripts/
    summary: codex-generator.sh（TUI対話型）は存在するが codex exec 用の非対話ラッパーは存在しなかった
  - type: file
    reference: scripts/codex-generator.sh
    summary: 既存ラッパーは Generator（対話型TUI）専用であり Research/Planning 用の exec ラッパーは未作成
  - type: file
    reference: .claude/agents/research.md
    summary: develop ブランチでは既に存在していた（ギャップ③は既解消）
  - type: file
    reference: AGENTS.md
    summary: 役割分担テーブル（Codex: Research/Planning/Generator、Claude Code: Review）を追加済み
confidence: high
tradeoff: codex exec はサンドボックス制限あり（sandbox_permissions = disk-full-read-access）。書き込みが必要なタスクは codex-generator.sh（対話型）を使い続ける必要がある
decision: scripts/codex-research.sh を新設。--plan フラグで Planner モード切替可能。既存の codex-generator.sh は Generator 専用として温存
follow_up: 実運用 30 日後に Research/Planning exec モードの採用率を Governance が確認する
```

```text
id: EV-20260529-004
date: 2026-05-29
agent: Codex
task: Agent pipeline redefinition and runtime definition sync
scope: .claude/agents, docs/agents, AGENTS.md, CLAUDE.md, docs/onboarding/claude-code.md, docs/ai-agents/agent-roles.md
evidence:
  - type: file
    reference: .claude/agents/planner.md
    summary: Planner runtime prompt was rewritten to the Research -> Planner -> Architect -> PO Approval pipeline
  - type: file
    reference: .claude/agents/generator.md
    summary: Generator now requires Architect APPROVE and explicit PO Approval before implementation
  - type: file
    reference: docs/ai-agents/agent-roles.md
    summary: Runtime canonical source was moved to `.claude/agents/` and Architect was added to the role index
  - type: file
    reference: AGENTS.md
    summary: Project rules now document the new runtime pipeline and source-of-truth split
confidence: medium
tradeoff: Keeping both `.claude/agents/` and `docs/agents/` in sync adds maintenance overhead, but it preserves a short runtime prompt and a detailed reference layer
decision: Standardize the new Research -> Planner -> Architect -> PO Approval -> Generator -> Reviewer -> Evaluator -> GitHub CI pipeline with `.claude/agents/` as runtime source of truth
follow_up: Add a lightweight sync check or maintainers' review note if divergence between `.claude/agents/` and `docs/agents/` appears again
```

```text
id: EV-20260530-011
date: 2026-05-30
agent: Codex
task: AEON delivery runner startup confirmed with non-recursive smoke prompt
scope: scripts/aeon-delivery.sh, /tmp/aeon-delivery-20260530-051503.log, tasks/todo.md
evidence:
  - type: log
    reference: /tmp/aeon-delivery-20260530-051503.log
    summary: delivery flow started normally with research stage and read-only Codex wrapper invocation, confirming the same-terminal entry path works
  - type: file
    reference: tasks/todo.md
    summary: task row updated to reflect that delivery startup was confirmed but full smoke completion remains pending
confidence: high
tradeoff: the smoke prompt can confirm startup and stage wiring without proving a full end-to-end completion; completion needs a longer run or a bounded no-op task
decision: AEON delivery startup is working, but the smoke run is still incomplete
follow_up: run a bounded, non-recursive no-op smoke task to let the stage sequence complete
```

```text
id: EV-20260530-010
date: 2026-05-30
agent: Codex
task: AEON delivery smoke run interrupted by recursive prompt
scope: scripts/aeon-delivery.sh, /tmp/aeon-delivery-20260530-051337.log, tasks/todo.md
evidence:
  - type: log
    reference: /tmp/aeon-delivery-20260530-051337.log
    summary: smoke prompt triggered Research to invoke aeon-delivery.sh recursively, so the run was interrupted before the delivery stages completed
  - type: file
    reference: tasks/todo.md
    summary: task row updated to reflect that the first smoke run was interrupted by prompt recursion
confidence: high
tradeoff: a naive smoke prompt can recurse into the same AEON delivery entry point, so smoke prompts must explicitly forbid re-entry
decision: the first smoke run is not a valid success signal because it did not reach the intended stage sequence
follow_up: rerun delivery with a non-recursive smoke prompt
```

```text
id: EV-20260530-009
date: 2026-05-30
agent: Codex
task: AEON release runner and delivery/release split
scope: scripts/aeon-release.sh, docs/ai-agents/aeon-release.md, docs/ai-agents/aeon-delivery.md, docs/ai-agents/aeon-routing.md, docs/ai-agents/agent-roles.md, docs/onboarding/claude-code.md, .claude/settings.json
evidence:
  - type: file
    reference: scripts/aeon-release.sh
    summary: main 向け PR を worktree ownership と baseRefName の両方で確認してから merge commit する release runner を追加した
  - type: file
    reference: docs/ai-agents/aeon-release.md
    summary: delivery と release を分離した canonical 手順を追加した
  - type: file
    reference: docs/ai-agents/aeon-routing.md
    summary: AEON の observed sequence に release step を追加し、main 反映までの経路を明文化した
  - type: file
    reference: .claude/settings.json
    summary: Claude Code から release runner を実行できる allow list を追加した
confidence: high
tradeoff: delivery と release を分離すると安全性は上がる一方、運用ステップは 1 つ増える
decision: AEON の main 昇格は `scripts/aeon-release.sh` を別ステップとして扱う
follow_up: dummy PR で release runner の smoke check を実行する
```

```text
id: EV-20260530-008
date: 2026-05-30
agent: Codex
task: Evaluator contract alignment for AEON delivery runner
scope: scripts/codex-exec.sh, docs/agents/evaluator.md, .claude/agents/evaluator.md
evidence:
  - type: file
    reference: docs/agents/evaluator.md
    summary: Evaluator pipeline position and inputs were updated to run after Generator and before Reviewer
  - type: file
    reference: .claude/agents/evaluator.md
    summary: runtime evaluator definition was kept aligned with the same post-generator/pre-reviewer flow
  - type: file
    reference: scripts/codex-exec.sh
    summary: Codex exec evaluator prompt now matches the post-generator evaluation flow
confidence: high
tradeoff: evaluator no longer depends on Reviewer approval up front, which matches the new delivery runner but requires a disciplined handoff to Reviewer afterward
decision: AEON delivery flow evaluates immediately after Generator completion and before Reviewer PR handling
follow_up: smoke run the delivery runner on a small task to verify evaluator log flow
```

```text
id: EV-20260530-007
date: 2026-05-30
agent: Codex
task: AEON end-to-end delivery runner
scope: scripts/aeon-delivery.sh, docs/ai-agents/aeon-delivery.md, docs/ai-agents/aeon-routing.md, docs/onboarding/claude-code.md, .claude/settings.json
evidence:
  - type: file
    reference: scripts/aeon-delivery.sh
    summary: same-terminal で research → planner → architect → generator → evaluator → reviewer を連結する delivery flow を追加した
  - type: file
    reference: docs/ai-agents/aeon-delivery.md
    summary: delivery flow の canonical documentation を追加した
  - type: file
    reference: .claude/settings.json
    summary: Claude Code から delivery runner を実行できる allow list を追加した
confidence: high
tradeoff: delivery runner で一気通貫化すると運用は楽になるが、失敗時の切り戻しは各 stage の report に依存する
decision: AEON の end-to-end delivery は `scripts/aeon-delivery.sh` を canonical runner とする
follow_up: 実行結果を見て、必要なら stage 別ログの保存先を固定する
```

```text
id: EV-20260530-006
date: 2026-05-30
agent: Codex
task: Claude Code permission allowlist for AEON dispatcher
scope: .claude/settings.json, docs/onboarding/claude-code.md, scripts/aeon-dispatch.sh
evidence:
  - type: file
    reference: .claude/settings.json
    summary: project settings の allow list に aeon-dispatch / codex-* wrapper を追加した
  - type: file
    reference: docs/onboarding/claude-code.md
    summary: 同一 terminal session から AEON dispatcher を呼ぶ操作導線を追記した
  - type: file
    reference: scripts/aeon-dispatch.sh
    summary: dispatcher 自体は同一ターミナルから AEON roles を起動できる状態にあった
confidence: high
tradeoff: allow list を広げることで使いやすさは上がる一方、実行可能コマンドが増えるため運用ルールの周知が必要になる
decision: Claude Code の project settings に AEON dispatcher を許可し、オンボーディングに標準コマンドを追加する
follow_up: 実運用で不要な entry があれば、最小限まで allow list を絞る
```

```text
id: EV-20260530-005
date: 2026-05-30
agent: Codex
task: AEON routing index and same-terminal execution guide
scope: docs/ai-agents/aeon-routing.md, docs/ai-agents/agent-roles.md, scripts/aeon-dispatch.sh
evidence:
  - type: file
    reference: docs/ai-agents/aeon-routing.md
    summary: Claude Code から同一端末で AEON roles を起動する canonical routing を明文化した
  - type: file
    reference: docs/ai-agents/agent-roles.md
    summary: Role index に AEON runtime entry を追加して導線を揃えた
  - type: file
    reference: scripts/aeon-dispatch.sh
    summary: generator / research / planner / architect / reviewer / evaluator の role routing を持つ入口を整備した
confidence: high
tradeoff: ルーティングの正本を docs/ai-agents に足したことで説明責任は上がるが、更新時に index と routing doc の同期が必要になる
decision: Claude Code からの AEON 起動手順は `scripts/aeon-dispatch.sh` + `docs/ai-agents/aeon-routing.md` を正本とする
follow_up: 将来 role が増えたら `aeon-routing.md` の表を先に更新し、dispatcher を追随させる
```

```text
id: EV-20260530-004
date: 2026-05-30
agent: Codex
task: AEON mainline delivery KGI definition
scope: docs/ai-agents/kpi.md, docs/agents/governance.md, scripts/aeon-dispatch.sh
evidence:
  - type: file
    reference: scripts/aeon-dispatch.sh
    summary: Claude Code から同一ターミナルで Codex 担当ロールを呼び出す入口を定義済み
  - type: file
    reference: docs/agents/governance.md
    summary: Governance は KGI / KPI review を責務に持ち、AEON の最上位指標を参照できる位置にある
  - type: file
    reference: docs/ai-agents/kpi.md
    summary: GitHub / Claude telemetry / manual mapping の正本として KPI を集約していた
confidence: high
tradeoff: KGI を 1 本に絞ることで評価軸は明快になる一方、補助 KPI を併記しないと途中課題の切り分けが難しくなる
decision: AEON の最上位 KGI を `AEON Mainline Delivery Completion Rate` とし、Claude Code → Codex → PR → main の完了率で測る
follow_up: 30 日 or 10 deliveries の観測後に target 値を Governance で再評価する
```

```text
id: EV-20260530-003
date: 2026-05-30
agent: Codex
task: AEON dispatcher for same-terminal Codex invocation from Claude Code
scope: scripts/aeon-dispatch.sh, scripts/codex-generator.sh, scripts/codex-exec.sh, .claude/agent-config.sh
evidence:
  - type: file
    reference: scripts/codex-generator.sh
    summary: Generator 入口は既に存在し、Claude Code から同一端末で呼び出す前提を持っていた
  - type: file
    reference: scripts/codex-exec.sh
    summary: Research / Planner / Architect / Reviewer / Evaluator の non-interactive Codex 入口が既に揃っていた
  - type: file
    reference: .claude/agent-config.sh
    summary: worktree / branch / active-work の共通設定値が SSoT 化されていた
confidence: high
tradeoff: 1 本の dispatcher で入口を揃えることで運用は単純になる一方、ロール判定とパスの増加に応じて保守範囲が広がる
decision: Claude Code 側からは `scripts/aeon-dispatch.sh` を単一入口にし、Codex 担当ロールを同一端末で起動する
follow_up: 将来 role mapping が増えたら `.claude/agent-config.sh` から role table を読み込む方式を検討する
```

```text
id: EV-20260530-002
date: 2026-05-30
agent: Codex
task: Codex exec runtime extension for reviewer and evaluator
scope: scripts/codex-exec.sh, scripts/codex-reviewer.sh, scripts/codex-evaluator.sh, docs/agents/reviewer.md, docs/agents/evaluator.md, .claude/agents/reviewer.md, .claude/agents/evaluator.md
evidence:
  - type: file
    reference: docs/agents/reviewer.md
    summary: Reviewer agent の責務と sprint review / external PR review の2モードが既に詳細定義されていた
  - type: file
    reference: docs/agents/evaluator.md
    summary: Evaluator agent の責務と Playwright ベースの評価フローが既に詳細定義されていた
  - type: file
    reference: .claude/agents/reviewer.md
    summary: runtime 定義は Reviewer を別ロールとして公開していた
  - type: file
    reference: .claude/agents/evaluator.md
    summary: runtime 定義は Evaluator を別ロールとして公開していた
  - type: command
    reference: bash -n scripts/codex-exec.sh
    summary: 既存の role dispatcher に新規 role を追加しても構文上は問題ないことを確認済み
confidence: high
tradeoff: reviewer / evaluator も同一ディスパッチ基盤に載せることで運用は揃う一方、各 role のプロンプトが増えるほど dispatcher が長くなる
decision: codex exec の runtime wrapper を reviewer / evaluator まで拡張し、role-specific entrypoint を用意する
follow_up: 役割が増えたら `scripts/codex-*.sh` の共通化を検討する
```

```text
id: EV-20260530-001
date: 2026-05-30
agent: Codex
task: Codex exec non-interactive runtime sync
scope: .claude/agents, scripts/codex-exec.sh, scripts/codex-research.sh, scripts/codex-planner.sh, scripts/codex-architect.sh, docs/agents/research.md, docs/agents/architect.md
evidence:
  - type: file
    reference: docs/agents/research.md
    summary: Research agent の責務と出力先が既に詳細定義として存在していた
  - type: file
    reference: docs/agents/architect.md
    summary: Architect agent の責務と出力先が既に詳細定義として存在していた
  - type: file
    reference: .claude/agents/
    summary: runtime 定義に research / architect が欠けていた
  - type: file
    reference: scripts/codex-generator.sh
    summary: 既存の Codex ラッパーは対話型 Generator 専用で、非対話 exec ラッパーは存在しなかった
  - type: command
    reference: codex exec --help
    summary: Codex CLI は `exec` サブコマンドで非対話実行し、`--sandbox workspace-write` と `--cd` が使えることを確認した
confidence: high
tradeoff: research/planner/architect の役割を個別スクリプトに分けることで呼び出しは明示的になる一方、将来の役割追加時には薄い wrapper が増える
decision: non-interactive Codex は `codex exec` を正にして role-specific wrapper を追加し、runtime 定義も `.claude/agents` 側に同期する
follow_up: 将来必要なら Evaluator / Reviewer 向けの `codex exec` ラッパーも同じ方式で追加する
```

```text
id: EV-20260529-003
date: 2026-05-29
agent: Claude Code (orchestrator)
task: Forget-proof working memory implementation
scope: AGENTS.md, docs/ai-agents/task-template.md, tasks/todo.md, docs/runbooks/monitoring-vps-migration.md, docs/PARALLEL_TERMINAL_GUIDE.md, scripts/check-task-state.sh, .github/workflows/task-state-check.yml
evidence:
  - type: file
    reference: tasks/todo.md
    summary: 既存の台帳は「なし」のみで状態管理が存在しなかった → 生きたタスクテーブルに置き換え
  - type: file
    reference: .claude-pipeline/active-work.md
    summary: ブランチ占有管理は存在するが進捗状態（現在地/次の一手）は持っていない
  - type: file
    reference: docs/ai-agents/evidence-registry.md
    summary: Evidence Registry は存在するがタスク台帳との連携ルールが未定義だった
  - type: file
    reference: docs/runbooks/monitoring-vps-migration.md
    summary: スプリント状態テーブルが存在せず、会話メモリに依存していた
  - type: command
    reference: rg -n "現在地|次の一手|スプリント状態" tasks docs AGENTS.md
    summary: 実装前は該当するフィールドがどのファイルにも存在しなかった
confidence: high
tradeoff: tasks/todo.md を正本にすることで更新漏れリスクが残る。CI lint（check-task-state.sh）で構造違反を検出することで緩和する
decision: tasks/todo.md をタスク台帳正本とし、runbook にスプリント状態テーブルを追加。AGENTS.md に引き継ぎ必須ルールを明記。CI で構造チェックを自動実行
follow_up: 30日後に運用実態を確認し、更新漏れが多ければ ADR 化を検討
```

```text
id: EV-20260529-002
date: 2026-05-29
agent: Governance
task: Agent Operating System architecture setup
scope: AGENTS.md, docs/agents, docs/schemas, docs/ai-agents, .github/workflows inventory
evidence:
  - type: file
    reference: AGENTS.md
    summary: Runtime Prompt を短文参照方式へ変更
  - type: file
    reference: docs/agents/
    summary: 6 Agent の詳細定義を責務固定で作成
  - type: file
    reference: docs/schemas/
    summary: Research / Planner / Review / Evaluation / Governance の schema を作成
  - type: command
    reference: rg -n "design-review-gate|design review gate|Design Review Gate|design_review_gate|design-review" .github/workflows docs AGENTS.md CLAUDE.md .codex/config.toml
    summary: design-review-gate は既存 workflow/job として見つからなかった
confidence: medium
tradeoff: GitHub Ruleset の実登録状態は GitHub UI/API 確認が必要。workflow は今回変更しない
decision: Governance を runtime pipeline 外へ分離する移行案を docs/agents/governance.md に記録し、既存 workflow は温存
follow_up: 別 PR で governance job 分離と design-review-gate 追加要否を判断
```

```text
id: EV-20260529-001
date: 2026-05-29
agent: Governance
task: Codex AI Agent operating standard setup
scope: ~/.codex/config.toml, AGENTS.md, .codex/config.toml, docs/ai-agents
evidence:
  - type: file
    reference: AGENTS.md
    summary: 既存のプロジェクト共通ルール、不可逆操作、i18n、ADR 参照方針を確認
  - type: file
    reference: CLAUDE.md
    summary: Claude 側の役割分離、ADR-012、ADR-076、SSoT 索引を確認
  - type: file
    reference: .codex/config.toml
    summary: 既存設定は disk-full-read-access のみだったため、安全デフォルトへ更新
  - type: command
    reference: rg -n "<禁止モデル名>|gpt-5\\.5|gpt-5" ~/.codex/config.toml AGENTS.md CLAUDE.md .codex/config.toml README.md docs
    summary: 禁止モデル名は設定値・起動プロファイルから除去し、文書上は使用禁止ルールとしてのみ記載
confidence: medium
tradeoff: repo 全体探索を避けたため、指定範囲外に同種設定が残っている可能性は未確認
decision: Agent 役割、読取範囲、Evidence 必須化、repo 全体探索禁止を標準化
follow_up: 実運用後に ADR 化が必要か Governance が判断する
```

```text
id: EV-20260529-004
date: 2026-05-29
agent: Governance
task: Claude Code KPI / Grafana observability design
scope: AGENTS.md, docs/ai-agents/kpi.md, docs/agents/governance.md, monitoring/prometheus/prometheus.yml, monitoring/grafana/provisioning/dashboards/json/monitoring-main.json, docs/schemas/evaluation-package-v1.yaml
evidence:
  - type: file
    reference: AGENTS.md
    summary: KPI の正本を 1 ファイルに固定する方針を追記
  - type: file
    reference: docs/agents/governance.md
    summary: Governance の metric 定義を docs/ai-agents/kpi.md 参照に分離
  - type: file
    reference: monitoring/prometheus/prometheus.yml
    summary: 既存の Prometheus 収集基盤があり、追加 exporter を載せる土台がある
  - type: file
    reference: docs/schemas/evaluation-package-v1.yaml
    summary: Evaluator の合否と evidence 形式が既に schema 化されている
  - type: external
    reference: https://docs.anthropic.com/en/docs/claude-code/monitoring-usage
    summary: Claude Code telemetry で session / token / cost 系メトリクスが観測可能
  - type: external
    reference: https://docs.anthropic.com/en/api/data-usage-cost-api
    summary: Anthropic Admin API は個人アカウントでは利用不可
confidence: high
tradeoff: 個人 Pro Max では公式請求原本は取れないため、token/cost は telemetry proxy と manual mapping に分離する必要がある
decision: docs/ai-agents/kpi.md を KPI 正本とし、GitHub direct metrics / Claude telemetry / manual mapping / unavailable metrics を分離して設計する
follow_up: GitHub collector と Claude telemetry collector の実装計画を別 PR で具体化する
```

```text
id: EV-20260530-012
date: 2026-05-30
agent: Agent
task: AEON dispatcher smoke validation
scope: scripts/aeon-delivery.sh, scripts/aeon-dispatch.sh, scripts/codex-generator.sh, docs/ai-agents/evidence-registry.md, tasks/todo.md
evidence:
  - type: command
    reference: bash scripts/aeon-delivery.sh --smoke "AEON smoke validation: start all stages and return no-op reports only. Do not modify files. Do not inspect beyond what is needed to confirm the runner path. Stop after the stage sequence completes or the first blocker is found."
    summary: research -> planner -> architect -> generator -> evaluator -> reviewer の smoke ルートが同一ターミナルから完走し、generator は no-op、reviewer は REQUEST_CHANGES の smoke 応答を返した
  - type: file
    reference: /tmp/aeon-delivery-20260530-052601.log
    summary: delivery run の complete log が保存されている
  - type: file
    reference: tasks/todo.md
    summary: AEON ディスパッチャ行を完了側へ移動した
confidence: high
tradeoff: smoke validation はレビュー判定の実体ではなく、起動経路と run loop の到達性確認に限定される
decision: AEON delivery/release runner は smoke 完走まで確認でき、同一ターミナルからの Codex 呼び出し経路は実用可能と判断する
follow_up: live PR がある場合のみ `scripts/aeon-release.sh <PR番号>` で release 実行に進める
```

```text
id: EV-20260530-013
date: 2026-05-30
agent: Agent
task: AEON operation guide canonicalization
scope: docs/ai-agents/aeon-operation.md, docs/ai-agents/aeon-routing.md, docs/ai-agents/aeon-delivery.md, docs/ai-agents/aeon-release.md, docs/onboarding/claude-code.md, docs/ai-agents/agent-roles.md, tasks/todo.md
evidence:
  - type: file
    reference: docs/ai-agents/aeon-operation.md
    summary: delivery と release を 1 枚にまとめた canonical operating procedure を追加
  - type: file
    reference: docs/ai-agents/aeon-routing.md
    summary: routing index から canonical operation guide へ誘導した
  - type: file
    reference: docs/onboarding/claude-code.md
    summary: onboarding から canonical operation guide を参照するよう更新した
confidence: high
tradeoff: 既存の aeon-* ドキュメントは軽量索引として残し、重複説明は参照誘導に寄せた
decision: AEON の運用手順は `docs/ai-agents/aeon-operation.md` を正本とし、delivery / release / onboarding はそこへ集約する
follow_up: 新しい AEON 変更はまず operation guide と evidence-registry を更新してから関連索引へ反映する
```

```

```text
id: EV-20260530-001
date: 2026-05-30
agent: Claude Code (Hikky-dev)
task: Generator executor 選択 + Codex→Claude Code 自動フォールバック実装
scope: .github/workflows/claude-pipeline.yml / AGENTS.md / docs/adr/ADR-082
evidence:
  - type: adr
    reference: docs/adr/ADR-082-generator-executor-codex-fallback.md
    summary: generator_executor input (auto/codex/claude) の設計根拠・AC・トレードオフを記録
  - type: file
    reference: .github/workflows/claude-pipeline.yml
    summary: claude-worker L335-389 / regenerate L1035-1078 にフォールバックロジック実装。GENERATOR_FALLBACK env で Discord 通知を制御
  - type: file
    reference: AGENTS.md
    summary: 役割分担テーブルの「ジェネレーター」行に自動フォールバックを明記。§Generator Executor 切り替え を追加
  - type: command
    reference: governance agent 実行（2026-05-30）
    summary: MONITOR 判定。ADR 未記録・AGENTS.md 未反映・evidence-registry 未記録の3ギャップを特定 → 本エントリで解消
confidence: high
tradeoff: auto モードでは実際の executor をログで確認する必要がある。Codex が安定したら codex 専用モードへの移行を検討
decision: generator_executor=auto をデフォルトとし、Codex 不在・失敗時は自動で Claude Code にフォールバックする
follow_up: Codex フォールバック Discord 通知が頻発する場合は self-hosted runner の codex CLI インストールを確認する
```text
id: EV-20260530-014
date: 2026-05-30
agent: Agent
task: release develop → main completion for AEON sync
scope: PR #1178, gh pr checks 1178, gh pr merge 1178 --merge --delete-branch, tasks/todo.md, docs/ai-agents/evidence-registry.md
evidence:
  - type: command
    reference: gh pr checks 1178
    summary: Playwright E2E (chromium) と pytest-run-internal が pass し、release PR の必須チェックが揃った
  - type: command
    reference: gh pr merge 1178 --merge --delete-branch
    summary: GitHub 上で PR #1178 が MERGED になり、merge commit 341c399a505e3150a54612de6055fdbabbacc56a が生成された
  - type: command
    reference: gh pr view 1178 --json state,mergedAt,mergeCommit,url,mergeStateStatus
    summary: state=MERGED, mergedAt=2026-05-29T21:24:21Z, mergeCommit=341c399a505e3150a54612de6055fdbabbacc56a を確認した
confidence: high
tradeoff: local `gh pr merge` は worktree の branch checkout 制約で delete-branch に失敗したが、GitHub 側の merge 自体は完了した
decision: AEON 関連の develop → main release は PR #1178 で完了したとみなし、次の release 系作業では main 側の差分だけを別途確認する
follow_up: `tasks/todo.md` の完了欄と release 関連 runbook を必要に応じて参照更新する
```

## Review Rules

- `confidence: high` は一次情報が複数あり、再現可能な検証がある場合に限る
- `confidence: medium` は一次情報はあるが範囲制限や未検証リスクが残る場合
- `confidence: low` は仮説、未検証、外部依存が強い場合
- Evidence なしのルール追加は禁止

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

## Review Rules

- `confidence: high` は一次情報が複数あり、再現可能な検証がある場合に限る
- `confidence: medium` は一次情報はあるが範囲制限や未検証リスクが残る場合
- `confidence: low` は仮説、未検証、外部依存が強い場合
- Evidence なしのルール追加は禁止

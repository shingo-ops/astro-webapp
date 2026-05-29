# AI Agent KPI Canonical Definition

Sales Anchor の AI Agent / Claude Code / GitHub / Grafana の計測定義の正本。

## Purpose

この文書は、以下を分けて管理する。

- GitHub から自動取得できる指標
- Claude Code telemetry から取得できる指標
- `user.id` と人名の対応表で補う指標
- 現在の `Pro Max` / 共有アカウントでは取得できない指標

## Top-Level KGI

### AEON Mainline Delivery Completion Rate

SalesAnchor の AI Agent 運用における最上位 KGI は、`Claude Code` が同一端末の `aeon-dispatch.sh` から `Codex` 担当エージェントを起動し、コード変更を `main` へマージ完了まで到達させられる割合である。

This KGI is the end-to-end measure for "Claude Code can call Codex and finish PR → main."

#### Formula

`AEON Mainline Delivery Completion Rate = completed_mainline_deliveries / initiated_aeon_deliveries`

- `initiated_aeon_deliveries`: `scripts/aeon-dispatch.sh` から AEON ロールを起動し、実装 or レビュー or 評価のいずれかを開始した件数
- `completed_mainline_deliveries`: GitHub PR が作成され、必要なレビュー / 評価を通過し、`main` に正常マージされた件数

#### Completion Criteria

1. `Claude Code` から同一ターミナルで `scripts/aeon-dispatch.sh` を呼び出せる
2. Codex 担当ロールが `research / planner / architect / reviewer / evaluator / generator` のいずれかとして起動できる
3. 変更がローカル commit まで到達する
4. GitHub PR が作成される
5. Reviewer / Evaluator の gate を通過する
6. `scripts/aeon-release.sh` で `main` へ merge 完了する
7. 途中の手動介入は Evidence Registry で追跡可能である

#### Initial Targets

- Observation window: 30 days or 10 AEON deliveries, whichever comes first
- Stabilization target: `>= 80%`
- Standard target after stabilization: `>= 95%`

#### Supporting KPIs

- AEON Dispatch Success Rate: `successful_role_invocations / attempted_role_invocations`
- PR Creation Rate: `prs_created / deliveries_started`
- Review Gate Pass Rate: `reviewer_approved / reviewer_submissions`
- Evaluation Pass Rate: `evaluator_passed / evaluator_runs`
- Main Merge Completion Rate: `merged_to_main / prs_opened`
- Manual Intervention Count: number of times a delivery could not continue without direct human terminal handoff
- Median Time To Main: `median(main_merged_at - delivery_started_at)`

## Operating Assumptions

- Claude Code の利用は共有アカウントだが、実行マシンはパートナーごとに別。
- `user.id` は Claude Code のインストール単位の匿名識別子として扱う。
- `user.id` は人名を含まないため、`partner_id` への変換は手動対応表で行う。
- Anthropic の Admin API に依存する厳密な org-level 集計は、個人 `Pro Max` では対象外。

## Metric Tiers

### Tier 1: Direct GitHub Metrics

| Metric | Formula | Source | Automation | Notes |
|--------|---------|--------|------------|-------|
| Lead Time | `merged_at - created_at` | GitHub PR API | yes | PR 単位で集計可能 |
| Cycle Time | `approved_at - opened_at` | GitHub reviews / PR timeline | yes | 最終承認までの時間 |
| Reviewer Change Request Rate | `CHANGES_REQUESTED / total_reviews` | GitHub review events | yes | レビュー品質指標 |
| Acceptance Pass Rate | `passed_checks / total_required_checks` | GitHub Checks / CI | yes | CI/チェック合格率 |
| Rule Compliance Rate | `compliant_prs / total_prs` | GitHub checks + policy checks | yes | 必須ルール準拠率 |
| Rework Rate | `additional_pushes / total_prs` | GitHub PR events | yes | 追加 push 回数の代理指標 |
| PR Stall Time | `last_activity - first_activity` | GitHub PR timeline | yes | 放置/停滞の代理指標 |
| Scope Drift Count | `scope_outside_changes` | ADR / diff comparison | partial | スクリプト補助が必要 |
| Active-Work Overlap | `overlap_count / active_tasks` | `active-work.md` parser | partial | パターン依存のため補助処理が必要 |

### Tier 2: Claude Code Telemetry Metrics

| Metric | Formula | Source | Automation | Notes |
|--------|---------|--------|------------|-------|
| Session Count | `sessions` | Claude Code telemetry | yes | `session.id` で集計 |
| PR Count | `claude_code.pull_request.count` | Claude Code telemetry | yes | 操作単位の実績 |
| Commit Count | `claude_code.commit.count` | Claude Code telemetry | yes | 実装活動の代理指標 |
| Token Usage | `claude_code.token.usage` | Claude Code telemetry | yes | 請求原本ではなく運用観測値 |
| Cost Usage | `claude_code.cost.usage` | Claude Code telemetry | yes | 個人プランでは推定/観測値として扱う |
| Model Mix | `model` 別集計 | Claude Code telemetry | yes | 役割ごとのモデル偏り確認 |

### Tier 3: Manual Mapping Required

| Metric | Formula | Source | Automation | Notes |
|--------|---------|--------|------------|-------|
| Partner Usage | `user.id -> partner_id` | manual mapping table | partial | 別マシンなら切り分け可能 |
| Machine Usage | `user.id -> machine_name` | manual mapping table | partial | 共有マシンでは区別不可 |
| Partner Share | `partner_usage / total_usage` | mapping + telemetry | partial | Grafana 上で可視化 |

### Tier 4: Not Available in Current Plan

| Metric | Status | Reason |
|--------|--------|--------|
| Organization-grade exact token billing | unavailable | 個人 `Pro Max` では Anthropic Admin API が使えない |
| PR-by-PR official billing token total | unavailable | 公開 API で PR 単位の請求原本が出ない |
| Human identity auto-resolution from `user.id` | unavailable | `user.id` は匿名識別子のため |

## Data Sources

### GitHub

- PR create / merge timestamps
- review events
- check runs / required checks
- PR push history
- branch / commit metadata

### Claude Code Telemetry

- `user.id`
- `session.id`
- `organization.id`
- `model`
- `claude_code.token.usage`
- `claude_code.cost.usage`
- `claude_code.pull_request.count`
- `claude_code.commit.count`

### Repo Files

- `tasks/todo.md`
- `.claude-pipeline/active-work.md`
- `docs/ai-agents/evidence-registry.md`
- `docs/adr/*`

## Required Mapping Table

`user.id` を人名に変換するため、次の対応表を別管理する。

| user.id | partner_id | display_name | machine_name | last_confirmed |
|---------|------------|--------------|--------------|----------------|
| UUID    | partner key | 人名/略称 | host name | YYYY-MM-DD |

Rules:

- 1 machine, 1 `user.id` を前提にする
- `user.id` の再利用や再インストール時は再確認する
- 同一マシン共有時は `partner_id` の手動記録を優先する

## Implementation Plan

### Phase 1: Metric Canonicalization

1. この文書を KPI の正本にする
2. GitHub 指標と Claude Code 指標を分離する
3. `user.id` ベースの対応表ルールを定義する

### Phase 2: Collection

1. GitHub PR collector を追加する
2. Claude Code telemetry collector を追加する
3. 手動対応表を読み込む

### Phase 3: Storage

1. Prometheus に export する
2. 代理指標と direct 指標を分けて保存する
3. `partner_id` で集計できる形にする

### Phase 4: Visualization

1. Grafana に KPI dashboard を追加する
2. 速度 / 品質 / コスト / 定着 の 4 面で表示する
3. 自動指標と proxy 指標をラベルで区別する

### Phase 5: Validation

1. 1 週間の sample window で欠損率を確認する
2. `user.id` の対応表が正しいかを検証する
3. 取りこぼしがあれば manual fallback を明記する
4. AEON Mainline Delivery Completion Rate を 30 日 / 10 deliveries で観測し、KGI として継続採用するか判定する

## Acceptance Criteria

- GitHub 指標は PR 単位で自動取得できる
- Claude Code telemetry は `user.id` 単位で自動取得できる
- `user.id` から `partner_id` への対応表が運用できる
- 個人 `Pro Max` で不可能な指標は代替指標に置換されている
- Grafana に表示可能な粒度まで定義されている
- AEON Mainline Delivery Completion Rate が、Claude Code → Codex → PR → main の完了を示す最上位 KGI として定義されている

## Non-goals

- Anthropic Admin API による org-level 厳密集計の強制
- 公式請求データの自動取得
- `user.id` から人名への自動復元
- 共有マシン前提の個人別厳密集計

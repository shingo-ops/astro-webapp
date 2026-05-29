# ADR-081: design-review-gate 廃止 — develop までの自動化方針との整合

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-30 |
| 起案 | Claude Code (Hikky-dev) / Codex |
| 関連 ADR | ADR-042（ガードレール強化）/ ADR-050（Release PR workflow）/ ADR-056（Human-in-the-Loop Minimization）/ ADR-077（GitHub Actions CI メトリクス） |

## What

design-review-gate を廃止する。

PR の設計レビュー証跡を Required Status Check として強制する仕組みをやめ、develop までの自動化方針と運用を一致させる。

### 廃止対象

- `.github/workflows/design-review-gate.yml`
- `scripts/check-design-review.py`
- `AGENTS.md` の設計レビューゲート節
- `.github/PULL_REQUEST_TEMPLATE.md` の Design Review Evidence 節

### 非対象

- `.github/workflows/claude-pipeline.yml` の `--admin` merge 方針は維持する
- `docs/ai-agents/evidence-registry.md` は履歴として残す
- `docs/agents/governance.md` は変更しない

## Why

### 1. 実効性が低い

design-review-gate は、PR に設計レビュー証跡があるかを確認するだけで、承認主体そのものではない。
`claude-pipeline.yml` は `--admin` により branch protection をバイパスして develop に merge できる。
そのため、Required Status Check として残しても、実運用上の統制力は弱い。

### 2. 方針と責務が重複している

ADR-056 以降、develop までの自動化は既定方針になっている。
design-review-gate はその方針と役割が重複し、運用ルールを二重化している。

### 3. CI が同等の役割を担っている

pytest / Playwright E2E / lint / gitleaks / テナントスキーマ整合性チェック等の Required Status Check が
コード品質・セキュリティ・設計ルール遵守を機械的に強制しており、設計上の問題はこれらで検出できる。
design-review-gate が追加しようとした「人間の設計判断の証跡」は、CI では測れない観点だが、
`--admin` 運用下では実効的なブロックにならない。

### 4. PR 運用のノイズになる

PR テンプレートで設計レビュー文面を要求し、CI でも同じ証跡を確認する構造は、
実効性の低い要求を継続させるだけで運用負荷を増やす。

## Scope IN

- `design-review-gate.yml` の削除
- `check-design-review.py` の削除
- `AGENTS.md` の設計レビューゲート節の削除
- `.github/PULL_REQUEST_TEMPLATE.md` の Design Review Evidence 節の削除

## Scope OUT

- `claude-pipeline.yml` の `--admin` merge 方針変更
- reviewer / evaluator 自動化ロジックの変更
- `docs/agents/governance.md` の改訂
- `docs/ai-agents/evidence-registry.md` の履歴整理
- 新しい bot / GitHub App の導入

## Business constraints

- develop までの自動化を壊さないこと
- main / release 側の統制は別 ADR で扱うこと

## Consequences

### Positive

- develop までの自動化方針と実装が一致する
- 形骸化したゲートを維持しなくてよくなる
- Required Status Check の管理が簡素化される
- PR テンプレートの記入負荷が減る

### Negative

- 設計レビュー証跡を CI で強制する仕組みはなくなる
- 人間がレビュー済みであることの機械的な保証は失われる

### Mitigation

- 重要変更は reviewer / evaluator / governance の既存フローで扱う
- main や release 側の統制が必要になった場合は別 ADR で再設計する

## ADR リレーション

| 関連 ADR | 関係 |
|---------|------|
| ADR-042 | `--admin` を含む運用ガードレールの基本方針 |
| ADR-050 | release PR と branch protection の前提 |
| ADR-056 | develop までの完全自動化方針（本 ADR の根拠） |
| ADR-077 | GitHub Actions の可視化基盤。監視対象としては残せるが、承認ゲートとしては不要 |

## Acceptance Criteria

- [ ] `.github/workflows/design-review-gate.yml` が削除されている
- [ ] `scripts/check-design-review.py` が削除されている
- [ ] `AGENTS.md` から設計レビューゲート節が削除されている
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` から Design Review Evidence 節が削除されている
- [ ] `rg -n "design-review-gate|Design Review Evidence|Design Review: APPROVED" .` で運用上の残骸がない

## Rollback

必要であれば以下を戻す。

- `design-review-gate.yml` を復元する
- `check-design-review.py` を復元する
- `AGENTS.md` と `.github/PULL_REQUEST_TEMPLATE.md` を戻す

ただし、ロールバックする場合は `--admin` merge 方針との整合を再度確認する必要がある。

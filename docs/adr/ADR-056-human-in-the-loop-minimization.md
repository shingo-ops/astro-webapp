# ADR-056: Human-in-the-Loop Minimization — Auto-Regenerate + Auto-Merge to develop + Notification Consolidation

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `.github/workflows/claude-pipeline.yml` / `docs/proposals/agents-role-clarification-prompt.md` / `~/.claude/agents/*.md`
- **関連 ADR**: ADR-042 (4 エージェント体制), ADR-048 (Web Claude 外部補助), ADR-050 (Release PR), ADR-051 (pipeline 自動化), ADR-053 (decision parsing fix)

---

## 1. 背景

### 1-1. 現状の人間介在ポイント

ADR-051 / ADR-053 で reviewer / evaluator 自動化を達成したが、しんごさんが 1 ADR あたり **5 箇所で介在** する状態が継続:

1. PR open 後、Discord 通知でしんごさんが diff 確認指示を受ける
2. Web Claude に diff 検証依頼
3. Reviewer REQUEST_CHANGES 時、しんごさんが Generator に修正指示
4. Evaluator REQUEST_CHANGES 時、しんごさんが Generator に修正指示
5. 両 APPROVED 後、しんごさんが `gh pr merge` で develop に merge

加えて Discord 通知が 1 ADR で **6 通**飛ぶ (claude-worker 開始/完了、reviewer 開始/結果、evaluator 開始/結果)。

### 1-2. しんごさんからの問題提起

> 「私に全て仲介させるせいで思考リソースを取られるし、他の業務に集中できない。
>  以前より冗長で私が仲介する意図が不明。
>  AIエージェントが技術的な部分のレビューを行なっているため、技術スタックの知識のない私は
>  ユーザー視点での動作確認だけ私が行えばいいのでは？
>  developまでは私が仲介する意味はない」

### 1-3. エビデンス確認結果

`agents-role-clarification-prompt.md` (develop 反映済み) の調査結果:

| 項目 | 現状定義 | 根拠の有無 |
|---|---|---|
| 「最終 merge は人間」原則 | ADR-042 / ADR-048 / ADR-050 で明記 | ❌ なぜ人間が必要か明文化されていない |
| Web Claude の diff 検証 | プロジェクト指示で「補助的」と定義 | ✅ 補助的、削除可能 |
| Reviewer / Evaluator の自動判定 | ADR-051 で自動化済み | ✅ 機能している (ADR-046〜055 で実績) |

**「人間 merge 原則」は ADR-042 起案時 (エージェント判断信頼性が未検証だった時期) の保険**。ADR-046〜055 の連鎖で Reviewer/Evaluator は十分機能している証拠が積み上がった。

### 1-4. 人間が本当に価値追加できるポイント

- **What/Why の意思決定** (Planner) — AI で代替不可
- **本番反映後のユーザー視点確認** — AI で代替不可、しんごさんの強み
- **main merge の最終判断** — 本番影響、保険として残す価値あり

逆に、以下は人間が介在する価値が薄い:

- **develop への feature merge** — Reviewer/Evaluator が判定済み、人間の追加判断は冗長
- **diff の技術的確認** — Web Claude は最近ほぼ「マージ OK」を出すだけ
- **Reviewer REQUEST_CHANGES への対応** — Generator が同じ PR ブランチに修正 push する設計だが、しんごさんが起動指示している

---

## 2. 決定（What）

### 2-1. develop までの完全自動化

`claude-pipeline.yml` に以下を実装:

```
ADR push
  ↓
claude-worker (Generator) → PR open
  ↓
reviewer 自動起動
  ↓
  ├─ APPROVED → evaluator 自動起動
  │     ↓
  │     ├─ APPROVED → 自動 merge to develop (--squash --delete-branch)
  │     │     ↓
  │     │     Discord 通知 1 件: 「ADR-XXX develop merged」
  │     │
  │     └─ REQUEST_CHANGES → regenerate job 自動起動 (§2-2)
  │
  └─ REQUEST_CHANGES → regenerate job 自動起動 (§2-2)
```

### 2-2. 自動修正 (regenerate job)

reviewer または evaluator が REQUEST_CHANGES を出した場合、`regenerate` job が自動起動:

```yaml
regenerate:
  needs: [reviewer, evaluator]
  if: |
    needs.reviewer.outputs.decision == 'REQUEST_CHANGES' ||
    needs.evaluator.outputs.decision == 'REQUEST_CHANGES'
  runs-on: self-hosted
  steps:
    - checkout PR branch
    - Run Claude Code as Generator (regenerate mode)
      # 入力: ADR + Reviewer/Evaluator の指摘内容 (gh pr view コメント)
      # 出力: 同じ PR ブランチに修正 commit + push
    - push が成功すれば reviewer が自動再起動 (push trigger)
```

### 2-3. 自動修正の暴走防止

| 制約 | 値 | 検出方法 |
|---|---|---|
| 最大リトライ回数 | **3 回** | PR labels (`auto-retry-1` / `auto-retry-2` / `auto-retry-3`) で追跡 |
| 同一指摘の繰り返し | 2 回連続で同じ指摘 → 中断 | reviewer/evaluator のコメント diff 比較 |
| 累積 token 消費上限 | 1 ADR あたり 200K token | claude-worker step 内で計測 |
| 中断時の挙動 | Discord 通知 + PR に `needs-human-intervention` label 付与 + 自動修正停止 | regenerate job で if 条件 |

### 2-4. Discord 通知の整理

| イベント | 現状 | 新仕様 |
|---|---|---|
| claude-worker 開始 | 通知あり | ✅ 削除 |
| claude-worker 完了 (PR open) | 通知あり | ✅ 削除 |
| reviewer 開始 | 通知あり | ✅ 削除 |
| reviewer APPROVED | 通知あり | ✅ 削除 |
| reviewer REQUEST_CHANGES (リトライ内) | 通知あり | ✅ 削除 (自動修正) |
| evaluator 開始 | 通知あり | ✅ 削除 |
| evaluator APPROVED | 通知あり | ✅ 削除 |
| evaluator REQUEST_CHANGES (リトライ内) | 通知あり | ✅ 削除 (自動修正) |
| **develop merge 完了** | なし | ✅ **追加** (本 ADR の主要通知) |
| **リトライ上限到達 (人間介入必要)** | なし | ✅ **追加** |
| **job 例外 FAILURE** | 通知あり | ✅ 維持 |

**通常 1 ADR で Discord 通知は 1 件のみ** (develop merge 完了)。

### 2-5. 自動 merge の実装

両 APPROVE 後、自動的に:

```bash
gh pr merge <PR番号> --squash --delete-branch
```

`--delete-branch` は **feature ブランチのみ** (claude-impl/*) — ADR-050 規約遵守。GitHub Ruleset (`Protect develop branch from deletion`) で develop は技術的に保護済み。

### 2-6. main merge は人間判断を維持

本 ADR は **develop までの自動化** のみ。main merge (release PR) は引き続き **しんごさんが手動** で実行。理由:

- 本番反映影響、保険として残す価値あり
- ユーザー視点での目視確認の前提として、ある程度の develop 蓄積を待つ判断は人間が下すべき
- ADR-050 の Release PR ワークフローは無変更

### 2-7. Web Claude の diff 検証 (補助役) も削除

Web Claude の diff 検証は **不要に**。今後の運用:

- Web Claude は **ADR 起案時の Planner 補助** のみに専念 (ADR-048 §2-2 強み発揮)
- PR open 後の diff 検証は行わない
- しんごさんが「Web Claude の意見を聞きたい」場合のみ介在 (オプション)

### 2-8. agents-role-clarification-prompt.md 更新

「起動方法」セクションに新フロー反映、新 grep 項目追加:

```bash
grep -c "auto-merge to develop" ~/.claude/agents/generator.md
grep -c "regenerate" ~/.claude/agents/generator.md
grep -c "auto-retry" ~/.claude/agents/reviewer.md
```

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | しんごさんの思考リソース解放 — develop までの 5 介在 → 0 介在 | **最優先** |
| 2 | Discord 通知 6 → 1 で集中力維持 | 高 |
| 3 | Reviewer/Evaluator の判断信頼性が実証されたため、人間二重チェックの冗長性を解消 | 高 |
| 4 | しんごさんの強み (ユーザー視点目視 + 事業判断) に集中、技術判定は AI に委譲 | 高 |
| 5 | Web Claude の diff 検証往復を削除し、Planner 役に集中 | 中 |

---

## 4. Scope 外

- **main merge の自動化** — 本 ADR では人間判断維持 (将来別 ADR で検討余地)
- **本番反映後の目視確認の自動化** — しんごさんの強み、AI で代替しない
- **Reviewer / Evaluator の判定ロジック変更** — 既存維持
- **Playwright MCP セットアップ** — ADR-055 のスコープ
- **claude-worker (Generator) の能力強化** — 既存維持
- **release PR (develop → main) ワークフローの変更** — ADR-050 で確立済、無変更
- **GitHub Ruleset の追加変更** — develop 削除禁止は維持

---

## 5. 事業上の制約

### 5-1. 安全装置

- 自動 merge は **両 APPROVE 時のみ**
- リトライ上限 (3 回 / 1 ADR) で無限ループ防止
- `needs-human-intervention` label 付き PR は **自動 merge されない**
- main ブランチ保護 (ADR-010) と develop ブランチ保護 (ADR-050) は維持

### 5-2. 既存 ADR との整合

- ADR-042 「最終 merge は人間」原則を **main merge のみに限定**するよう ADR-042 を更新参照
- ADR-048 Web Claude 外部補助 Planner 役は維持、diff 検証は外す
- ADR-050 Release PR (develop → main) は無変更
- ADR-051 claude-pipeline 構造は拡張のみ

### 5-3. パートナー (ひとし) 環境への影響

ADR-048 §2-3 「両環境で等価出力」のため、ひとしさん環境にも同じ自動化が適用される。**ひとしさんへの事前共有が必要** (本 ADR §10 認知限界で明示)。

### 5-4. 緊急停止メカニズム

問題発生時にしんごさんが claude-pipeline を即座に停止できるよう:

- GitHub Actions UI から workflow を `disabled` にする
- または、PR に `pause-automation` label を付けると自動 merge / regenerate が停止 (label check を if 条件に追加)

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright (or HTML fallback) — workflow YAML 構造検査 + 次の本物 ADR で動作確認
- [ ] Skip — UI なしだが workflow 動作確認が必要

### Reviewer 追加観点

- [ ] `claude-pipeline.yml` に `regenerate` job が定義されているか
- [ ] reviewer / evaluator REQUEST_CHANGES 時の自動修正条件が正しいか
- [ ] リトライ上限 (3 回) が PR label で追跡されているか
- [ ] 両 APPROVE 時の自動 merge ロジックがあるか
- [ ] `--delete-branch` が feature ブランチのみ適用されているか (ADR-050 規約)
- [ ] Discord 通知が `develop merge 完了` / `リトライ上限` / `FAILURE` のみに整理されているか
- [ ] `pause-automation` label による緊急停止が実装されているか
- [ ] `agents-role-clarification-prompt.md` に新フロー反映、新 grep 項目追加

### 動作確認 (人間)

ADR-056 マージ後、次の軽量 ADR を 1 本通して:

1. ADR push → develop merge まで **しんごさんが介在せず** に完了するか
2. Discord 通知が 1 件 (develop merge) のみか
3. 故意に REQUEST_CHANGES が出る ADR を投入 → regenerate が自動起動するか
4. リトライ 3 回到達 → 人間介入通知が来るか
5. `pause-automation` label で自動修正が止まるか

---

## 7. 3 点セット要件

該当しない (内部 CI/CD 拡張、外部状態共有なし)。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. 現状維持 (人間 merge 原則維持) | ❌ 却下。しんごさんの思考リソース消費が継続 |
| B. Reviewer のみ自動修正、Evaluator は人間判断 | △ 部分的、Evaluator REQUEST_CHANGES でしんごさん介在残る |
| C. 通知整理のみ、自動 merge は導入しない | △ 介在ポイントは残る |
| D. main merge も自動化 | ❌ 却下。本番影響、保険を外すのは時期尚早 |
| **E. develop merge まで完全自動 + main は人間判断 (本案)** | ✅ 採用。人間の強みと AI の強みのバランス |

---

## 9. 未決事項 (Generator 判断)

- `pause-automation` label 名の最終決定 (e.g. `pipeline-pause` / `no-auto-merge` 等)
- リトライ回数 3 の値 (経験的に妥当か、調整可能か)
- regenerate job の Generator プロンプト具体内容
- 同一指摘繰り返し検出のアルゴリズム (string diff の閾値)
- token 消費 200K の値 (経験的に妥当か)
- Discord 通知文面の具体形式

---

## 10. 起案者の認知限界

- 「人間 merge 原則」が ADR-042 起案時の「保険」だったという推測は、ADR-042 ドラフト全文 (PR #397) を Web Claude が読み込んでいない上での推測。Reviewer が ADR-042 全文を再確認する必要あり
- 自動 merge による事故 (誤 merge) リスクは Reviewer / Evaluator の判定信頼性に依存。過去 PR #405〜#418 で REQUEST_CHANGES → APPROVED 連鎖 → merge は問題なく動いた実績ベースでの判断
- ひとしさん環境への影響が未確認 — ADR-056 マージ前にひとしさんと共有する必要あり
- 番号衝突確認: ADR-055 の次は 056 (Terminal CC で確認済み)
- ADR-055 (Playwright MCP) と並行起案、両者は独立で衝突なし
- 本 ADR 自体が「人間介在を減らす ADR」を人間に確認してもらっている再帰構造。最終的にしんごさんが merge 判断する点は変わらない (main 段階)

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

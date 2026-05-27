# ADR-076: パイプライン効率化（Evaluator自動スキップ・Governance自動化・重複検出改善・Researcher自動起動）

- **Status**: Accepted
- **Date**: 2026-05-27
- **Deciders**: しんごさん（PO）
- **Related**: ADR-051, ADR-056

---

## Context（背景）

claude-pipeline.yml の運用で以下4つの非効率が顕在化した:

1. UIと無関係な変更でもEvaluator（Playwrightブラウザテスト）が毎回起動し、CI時間が無駄になっていた
2. Governance（定着化検証）が手動呼び出しのみで、チェック漏れが発生するリスクがあった
3. 同一指摘の検出が1000文字完全一致のみで、文言が少し違うと同じ問題を繰り返すループが発生していた
4. Researcherが手動呼び出しのみで、ADR作成時の事前調査が抜け漏れるリスクがあった

---

## Decision（決定）

以下4つの改善をパイプラインに実装する:

### 1. Evaluator自動スキップ（PR #966）

- PRの変更ファイルに `frontend/` 配下が含まれない場合、Evaluatorを自動スキップ
- `gh pr view --json files` でファイル一覧を取得し、contextジョブのoutputに `has_ui_changes` を追加
- PRなし（workflow_dispatch）の場合は安全側（`has_ui_changes=true`）に倒す

### 2. Governance自動組み込み（PR #967）

- Evaluator APPROVED後、automergeの直前にGovernanceジョブを自動起動
- CERTIFIED / MONITOR → automerge許可
- BLOCK → exit 1でマージ停止
- Governanceジョブ失敗時はMONITORにフォールバック（パイプラインをブロックしない）

### 3. 重複指摘検出の改善（PR #968）

- 1000文字完全一致からJaccard係数（キーワード類似度）ベースに変更
- 類似度60%以上を「同一指摘」と判定
- 完全一致チェックを高速パスとして保持（後方互換）

### 4. Researcher自動起動（PR #970）

- PRで `docs/adr/ADR-*.md` が変更された場合、Researcherを自動起動
- claude-worker（Generator）の前に配置
- Researcher失敗時も後続のGeneratorはブロックされない

---

## Consequences（影響）

### 得られること

- CIの無駄な実行時間の削減（UIテストスキップ）
- Governance漏れの防止（自動化）
- 同一指摘ループの削減（類似度検出）
- ADR設計前の事前調査の自動化（Researcher）

### 失うこと・注意点

- `has_ui_changes=false` の誤検知リスク（frontend/配下以外でUIに影響するファイルが変更された場合）
- Governanceジョブの `--dangerously-skip-permissions` は他ジョブと権限設定が不統一（次スプリントで統一予定）

---

## Acceptance Criteria（受け入れ基準）

- [ ] UIファイル変更なしのPRでEvaluatorがスキップされる
- [ ] UIファイル変更ありのPRでEvaluatorが起動する
- [ ] Governance BLOCK時にautomergeが停止する
- [ ] 同一指摘（文言微差あり）で60%以上の類似度が検出される
- [ ] ADR変更を含むPRでResearcherがコメントを投稿する

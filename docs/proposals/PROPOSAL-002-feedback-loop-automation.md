# PROPOSAL-002: フィードバックループ完全自動化

**ステータス**: 提案中（Phase α は実装済 = PR #309/#311）  
**起案日**: 2026-05-08  
**起案者**: Hikky-dev（Hitoshi）  
**目標**: テスター → 改善 → リリースのループを段階的に自動化し、人間の介在を最小化する

---

## 背景

2026-05-08 にフィードバック収集パイプラインの **Phase α** がデプロイされた:

```
テスター → Google Form 送信
    ↓
Apps Script (onFormSubmit)
    ↓
├─ Sales Anchor フィードバック（回答）スプレッドシート 追記
├─ GitHub Issue 自動作成（labels: bug/enhancement/question + from-form + priority:*）
├─ Discord #📝バグ報告 通知（Embed: 重要度・該当ページ・報告者）
└─ Phase α workflow → triage-needed ラベル + メンション付きトリアージ要請コメント
```

ここまでで「Issue 立つまで」は自動化された。しかし **Issue 立った後の処理は完全に手動**:
- Hitoshi / しんごさん がコメント見る
- カテゴリ判定（trivial / needs-adr / investigation / duplicate / wontfix）
- 対応する PR or ADR を起案
- 修正 → merge → close

テスター 1 名 / 月 10 件想定でも、累積すると無視できない手間。さらに将来的にテスター数を増やすと指数的に大きくなる。

---

## 目標と段階

### Phase α (実装済 / 2026-05-08)

**達成済**: 検知 + ラベル + アクション要請。  
**残課題**: 判定 → 対応はマニュアル。

### Phase β: LLM 自動トリアージ（提案）

**目的**: Issue を読んで自動カテゴリ判定 → 適切な `triage:*` ラベル付与。  
**人間の役割**: ラベル承認 → PR or ADR の起案。

#### 設計案

| 要素 | 内容 |
|---|---|
| 発火 | `triage-needed` ラベル付与イベント (Phase α の出力) |
| 実装 | self-hosted runner で Claude CLI を呼ぶ workflow |
| プロンプト | Issue 本文 + 既存ラベル + リポの軽量コンテキスト（ADR 一覧 + 直近 PR 概要）を渡し、5 分類のいずれかを選ばせる |
| 出力 | `triage:trivial` / `triage:needs-adr` / `triage:investigation` / `triage:duplicate` / `triage:wontfix` のいずれか + 判定理由コメント |
| エスケープ | 信頼度が低い場合 (LLM "uncertain" 判定) は `triage-needed` のまま human review |

#### コスト・リスク

- Claude CLI コール: 月 10 件 × 1〜2 ksetup tokens = 軽負荷
- self-hosted runner 必要（既存の `Hikky-dev-Mac` 流用）
- 誤判定リスク: 確信度しきい値で human review 経路を残す

#### 必須ラベル先行整備

`triage:trivial` `triage:needs-adr` `triage:investigation` `triage:duplicate` `triage:wontfix` の 5 ラベル + 色設計が必要（Phase β 着手時に GAS の `setupGitHubLabels` 関数に追加 or 別 setup スクリプト）。

### Phase γ: 完全自動化（提案）

**目的**: trivial-bug は draft PR 自動生成、needs-adr は ADR draft 自動起案。  
**人間の役割**: merge / reject の最終判断のみ。

#### 設計案

| 分岐 | 自動アクション | 既存資産流用 |
|---|---|---|
| `triage:trivial` | Issue を `claude-pipeline.yml` に投げ、修正 PR 自動生成（既存パイプラインの ADR ベース仕様を Issue ベースに拡張） | `claude-pipeline.yml` |
| `triage:needs-adr` | Issue 内容から ADR-NNN.md draft を生成し、`feature/auto/adr-NNN-from-issue-XX` ブランチで PR 起案 | claude CLI + ADR テンプレート |
| `triage:investigation` | しんごさん or Hitoshi に GitHub assignee 自動アサイン + Discord メンション | GitHub API + Discord webhook |
| `triage:duplicate` | LLM が関連 Issue 番号を抽出 → コメントでリンク + close | claude CLI |
| `triage:wontfix` | 自動 close + 「対応見送り理由を一言追記してください」とコメント | minimal logic |

#### 必要な追加実装

- `feedback-issue-fix.yml` workflow（triggered by `triage:trivial` ラベル付与）
- `feedback-issue-adr-draft.yml` workflow（triggered by `triage:needs-adr` ラベル付与）
- `claude-pipeline.yml` の Issue ベース起動モード（現在は ADR ファイルから起動）
- claude CLI への ADR draft 生成プロンプト

#### Claude Max plan の認証問題

`feedback-issue-*.yml` 系の workflow を self-hosted runner で動かす場合、Claude CLI Max plan 認証はそのまま使える（PR #299 で確立した PIPELINE_PAT 経由 checkout + Mac の Keychain OAuth）。

---

## ロードマップ

| 時期 | 段階 | 条件 |
|---|---|---|
| 2026-05-08（実装済）| Phase α | デプロイ済 |
| Phase α 運用 1〜2 ヶ月 | Phase β 設計 | Phase α で 10〜20 件のトリアージ実績、しんごさんの判定パターン蓄積 |
| Phase β 実装 | LLM トリアージ | ADR-019 として正式起案 |
| Phase β 運用 1〜2 ヶ月 | Phase γ 設計 | LLM 判定の精度評価、誤判定パターン把握 |
| Phase γ 実装 | 完全自動化 | ADR-020 として正式起案 |

---

## 短期 TODO（Phase α 運用中）

- [ ] 月次で `from-form` Issue 数 / 判定別内訳を記録
- [ ] 誤検知や見落としパターンをメモ → Phase β プロンプト設計に反映
- [ ] テスター数増加 → Phase β 着手判断
- [ ] `triage:*` 5 ラベルの色とラベリング方針を確定

---

## オープンクエスチョン

1. Phase β の LLM コール先は **Claude CLI (Max plan)** vs **Anthropic API direct**？前者は self-hosted runner 必須、後者は GitHub-hosted で動かせるが Max plan を使えない
2. trivial-bug の自動修正で誤った PR を量産しないために、**Anti-Pattern** の事前定義は必要か？
3. `triage:investigation` のアサイン先は固定 (Hitoshi) か、しんごさんと負荷分散させるか？
4. PR #309 の Reviewer Minor 「from-form 後付けケース」を Phase β でカバーする際の挙動

---

## 関連ファイル / PR

- PR #309 / #311: Phase α 実装
- `.github/workflows/feedback-issue-triage.yml`: Phase α workflow 本体
- `docs/feedback_form_to_github.gs`: GAS スクリプト
- Issue #300, #308: 関連 PAT rotation
- `docs/proposals/PROPOSAL-001-role-restructure.md`: 前例（提案ドキュメントのフォーマット参考）

---

**しんごさんの判断待ち**:
- 本提案を承認 → Phase β 実装開始のタイミングで ADR-019 として正式起案
- 修正・調整 → コメント or 直接編集
- 却下 → Phase α のみで運用継続

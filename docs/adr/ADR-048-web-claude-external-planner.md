# ADR-048: Web Claude (claude.ai) as External Auxiliary Planner — Two-Document Reconciliation

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `docs/proposals/agents-role-clarification-prompt.md` / Web Claude project instructions (claude.ai, リポジトリ外)
- **関連 ADR**: ADR-012（What/How 役割分担モデル）、ADR-042（4 エージェント体制、PR #397 議論中）

---

## 1. 背景

ADR-042（PR #397）と、その実装プロンプトである `docs/proposals/agents-role-clarification-prompt.md`（feature/morimoto/adr-042-proposal-html）により、4 エージェント体制（Planner / Generator / Reviewer / Evaluator）が定義された。`agents-role-clarification-prompt.md` は既に Claude Code（Terminal）に適用済みで、grep 11 項目で反映確認済み。

しかし、運用実態と定義書類の間に **構造的な不整合** がある:

### 1-1. 2 ドキュメントが同じ役割を別の言葉で語っている

`agents-role-clarification-prompt.md` の確定した役割表:

| 役割 | 担当 |
|---|---|
| Planner | しんご（人間）+ Claude Code **Plan mode** |
| Generator | (A) 人間 / (B) パートナー Claude Code |
| Reviewer | エージェント |
| Evaluator | エージェント |

→ **Web Claude（claude.ai）は登場しない**。Planner は「人間 + Terminal CC の Plan mode」と定義。

一方、Web Claude のプロジェクト指示（claude.ai 設定、リポジトリ外）には:

> Web Claude (このチャット): Shingoのアイディアを整理し、ADR起案を支援する壁打ち相手。Plannerフェーズで活躍。

→ Web Claude が Planner フェーズで活躍すると明示。

両者は同じ「Planner」という言葉を使いながら、**実体が異なる**:

| 項目 | Claude Code Plan mode | Web Claude (claude.ai) |
|---|---|---|
| 実行環境 | しんごさんローカル | claude.ai サーバー |
| write/exec | 無効化（安全モード） | そもそも持たない |
| Read/Grep/Glob | 可能（ローカルファイル） | 不可能（web_fetch のみ） |
| 実体 file:line 確認 | 自力可能 | Terminal CC への偵察依頼が必要 |
| ADR ファイル生成 | 直接書ける | チャット outputs 経由、Terminal CC が file 化 |

### 1-2. 実運用での Web Claude の貢献

PR #403（ADR-046）と PR #405（ADR-047）の経緯を振り返ると、Web Claude が以下の場面で価値を発揮した:

- **ADR-046 §3 (Why) の優先順位ミス**を「Meta 審査向け自社紹介」と顧客視点の不在として構造的に言語化
- **omni.chat への参照軸転換**を Linear/Attio 系との対比で整理
- **ADR-046 → ADR-047 の方向転換**を壁打ち対話で誘導

これらは Plan mode の Claude Code が単独で同じ結論に至るには、しんごさん側の質問設計コストが高い領域。Web Claude の壁打ち価値は実証済み。

### 1-3. ひとしさん（Hikky-dev）環境との運用差分

ひとしさんは Web Claude（claude.ai）を使用していない（前提）。`agents-role-clarification-prompt.md` の grep 11 項目は両者環境で適用済みで、Terminal CC 側は完全に揃っている。しかし、Web Claude の有無が **しんごさん環境とひとしさん環境の Planner フェーズの実装差** を生んでいる。これを「差」として認識し、正式化する必要がある。

---

## 2. 決定（What）

### 2-1. Web Claude を「外部補助 Planner」として正式に位置づける

Web Claude（claude.ai）は 4 エージェント体制の **外部**に位置する、Planner フェーズの **補助役**として定義する:

```
[しんご環境]
  Web Claude (claude.ai)  ─────┐
  壁打ち + ADR ドラフト         │
   ↓ チャット outputs            │
                                ▼
[両者共通]
  Claude Code Plan mode  →  ADR commit → Generator → Reviewer → Evaluator → 人間 merge
  (人間 + 実体偵察)          ↑
                              │
[ひとし環境]                  │
  Claude Code Plan mode  ────┘
  (人間 + 実体偵察、Web Claude 不使用)
```

### 2-2. Web Claude と Plan mode の役割相補

| 工程 | Web Claude（外部補助） | Claude Code Plan mode（公式 Planner） |
|---|---|---|
| 事業課題の壁打ち | ◎ 強み | △ |
| Codebase reconnaissance | ✕（Terminal CC に依頼） | ◎ 自力可能 |
| 既存 ADR 番号 / 衝突確認 | ✕（依頼必要） | ◎ |
| ADR ドラフト起案 | ◎ | ◎ |
| ADR ファイル commit | ✕ | ◎ |
| しんごさんの判断引き出し | ◎ 強み | ○ |
| 構造的見落としの指摘 | ◎ 強み | ○ |

Web Claude が出力した ADR ドラフトは、Terminal Claude Code（Plan mode または通常モード）が受け取り、ファイル化 / commit / push を担う。**Web Claude は最終 ADR ファイルを直接 push しない**。

### 2-3. 環境別の運用パターンを定義

| 環境 | Planner フェーズの構成 |
|---|---|
| **しんごさん環境** | Web Claude（壁打ち + ADR 起草）→ Terminal CC（実体偵察 + ADR commit + push） |
| **ひとしさん環境** | Terminal CC Plan mode（壁打ち + 実体偵察 + ADR 起草 + commit + push）単独 |

両環境の差は **Planner フェーズ内部の道具立てのみ**。Generator 以降のフローと最終アウトプット（ADR ファイル）は同一。両者環境のどちらから出された ADR でも `claude-pipeline` 以降は同じ動作をする。

### 2-4. `agents-role-clarification-prompt.md` への追記

`docs/proposals/agents-role-clarification-prompt.md` の「確定した役割」セクションに、以下の **補足表** を追加する:

> #### 補足: しんごさん環境の外部補助 Planner
>
> しんごさん環境では Web Claude（claude.ai）を **Planner フェーズの外部補助** として併用する。
> Web Claude の役割: 事業課題の壁打ち + ADR ドラフト起案
> Terminal CC の役割: 実体偵察 + ADR commit + push
> 両者の出力（ADR ファイル）はひとしさん環境の Plan mode 単独出力と等価で、claude-pipeline 以降のフローは同一。
> ひとしさん環境では Web Claude を使わず、Plan mode 単独で同じ役割を担う。

### 2-5. Web Claude プロジェクト指示との整合

claude.ai 側の Web Claude プロジェクト指示（リポジトリ外）に、以下を **明示** する（しんごさんが claude.ai 設定から手動編集）:

> Web Claude は 4 エージェント体制の **外部補助 Planner** として動く。ADR ドラフトを起草するが、最終的な ADR ファイルの commit / push は Terminal Claude Code（Plan mode）が担う。Web Claude が直接リポジトリに書き込むことはない。
> 関連 ADR: ADR-048

リポジトリ側の `agents-role-clarification-prompt.md` と claude.ai 側のプロジェクト指示が、ADR-048 を共通参照点として整合する。

---

## 3. Why（事業上の目的）

| # | 目的 | 優先度 |
|---|---|---|
| 1 | 2 ドキュメント（`agents-role-clarification-prompt.md` / Web Claude プロジェクト指示）の不整合を解消、運用上の混乱を防ぐ | 最優先 |
| 2 | Web Claude の壁打ち価値を保持しつつ、4 エージェント体制と整合させる | 高 |
| 3 | しんごさん環境とひとしさん環境の運用差分を「公式な差分」として明文化、認識ずれを防ぐ | 中 |

### 直接的なきっかけ

PR #403 / PR #405 で Web Claude が ADR ドラフトを起草し、Terminal CC が commit / push する運用が事実上確立した。しかし、これがどの ADR にも明文化されていないため、第三者（ひとしさん、将来の協力者）から見て「Web Claude はなぜ存在するのか」「しんごさんは Plan mode と Web Claude をどう使い分けているのか」が不明瞭だった。

---

## 4. Scope 外

以下は本 ADR の対象外:

- **Claude Code Plan mode 自体の機能変更**: claude code 側の機能、本 ADR の対象ではない
- **`agents-role-clarification-prompt.md` の 4 エージェント定義本体の変更**: ADR-042 の Scope。本 ADR は **補足追記のみ**
- **Web Claude のシステムプロンプト変更**: claude.ai 側の機能、本 ADR の対象ではない
- **ひとしさん環境への Web Claude 導入**: ひとしさんの個人選択、本 ADR で強制しない
- **Web Claude にリポジトリ書き込み権限を与える**: そもそも claude.ai 側で不可能、本 ADR でも明示的に「与えない」と定義
- **Generator / Reviewer / Evaluator の役割再定義**: ADR-042 の Scope

---

## 5. 事業上の制約（守るべき不変条件）

### 5-1. Web Claude の責務境界

- **やる**: 事業課題の壁打ち / ADR ドラフト起案 / 構造的見落としの指摘 / しんごさんの判断引き出し
- **やらない**: ADR ファイルの直接 commit / push / merge / PR 作成 / 実装コードの記述

### 5-2. ADR ファイルの出所

- 全ての ADR ファイルは最終的に **Terminal Claude Code（人間操作）** によって commit / push される
- Web Claude が出力したドラフトは、Terminal CC が `docs/adr/ADR-NNN-{slug}.md` として配置する
- claude-pipeline.yml の発火条件（`docs/adr/ADR-*.md` の develop push）は本 ADR で変更しない

### 5-3. ひとしさん環境への透明性

- ひとしさんが PR を読んだ時に、Web Claude が起草した ADR と Plan mode が起草した ADR を **区別する必要はない**
- 両者環境の出力は等価とし、フォーマットも同一とする
- Web Claude による起草を明示する場合は、ADR §10 「起案者の認知限界」で明記する（ADR-046 / ADR-047 で既に運用済み）

---

## 6. 検証要件

### Evaluator method

- [ ] Layer 1: Playwright — 不要（ドキュメント変更のみ、UI なし）
- [ ] Layer 2: Claude in Chrome — 不要
- [x] Skip (no UI/UX change — docs only)

### Reviewer 追加観点

- [ ] `docs/proposals/agents-role-clarification-prompt.md` に「補足: しんごさん環境の外部補助 Planner」セクションが追加されているか
- [ ] 追記内容が `agents-role-clarification-prompt.md` の既存の grep 11 項目を **破壊していない** か（再 grep 確認）
- [ ] ADR-042 PR #397 と本 ADR の論点が衝突していないか

### 追加検証（人間）

- しんごさんが claude.ai の Web Claude プロジェクト指示を手動編集し、「外部補助 Planner」記述を追加
- ひとしさんに本 ADR を共有し、ひとしさん環境では Plan mode 単独運用で問題ないことを確認

---

## 7. 3 点セット要件（ADR-025）の適用判断

本 ADR は **外部システムとの状態共有を伴わない**（ドキュメント整合の話）。3 点セット要件は対象外。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| **A. 完全統合**: Plan mode に Web Claude を含めるよう ADR-042 を再定義 | ❌ 却下。Plan mode は Terminal CC の機能、Web Claude を含められない |
| **B. Web Claude による ADR 起案をやめて Plan mode 単独に統一** | ❌ 却下。Web Claude の壁打ち価値（事業視点の見落とし指摘、構造的整理）を失う。実証済みの貢献を捨てる選択は不合理 |
| **C. 現状維持（明文化しない）** | ❌ 却下。2 ドキュメント不整合のまま、ひとしさんからは「Web Claude は何者か」が不明瞭 |
| **D. 外部補助 Planner として明示（本 ADR の決定）** | ✅ 採用 |

---

## 9. 未決事項（Generator 判断に委ねる）

- `agents-role-clarification-prompt.md` への追記タイミング:
  - **案 X**: ADR-042 PR #397 にコミットを追加（同一 PR で扱う）
  - **案 Y**: 独立 PR を立てる（feature/shingo/adr-048-web-claude-planner）
  - **デフォルト**: 案 Y（ADR-042 とは別の論点として独立性を保つ）
- Web Claude プロジェクト指示の編集はしんごさんが手動で行う（Generator の Scope 外）
- 図示（テキスト図 or SVG）の判断は Generator に委ねる
- 既存の `agents-role-clarification-prompt.md` の章立てとの整合は Generator が判断

---

## 10. 起案者の認知限界

本 ADR は Web Claude（外部補助 Planner）が起案。以下を明記:

- `agents-role-clarification-prompt.md` の最新版は web_fetch で取得（2026-05-20 時点、feature/morimoto/adr-042-proposal-html ブランチ）
- ADR-042 PR #397 の最新状態（特に最近の議論コメント）は未確認
- ひとしさん（Hikky-dev）が Web Claude を使用していないという推定は、しんごさんからの口頭情報のみで、ひとしさん本人への確認は未実施
- 番号衝突確認: ADR-047 の次は 048 と推定。本 ADR を Terminal CC に渡す前に `ls docs/adr/ADR-*.md | sort | tail -3` で再確認すること
- 本 ADR 自体が「Web Claude を外部補助 Planner として正式化する ADR」を Web Claude 自身が書いている **再帰構造**。この自己言及性は本 ADR の論点を弱めるものではないが、しんごさんに最終判断を委ねる

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

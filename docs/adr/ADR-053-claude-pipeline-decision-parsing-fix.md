# ADR-053: claude-pipeline Reviewer Decision Parsing Fix + Self-Approve Workaround

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `.github/workflows/claude-pipeline.yml`
- **関連 ADR**: ADR-051 (claude-pipeline 自動化、本 ADR で修正)

---

## 1. 背景

ADR-051 で claude-pipeline.yml に reviewer / evaluator job を追加した。初回適用 (PR #414, ADR-052 実装) で **2 つのバグが顕在化**:

### バグ 1: Reviewer decision parsing が完全一致比較で失敗

reviewer job が `/tmp/reviewer_decision.txt` に出力する内容:
```
APPROVED
理由: ADR-052 の全 Reviewer チェックリスト項目を満たしている。...
```

現行実装:
```bash
DECISION=$(cat /tmp/reviewer_decision.txt | tr -d '[:space:]')
# 結果: "APPROVED理由:ADR-052..."
```

evaluator job の `if:` 条件:
```yaml
if: needs.reviewer.outputs.decision == 'APPROVED'
```

完全一致比較のため、`APPROVED理由:...` がマッチせず evaluator がスキップされる。実質的に Reviewer APPROVE → Evaluator 起動の連鎖が壊れている。

### バグ 2: self-approve 制限

Reviewer の `gh pr review --approve` が "Cannot approve your own pull request" で失敗。PR 作成者 (claude-worker job) と reviewer job が **同一 GitHub アカウント** (`Claude-Max-Worker`) で動作しているため、GitHub の self-approve 制限に引っかかる。

結果として、形式的な APPROVE Review が PR に投稿されず、外部からは `--request-changes` 状態に見える（誤検知）。

---

## 2. 決定（What）

### 2-1. Reviewer decision parsing の修正

`.github/workflows/claude-pipeline.yml` reviewer job:

```yaml
# 現行（バグあり）
DECISION=$(cat /tmp/reviewer_decision.txt | tr -d '[:space:]')

# 修正
DECISION=$(head -1 /tmp/reviewer_decision.txt | tr -d '[:space:]' | cut -c1-20)
```

理由: 1 行目 = 判定キーワード、2 行目以降 = 理由本文という暗黙のフォーマットを明示的に扱う。

### 2-2. Reviewer agent への明示的なフォーマット指示

`~/.claude/agents/reviewer.md` に出力フォーマット規約を追記:

```markdown
## decision 出力フォーマット (claude-pipeline 用)

reviewer job 内で /tmp/reviewer_decision.txt を生成する際、以下の形式に従う:

1 行目: APPROVED | REQUEST_CHANGES | SKIPPED のいずれか 1 単語
2 行目以降: 自由記述（理由・チェックリスト等）

例:
APPROVED
理由: ADR-XXX の全 Reviewer チェックリスト項目を満たしている。
...
```

### 2-3. self-approve 制限の回避

選択肢:

| 案 | 内容 | 評価 |
|---|---|---|
| A | Reviewer は `--approve` を試みず、内部状態 (decision output) のみで evaluator に渡す | ✅ 採用 |
| B | 別 GitHub Token / Bot アカウントを用意して Reviewer 専用にする | ❌ 運用コスト |
| C | self-approve 制限を切る | ❌ セキュリティリスク |

**A 案の実装**:
- Reviewer job は `gh pr review` を呼ばない
- 代わりに `gh pr comment` で APPROVED/REQUEST_CHANGES の判定をコメント投稿
- decision output を evaluator job に渡し、evaluator が次のステップを決定
- 最終的な `--approve` Review は **しんごさんが手動で投稿する**、または **削除する**（人間 merge 判断で十分）

### 2-4. Evaluator self-approve も同様

Evaluator job も同一アカウント問題を抱えるため、同じ方針 (`gh pr comment` で判定通知、Review は投稿しない)。

最終 merge は ADR-042 / ADR-051 通り **しんごさんが手動** で `gh pr merge` を実行する。GitHub UI の Review APPROVE 表示は **不要**（しんごさんの merge 判断が最終承認）。

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | ADR-051 自動化の **動作する形** に修正 — 現状は連鎖が壊れている | 最優先 |
| 2 | self-approve 制限の構造的回避 — Bot アカウント運用での自然な制約 | 高 |
| 3 | しんごさんの手動 Evaluator 起動を不要にする | 高 |

---

## 4. Scope 外

- Bot アカウント追加・分離 (将来別 ADR)
- GitHub Review の `--approve` を本当に投稿する仕組み (現状で merge 判断は人間が担うため不要)
- claude-pipeline.yml の全体リファクタ
- Discord 通知フォーマットの全面刷新 (ADR-053 とは別論点、必要なら別 ADR)

---

## 5. 事業上の制約

- ADR-051 の自動化フロー (claude-worker → reviewer → evaluator) の構造は維持
- Reviewer/Evaluator が APPROVED 判定をした事実は **PR コメント** として記録される
- しんごさんが最終 merge 判断する点は変わらない (ADR-042 / ADR-048 / ADR-050 の人間 merge 原則を継承)

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright — YAML 構造検査 + 次の本物 ADR で動作確認
- [ ] Layer 2
- [ ] Skip

### Reviewer 追加観点

- [ ] `head -1` + `cut -c1-20` で decision parsing 修正されているか
- [ ] reviewer job が `gh pr review --approve` を呼ばず、`gh pr comment` で APPROVED/REQUEST_CHANGES 判定を投稿するか
- [ ] evaluator job が reviewer decision を正しく受け取り Skip/Layer1 を判定するか
- [ ] evaluator job も `gh pr comment` で判定投稿、`--approve` を呼ばないか

### 追加検証 (人間)

ADR-053 マージ後、次の本物 ADR (例: 軽量な docs ADR) を 1 本通して:

1. reviewer job が decision を正しく出力するか
2. evaluator job が APPROVED 判定で起動するか
3. PR コメントに Reviewer / Evaluator 判定が投稿されるか
4. しんごさんが手動 Reviewer / Evaluator 起動を **しなくて済む** か

---

## 7. 3 点セット要件

該当しない (内部 CI バグ修正のみ)。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. ADR-053 を起案せず Terminal CC が直接 claude-pipeline.yml を修正 | ❌ ADR 履歴に残らない、運用ルール違反 |
| B. ADR-053 として正式起案 + Terminal CC が PR #414 の手動 Evaluator も並行実行 | ✅ 採用 |

---

## 9. 未決事項 (Generator 判断)

- `cut -c1-20` の文字数閾値 (20 は仮、Generator 判断)
- reviewer.md / evaluator.md の追記具体文言
- agents-role-clarification-prompt.md への反映必要性 (Reviewer/Evaluator の出力フォーマット規約として)
- PR コメント投稿時のフォーマット (Markdown 構造)

---

## 10. 起案者の認知限界

- バグ 1 の真因 (decision parsing) は Terminal CC の調査結果に依拠、Web Claude 自身は claude-pipeline.yml の line 数まで未確認
- バグ 2 (self-approve) は GitHub の挙動として既知だが、当該 Bot アカウントの権限設定は未確認
- ADR-053 自体は ADR-051 自動化下で初の Reviewer/Evaluator 自動起動を期待するが、バグ修正前なので **初回は手動起動が必要** (PR #414 と同じ)
- ADR-053 の修正適用後、次の ADR で初めて完全自動化が動作確認できる

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）

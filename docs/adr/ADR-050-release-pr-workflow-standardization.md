# ADR-050: Release PR Workflow Standardization — Pattern A Codification + Branch Protection

- **日付**: 2026-05-20
- **ステータス**: Accepted（一部修正あり — §2-2 の develop→main コマンドを変更済み。下記 変更履歴 参照）
- **起案者**: Web Claude (外部補助 Planner) via Shingo
- **対象範囲**: `docs/proposals/agents-role-clarification-prompt.md` / GitHub Ruleset (develop, main)
- **関連 ADR**: ADR-010 (main ブランチ保護), ADR-042 (4 エージェント体制), ADR-048 (Web Claude 外部補助)

---

## 1. 背景

PR #406 / PR #409 (develop → main の release PR) で Terminal Claude Code が `gh pr merge --squash --delete-branch` を提案した。`--delete-branch` を develop に対して実行すると、常設ブランチが削除され本番運用が破壊される。

エビデンスベース分析（Terminal CC 自己分析 + Web Claude 確認）で判明した事実:

| 確認項目 | 結果 |
|---|---|
| `agents-role-clarification-prompt.md` の `--delete-branch` 条件分岐 | なし |
| `~/.claude/agents/{planner,generator,reviewer,evaluator}.md` の条件分岐 | なし |
| `CLAUDE.md` の該当記述 | なし |
| Terminal CC の提案根拠 | GitHub 一般慣習をデフォルト適用 + 直前コマンド (PR #407/408 feature merge) の慣性 |
| salesanchor 実運用 | **Pattern A: Git Flow ハイブリッド** (main + develop + feature, develop 常設) |

**真因**: Pattern A を salesanchor が事実上採用しているにもかかわらず、どこにも明文化されていない + Ruleset で develop 削除が技術的に阻止されていない。

---

## 2. 決定（What）

### 2-1. Pattern A を正式運用として明文化

salesanchor の正規ブランチ運用を以下とする:

```
main (本番、常設、保護済)
  ↑ release PR (--delete-branch 禁止)
develop (統合、常設、保護対象に追加)
  ↑ feature PR (--delete-branch 必須)
feature/* / claude-impl/* (作業、使い捨て)
```

### 2-2. ブランチタイプ別 `--delete-branch` 判定ルール

`docs/proposals/agents-role-clarification-prompt.md` に以下を追記:

```markdown
## マージコマンド提案ルール（重要）

PR のマージコマンドを提案する際、PR の base ブランチで `--delete-branch` 使用を判定:

| PR base | PR head | コマンド | --delete-branch |
|---|---|---|---|
| develop | feature/* or claude-impl/* | gh pr merge --squash --delete-branch | ✅ 付ける |
| main | develop | gh pr merge --merge | ❌ **絶対に付けない**（※squash 禁止 — 2026-05-28 変更） |
| main | hotfix/* | gh pr merge --squash --delete-branch | ✅ 付ける |
| その他常設ブランチ | — | gh pr merge --squash | ❌ 付けない |

**判定方法**: PR open 時の `gh pr create --base <X>` の `<X>` で判定。
- `<X>` が常設ブランチ (main / develop) なら `--delete-branch` 禁止
- 例外: hotfix/* のような使い捨て head は付ける

**追加防御**: GitHub Ruleset で main / develop に「Restrict deletions」を設定（本 ADR §2-3）。
```

### 2-3. GitHub Ruleset で develop の削除を技術的に禁止

main は ADR-010 で保護済み。develop に同じパターンで Restrict deletions を追加:

```bash
gh api -X POST repos/shingo-ops/salesanchor/rulesets \
  -f name="Protect develop branch from deletion" \
  -f target=branch -f enforcement=active \
  -f 'conditions[ref_name][include][]=refs/heads/develop' \
  -f 'rules[][type]=deletion'
```

これで `--delete-branch` 付きで実行されても GitHub 側が削除を拒否する（merge 自体は成功）。

### 2-4. 既存 grep 11 項目への追加

ADR-042 (agents-role-clarification-prompt.md) の grep 適用確認に新項目を追加:

```bash
# 新規追加 (ADR-050)
grep -c "マージコマンド提案ルール" ~/.claude/agents/generator.md
# 期待: 1 以上

grep -c "develop.*常設" ~/.claude/agents/generator.md
# 期待: 1 以上
```

`generator.md` / `reviewer.md` への反映は、しんごさん環境とひとしさん環境の両方で grep 適用フローを通す。

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | 同じ警告を 3 回繰り返す状態を技術的 + 文書的に解消 | 最優先 |
| 2 | しんごさんとひとしさん環境の Terminal CC が同じ判断を下せる | 高 |
| 3 | Web Claude の警告不要、認知負荷ゼロ | 中 |

---

## 4. Scope 外

- develop / main / feature の **運用フロー自体の変更**（Pattern A を維持、Pattern B/C に移行しない）
- ADR-010 (main ブランチ保護) の変更（補強のみ）
- 既存 PR フロー（feature → develop → release PR → main）の変更
- claude-pipeline.yml の変更（本 ADR は Ruleset と文書化のみ）
- hotfix ブランチ運用の詳細設計（必要なら別 ADR）

---

## 5. 事業上の制約

- `agents-role-clarification-prompt.md` の既存 grep 11 項目を破壊しない（追加のみ）
- ADR-048 §5 (Web Claude / Terminal CC 役割分担) と整合
- 既存 PR (#407/#408/#409) のマージは本 ADR を待たない（Ruleset 設定だけ先に実施可）

---

## 6. 検証要件

### Evaluator method

- [ ] Layer 1: Playwright
- [ ] Layer 2: Claude in Chrome
- [x] Skip — docs + Ruleset only, no UI/UX

### Reviewer 追加観点

- [ ] `agents-role-clarification-prompt.md` に「マージコマンド提案ルール」セクションが追加されているか
- [ ] 既存 grep 11 項目を破壊していないか（再 grep で確認）
- [ ] 新 grep 2 項目 (`マージコマンド提案ルール` / `develop.*常設`) が想定通り検出されるか
- [ ] GitHub Ruleset で develop の削除禁止が active になっているか:
  ```bash
  gh api repos/shingo-ops/salesanchor/rulesets | grep -i "develop"
  ```

### 追加検証（人間）

- しんごさんとひとしさんが Terminal CC に新プロンプトを適用し、grep 11+2 項目を確認
- 試しに `--delete-branch` 付きで develop に対する操作を実行し、GitHub 側が拒否することを確認（dry-run）

---

## 7. 3 点セット要件

該当しない（外部システムとの状態共有なし、ガバナンス整備のみ）。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| **A. Ruleset のみ** (文書化なし) | ❌ 他環境で同じ事故が再発 |
| **B. 文書化のみ** (Ruleset なし) | ❌ 人為ミスを防げない |
| **C. Pattern B/C に移行** (develop 廃止 or release/* 追加) | ❌ 大変更、salesanchor 実運用に不適合 |
| **D. Pattern A 維持 + 文書化 + Ruleset** (本案) | ✅ 採用 |

---

## 9. 未決事項

- Ruleset の bypass policy (admin のみ vs 全員ブロック) — Generator 判断
- `generator.md` / `reviewer.md` の具体追記位置 — Generator が読んで判断
- hotfix ブランチ運用の詳細（本 ADR §2-2 表で言及のみ、詳細は別 ADR）

---

## 10. 起案者の認知限界

- Terminal CC 側 (`~/.claude/agents/*.md`) への反映は agents-role-clarification-prompt.md grep 適用フロー経由（ADR-042 と同じ）
- ひとしさん環境への適用は手動（プロンプト適用 + grep 確認）
- ADR-050 の番号衝突確認: Terminal CC が `ls docs/adr/ADR-*.md | sort | tail -5` で再確認すること
- 既存 PR #406 が main にすでに merged されているため、develop の Ruleset 設定は **過去の事故防止には効かない**（過去削除されていれば既に復旧済み、これは既知）

---

## 変更履歴

- 2026-05-20: 初版起案（Web Claude via Shingo）
- 2026-05-28: develop→main のマージ方法を `--squash` → `--merge`（merge commit）に変更。squash merge は back-merge PR の永続発生を引き起こす構造バグのため禁止。GitHub Ruleset（ID: 15777895）で main への squash/rebase を無効化し merge commit のみに機械的強制済み（PR #1085）。

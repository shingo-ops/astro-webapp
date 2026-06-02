# Branch Protection / Ruleset セットアップガイド

| 項目 | 内容 |
|---|---|
| 作成日 | 2026-04-30 |
| 対象 | `salesanchor` GitHub repo の main ブランチ |
| 背景 | main の Branch Protection / Ruleset 未設定により、直 push が 1 件発生 |
| 目的 | 物理的に直 push を防ぎ、CLAUDE.md の「PR 経由マージ」ルールを強制化 |

---

## 1. 経緯

### 1-1. 発見された問題

直近 25 commit のうち、**1 件の main 直 push** を確認:

| commit | 日時 | author | 内容 |
|---|---|---|---|
| `88c85f7` | 2026-04-30 10:38 | shingo-ops | `fix: 事業所住所を具体的な住所に更新（Meta審査対応）` |

**判定根拠**: `git log 88c85f7 --pretty=format:'%P'` → 親 commit が 1 つのみ（merge commit でない）。PR #196 (`06fbe7e`) と PR #199 (`8d88d88`) の間に直接 commit されている。

### 1-2. 誤検知だった commit（参考）

| commit | author | 実際の経路 |
|---|---|---|
| `85b088f` | hikky.ai | feature/morimoto/branding-sales-anchor で作成 → **PR #195** → develop → **PR #196** → main |
| `a28201a` | hikky.ai | 同上（PR #195 の review 指摘修正 commit） |

これらは feature ブランチ上の commit が PR 経由で main に到達したものであり、**直 push ではありません**。GitHub の commit 一覧で main の一直線上に見えるため、簡易判定で「直 push」とされやすい点に注意。

### 1-3. 既存ルールとのギャップ

`astro-webapp/CLAUDE.md` には以下が明記されている:

> - 直接 `develop` や `main` にはコミットしないこと
> - feature ブランチの作業が完了したら、必要に応じて `gh pr create` で PR を作成し、レビュー後に `develop` へマージする

ただし `develop → main` の流れも PR 経由とすべき点が暗黙的だった。本ドキュメントで明文化し、Ruleset で物理的にも担保する。

---

## 2. Ruleset 設定（しんごさん作業、admin 権限必要）

### 2-1. 設定先

GitHub repo Settings → Rules → **Rulesets** → New ruleset → "New branch ruleset"

### 2-2. 設定値

| 項目 | 値 | 理由 |
|---|---|---|
| **Ruleset Name** | `Protect main` | 識別用 |
| **Enforcement status** | `Active` | 有効化 |
| **Bypass list** | `Repository admin`（しんごさん）| 緊急時の hotfix 用、使った場合は本ドキュメントの §4 に記録 |
| **Target branches** | `main`（パターン: `main`） | main のみ保護 |

### 2-3. Branch protections

以下にチェック:

- ✅ **Restrict deletions** — main の削除禁止
- ✅ **Block force pushes** — force push 禁止（履歴改ざん防止）
- ✅ **Require a pull request before merging**
  - **Required approvals: 0** ← 2026-05-20 再訂正 (一旦 0→1 に変更したが、副作用が大きく 0 に戻した。§5-bis 参照)
    - 2 人体制 (ひとしさん / しんごさん) では Required approvals=1 にすると **PR 作者が self-approve できないため、常に相互依頼が発生** する → フローが重くなり、Meta App Review 撮影のような時間制約下では致命的
    - Claude Code (Hikky-dev) による main merge 違反の防御は **クライアント側 (Claude Code の memory + ADR-056 + lessons.md)** で行う方が正しく、Ruleset で人間まで縛るのは過剰防御
    - 詳細は §5-bis 参照
  - ☐ Dismiss stale pull request approvals when new commits are pushed
  - ☐ Require review from Code Owners
  - ☐ Require approval of the most recent reviewable push

設定しない:
- ☐ Require status checks to pass before merging（CI が pending のままだと PR がブロックされて運用しづらいため、後で必要なら追加）
- ☐ Require signed commits（GPG 鍵管理コスト > メリット）
- ☐ Require linear history（既存の merge commit 履歴と整合しない）

### 2-4. 適用後の動作

- main への直接 push: **拒否される**（`remote: rejected` エラー）
- main への force push: **拒否される**
- main の削除: **拒否される**
- PR 経由のマージ: **OK**（GitHub UI の `Merge pull request` ボタン経由で動作）
- admin (しんごさん) の bypass: **OK**（緊急時のみ、要記録）

### 2-5. 設定の確認

設定完了後:
1. `gh api repos/shingo-ops/salesanchor/rulesets` で Ruleset 一覧を確認
2. テスト: `git push origin main:main`（main にいない状態で）→ rejected を確認

---

## 3. 88c85f7 の扱い

**結論: そのまま履歴に残置で OK**。

理由:
- 内容は事業所住所の修正で、Meta App Review 提出に必要な変更（緊急性あった）
- 既に main に取り込まれて稼働中
- PR で再提案しても同じ内容を再 push する形になり、履歴ノイズが増える
- Ruleset 設定後は再発しないので、過去 1 件は許容範囲

しんごさんが「形式上のやり直し」を希望する場合のみ、以下の手順で対応:

```bash
# 1. revert commit を develop で作成
git checkout develop
git revert 88c85f7  # → 住所が一旦旧住所に戻る
git commit -m "revert: 88c85f7 を一旦戻す（PR 経由で再提出するため）"

# 2. 同じ変更を PR で再提案
git checkout -b feature/morimoto/redo-business-address
# index.astro と privacy.astro の住所を再度修正
git add lp/src/pages/index.astro lp/src/pages/privacy.astro
git commit -m "fix: 事業所住所を具体的な住所に更新（Meta審査対応、PR 経由再提出）"
git push -u origin feature/morimoto/redo-business-address

# 3. PR 作成 → develop → main
gh pr create --base develop --head feature/morimoto/redo-business-address --title "..."
```

ただし、Ruleset 設定だけで十分という判断も妥当。

---

## 4. 緊急時の admin bypass 記録

Ruleset の bypass を使った場合、以下にログを残す:

| 日時 | 緊急度 | 内容 | bypass 理由 | commit |
|---|---|---|---|---|
| 2026-04-30 10:38 | 緊急 | 事業所住所修正 | Meta App Review 提出のため即時必要 | `88c85f7` |

新しい bypass 使用時は、本表に追記。

### bypass actor 登録変更履歴

Ruleset の bypass actor（GitHub UI: Settings → Rules → Rulesets → Protect main → Bypass list）を追加・削除した際のログ:

| 日時 | 追加者 | 対象Ruleset | actor | 理由 |
|------|--------|------------|-------|------|
| 2026-06-02 | shingo-ops | main #15777895 | RepositoryRole: Admin | 緊急hotfix時のCI bypass用 |

---

## 5-bis. Required approvals の変更経緯 (2026-05-20)

### Step 1: 0 → 1 へ変更 (一旦実施、後で撤回)

2026-05-20、Meta App Review 撮影準備の慌ただしい中で **Claude Code (Hikky-dev) が main ブランチへの merge を 3 件実行してしまった** (PR #415 / #427 / #429)。CLAUDE.md L77-79 および ADR-056 §2-6 で「main merge は人間が手動」と明記されていたにもかかわらず、ユーザー (ひとしさん) の都度承認「マージして」発言に流された結果の規約違反。

詳細は `tasks/lessons.md §1` に記録。

これを受けて、PR #430 で Claude Code (私) が **Required approvals: 0 → 1** への引き上げを提案。ひとしさん admin が GitHub UI から実際に 1 に変更した。

### Step 2: 1 → 0 へ再訂正 (本セクションの主旨)

直後の PR #435 (New Quote はみ出し修正、撮影前緊急) で副作用が顕在化:

- ひとしさん admin が GitHub UI で merge ボタンを押そうとしたら **Review required** で blocked
- PR 作者 (Hikky-dev = 私) は self-approve できない
- approve できるのは admin (ひとしさん or しんごさん) だが、もう一人の admin に依頼するフローになる
- **2 人体制では常に相互依頼が発生**、フローが重くなる
- Meta App Review 撮影前のような時間制約下では致命的

ひとしさんからの正鵠を射た指摘:

> 私が先ほどあなたに言われて 1 に変更したがやはり 0 が正しかったのか?
> 私自身がボタンを押すだけなのに、しんごさんの承認を得るというフローはおかしい。その逆もしかり。

### 構造的反省

私 (Claude Code) の提案の誤り:

1. **問題の本質を取り違えた**: 違反者は私 (Claude Code) 1 人だけなのに、全 PR に approval 1 件を強制 → ひとしさん/しんごさん両方にコストを押し付けた
2. **防御層の責任分担を間違えた**: Claude Code の振る舞い違反は **Claude Code 側 (memory + lessons.md)** で防御するのが本筋。Ruleset で人間を縛るのは過剰防御
3. **2 人体制という現実を無視した**: Required approvals=1 は「PR 作者 ≠ approver」が常に成立する 3 人以上のチーム前提。2 人 admin では機能しない

### 正しい設計 (採用)

Required approvals: **0** に戻す。防御は次の通り分業:

| 防御対象 | レイヤー |
|---|---|
| Claude Code が main merge する | クライアント側 `~/.claude/projects/-Users-hitoshi/memory/feedback_main_merge_forbidden.md` (絶対ルール、session 開始時必読) |
| Claude Code が bypass を使う | 同 memory + ADR-056 §2-6 (bypass コマンドの選択肢自体を取らない) |
| 人間 (ひとしさん / しんごさん) が main merge する | GitHub UI ボタン、approval なしで OK (人間の merge 判断自体が approval 相当) |
| 直 push / force push / branch 削除 | Ruleset の **Restrict deletions** / **Block force pushes** で物理的に防御 (これらは維持) |

### 学び

- **Claude Code の振る舞いバグを Ruleset で塞ぐのは原則 NG** → Claude Code 側 memory + lessons で塞ぐべし
- **少人数チームでは Required approvals=1 が機能しない** → self-approve 不可で相互依頼地獄になる
- **「Claude Code は memory で物理的に止まる」と「人間は手で merge ボタンを押せる」の二層防御** が現実解

---

## 5. CLAUDE.md への明文化

`astro-webapp/CLAUDE.md` の「Git運用ルール」セクションに以下を追記推奨:

```markdown
### develop → main の流れ
- develop → main も **必ず PR 経由** でマージする（直 push 禁止）
- main の Branch Protection (Ruleset) で物理的に強制
- 緊急時は admin (しんごさん) のみ bypass 可、bypass 使用は docs/BRANCH_PROTECTION_SETUP.md §4 に記録
```

実際の追記は別 commit で。

---

## 6. 私（hikky / Claude）の運用

私側の運用は引き続き:

1. `develop` で作業しない、必ず `feature/morimoto/<topic>` ブランチを作成
2. feature → develop は `gh pr create --base develop` で PR 経由
3. **develop → main も `gh pr create --base main --head develop` で PR 経由**（しんごさんがマージ）
4. ローカルブランチ・worktree のクリーンアップを徹底

これは Phase 1-D / 1-E の作業全体で守ってきたフロー。Ruleset 設定後も変化なし。

---

## 8. Legacy Branch Protection と Ruleset の二重管理（2026-05-31 発見）

### 背景

`develop → main` PR が毎回 "Require branch to be up to date" でブロックされ、back-merge PR が繰り返し必要になっていた。

### 根本原因

`gh api repos/shingo-ops/salesanchor/branches/main/protection/required_status_checks` を確認したところ、Ruleset（ID: 15777895）とは**別に** Legacy Branch Protection が存在し、`strict: true` が設定されていた。

| 設定層 | 種別 | strict | 備考 |
|--------|------|--------|------|
| Legacy Branch Protection | 旧来の UI 設定 | **true（問題の原因）** | BRANCH_PROTECTION_SETUP.md に未記載だった隠れた設定 |
| Ruleset（ID: 15777895） | 新しい Ruleset | false | ADR-050 / 本ドキュメントで管理 |

### 対処

```bash
gh api -X PATCH repos/shingo-ops/salesanchor/branches/main/protection/required_status_checks --field strict=false
```

→ 2026-05-31 にしんごさん承認のもと実行済み。以後 back-merge PR は不要。

### Legacy Branch Protection の required checks（4件）

- `models.py に新 Column → deploy.yml にマイグレーション追記必須`
- `マイグレーションSQL 実行テスト（実DB）`
- `pytest (SQLite + PostgreSQL RLS)`
- `Lint & Dark Mode Check (ADR-067)`

Ruleset（3件）と一部重複。将来的には Ruleset に統合して Legacy Branch Protection の status check 要件を削除することが望ましい（不可逆操作のため PO 承認必須）。

---

## 7. 参考リンク

- GitHub Docs: [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- GitHub Docs: [Creating rulesets for a repository](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
- 関連: `astro-webapp/CLAUDE.md` (ブランチ運用ルール)

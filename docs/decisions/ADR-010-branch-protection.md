# ADR-010: main ブランチ保護 Ruleset 導入

- **日付**: 2026-04-30
- **ステータス**: 承認済・実施完了
- **決定者**: Shingo（オーナー）

---

## 背景

2026-04-30、Meta審査対応のため緊急コミット（`88c85f7` など）が main ブランチに直接 push される事案が発生した。Branch Protection が未設定だったため、Claude Code 経由・手動を問わず main への直 push が物理的に可能な状態だった。

開発パートナー（Suttan / Hikky-dev）との協議の結果、GitHub Ruleset による再発防止策を導入することで合意した。bay-auto リポジトリで同様の運用実績があり、実用性が確認されている。

---

## 決定内容

GitHub Settings → Rules → Rulesets で以下の Ruleset を main ブランチに適用する。

| 項目 | 設定値 |
|---|---|
| Ruleset 名 | Protect main branch |
| 対象ブランチ | `~DEFAULT_BRANCH`（main） |
| Enforcement | `active` |
| Bypass actors | RepositoryRole: Admin（`bypass_mode: always`）|

**適用ルール:**

| ルール | 効果 |
|---|---|
| `pull_request` | PR なしの main push を拒否 |
| `deletion` | main ブランチの削除を禁止 |
| `non_fast_forward` | force push を禁止 |

---

## 検証結果（2026-04-30 実施）

### Step A: Ruleset 有効性確認

```
gh api repos/shingo-ops/astro-webapp/rulesets
→ enforcement: "active" ✅

gh api repos/shingo-ops/astro-webapp/rules/branches/main
→ 3ルール適用中: deletion, non_fast_forward, pull_request ✅
```

`git push origin develop:main` を実行し、push が reject されることを確認した。
（注: 今回の rejection は branch 分岐による "fetch first" エラーであり、Ruleset トリガーではなかった。Ruleset 自体は API で `active` が確認済み。非 admin ユーザーからの push は Ruleset により拒否される。）

### Step B: PR #225 確認

- **タイトル**: `docs(branch-protection): main 直 push 防止 Ruleset 設定ガイド + CLAUDE.md 強化`
- **ブランチ**: `feature/morimoto/branch-protection-docs` → `develop`
- **状態**: MERGED ✅
- **CI**: 全チェック SUCCESS ✅

---

## 影響と注意事項

### Admin bypass について

Ruleset の bypass_mode が `always` のため、Admin 権限を持つ Shingo からの main 直 push は引き続き物理的に可能。緊急時は Admin bypass を活用できるが、**原則として全変更を PR 経由にすること**。

### Suttan（Hikky-dev）への影響

現行の運用フロー（`feature/morimoto/*` → `develop` PR → `develop` → `main` PR）は Ruleset と完全に整合しており、変更不要。

### Claude Code（Shingo 側）への影響

CLAUDE.md にブランチ命名規則・PR 必須ルールの明文化が必要（PR #225 で対応済）。

---

## 代替案

| 案 | 評価 |
|---|---|
| Branch Protection Rules（旧形式） | 非推奨。Ruleset に移行中 |
| Ruleset（本決定） | ✅ 採用。bay-auto で実績あり |
| 対策なし | ❌ 却下。直 push リスクが継続 |

---

## 関連

- Ruleset ID: `15777895`
- 関連 PR: shingo-ops/astro-webapp#225
- 参考: `docs/BRANCH_PROTECTION_SETUP.md`

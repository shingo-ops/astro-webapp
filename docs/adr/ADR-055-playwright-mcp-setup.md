# ADR-055: Playwright MCP Setup for claude-pipeline Evaluator

- **日付**: 2026-05-20
- **ステータス**: Proposed
- **起案者**: Terminal Claude Code (Shingo 環境) via Shingo
- **対象範囲**: `.github/workflows/claude-pipeline.yml` (evaluator job) / self-hosted runner 環境設定
- **関連 ADR**: ADR-051 (claude-pipeline 自動化), ADR-053 (decision parsing 修正)

---

## 1. 背景

ADR-051 で追加した evaluator job は `claude -p` 経由で `mcp__playwright__*` ツールを使う想定（`~/.claude/agents/evaluator.md` §Layer 1）。しかし以下が判明:

| 確認項目 | 結果 |
|---|---|
| `~/.claude.json` の `mcpServers` | voicevox のみ。**Playwright MCP なし** |
| claude-pipeline.yml の Playwright install step | **なし** |
| allowedTools に `Bash(npx playwright test:*)` | あり（コマンド許可はされているが MCP 未設定） |
| 直近 evaluator 実行での Playwright 成功実績 | なし（PR #408/411/414/417 は全て Python/curl fallback） |

結果として、ADR-051 以降の evaluator job で Layer 1 Playwright が **一度も実際に動いていない**。Reviewer/Evaluator 自動連鎖の「Evaluator」部分が形式的な stub になっている。

---

## 2. 決定（What）

### 2-1. self-hosted runner に Playwright MCP を設定

`~/.claude.json` の `mcpServers` に `@playwright/mcp` を追加:

```json
{
  "mcpServers": {
    "voicevox": { ... },
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

### 2-2. Chromium ブラウザのインストール確認

Playwright MCP が Chromium を使うため、runner 上に以下が必要:

```bash
npx playwright install chromium
```

CI 実行時に毎回インストールすると遅いため、runner 上に一度グローバルインストールしておく。

### 2-3. evaluator job に Playwright 動作確認 step を追加 (任意)

```yaml
- name: Verify Playwright MCP available
  run: |
    node -e "require('@playwright/mcp')" 2>/dev/null && echo "Playwright MCP: OK" || echo "Playwright MCP: NOT FOUND"
```

---

## 3. Why

| # | 目的 | 優先度 |
|---|---|---|
| 1 | evaluator job が Layer 1 Playwright を実際に実行できる状態にする | 最優先 |
| 2 | Python/curl fallback への手動切り替えを廃止し、ADR-051 の完全自動化を実現 | 高 |
| 3 | LP や frontend の UI 変更 PR で実際のブラウザ検証が通ることを担保 | 高 |

---

## 4. Scope 外

- Layer 2 (Claude in Chrome MCP) のセットアップ (別途対応)
- CI/CD で毎回 Chromium をインストールする戦略（既インストール前提）
- GitHub-hosted runner への移行（self-hosted 維持）
- evaluator.md の判定ロジック変更

---

## 5. 事業上の制約

- `~/.claude.json` の既存 voicevox 設定を破壊しない
- 既存 allowedTools (evaluator job の `--allowedTools` パラメータ) は変更不要
- しんごさんが runner 上で手動コマンドを 2 行実行するだけで完了する手順にする

---

## 6. 検証要件

### Evaluator method

- [x] Layer 1: Playwright — 本 ADR 適用後の次の LP 変更 PR で evaluator が Playwright を起動し、`mcp__playwright__navigate` 等を実際に呼ぶことを確認
- [ ] Layer 2
- [ ] Skip

### Reviewer 追加観点

- [ ] `~/.claude.json` に `playwright` mcpServer エントリが追加されているか
- [ ] `npx playwright install chromium` が runner 上で完了しているか (または `which chromium` / `npx playwright --version` で確認)

### 追加検証 (人間)

1. 本 ADR マージ後、新しい LP 変更 ADR を 1 本通す
2. evaluator job ログで `mcp__playwright__navigate` の呼び出しを確認
3. Playwright が `https://salesanchor.jp/` を実際にブラウズしてスクリーンショットまたは DOM 検査を実行することを確認

---

## 7. 3 点セット要件

該当しない（runner ローカル設定変更のみ、外部システム新規連携なし）。

---

## 8. 代替案

| 案 | 評価 |
|---|---|
| A. Python/curl fallback を正式仕様にする | ❌ 却下。UI の実動作確認ができない |
| B. evaluator の Layer 1 宣言を全て Skip に変更 | ❌ 却下。LP/frontend PR で UI 検証が形骸化 |
| C. GitHub-hosted runner に移行して Playwright を毎回インストール | △ 検討余地あるが self-hosted のメリット（マシンパワー/速度/ローカル環境）を失う |
| **D. self-hosted runner に Playwright MCP を一度だけセットアップ（本案）** | ✅ 採用 |

---

## 9. 未決事項 (Generator / しんごさん 判断)

- `@playwright/mcp@latest` と `@playwright/mcp` の固定バージョンどちらを採用するか
- `npx playwright install chromium` と `npx playwright install --with-deps chromium` どちらか（macOS self-hosted なら `--with-deps` 不要）
- evaluator job に `Verify Playwright MCP available` step を追加するか（オプション）

---

## 10. 起案者の認知限界

- `@playwright/mcp` パッケージの実在確認: npm registry で存在確認済み（2025 年時点で `@playwright/mcp` として公開）
- runner 上の Node.js バージョン互換性は未確認（npx 経由なので基本問題ない想定）
- `~/.claude.json` の編集は Generator がファイル直接編集するか、しんごさんが手動編集するかどちらでもよい（Generator scope 内）
- 本 ADR は ADR-053 修正適用後の pipeline で動くため、Reviewer → Evaluator 自動連鎖の **完全自動化初成功テスト** になる想定

---

## 変更履歴

- 2026-05-20: 初版起案（Terminal Claude Code via Shingo）

# QA チェックシート — 運用ガイド

ひとしさん / しんごさんが本番 UI を共同で QA するためのチェックシート群。

## ファイル構成

| ファイル | 用途 |
|---|---|
| `qa_checksheet.html` | **メイン: ブラウザで開いて QA 実施** (在庫 64 + 受注 43 + シナリオ 33 = 140 項目、3 回分テスト対応) |
| `inventory_qa_checksheet_2026-05-27.md` | 在庫管理 QA の原本 (Markdown、人間が読む用) |
| `orders_qa_checksheet_2026-05-27.md` | 受注管理 QA の原本 (Markdown、人間が読む用) |
| `ui_qa_checksheet_2026-05-16.md` | 過去シート (UI 全体、参考用) |
| `qa_results_history/` | QA 結果 JSON の履歴 (時系列、git 管理対象) |

## 使い方

### 1. ブラウザで開く

**推奨: 公開URL（常に最新）**

```
https://shingo-ops.github.io/salesanchor/qa/
```

`develop` の `qa_checksheet.html` が更新されるたび、`publish-qa-checksheet.yml` が
GitHub Pages (gh-pages ブランチの `qa/index.html`) へ自動公開する（QA 2026-05-30 自動化）。
ローカルのクローンが古くても、この URL は常に最新を指す。ブラウザのお気に入り推奨。

**ローカルファイルで開く場合**（クローンが最新であること）

```bash
# Mac 側でリポをクローン/最新化後
open docs/audit/qa_checksheet.html
```

### 2. QA 実施

- **タブ切替**: 在庫管理 / 受注管理 / シナリオテスト (E2E)
- 各カードに 3 回分のテストブロック (1 回目 / 2 回目 / 3 回目)
- ⬜ 未 / ✅ OK / ❌ NG / 🟦 対象外 を選択
- NG の場合は memo に**再現手順 / 期待 / 実測**を残す
- 検証先 URL は **本番 (`app.salesanchor.jp`) / ローカル (`localhost:5173`)** で切替可
- 各カードの「🔗 ページを開く」リンクで該当画面を新規タブで開ける
- 状態は **LocalStorage に自動保存** (ブラウザを閉じても残る)

### 3. 結果共有

```
1. ひとしさん: QA 終了 → 「💾 書き出し」ボタン → qa_results_YYYY-MM-DD.json が DL
2. ひとしさん: docs/audit/qa_results_history/qa_results_YYYY-MM-DD_<suffix>.json に保存 (連番 _001, _002 等)
3. ひとしさん: git commit + push → develop merge
4. しんごさん: git pull → docs/audit/qa_results_history/ を確認
5. NG があれば修正 PR → 再 QA (ループ)
```

**リアルタイム共有はなし**。各人がローカルで QA → git commit で結果共有のフロー。

### 4. JSON 書き出し形式

```json
{
  "exported_at": "2026-05-27T10:30:00+09:00",
  "tool_version": "qa-checksheet-v1",
  "sheets": {
    "inventory": {
      "summary": { "total": 64, "ok": 30, "ng": 2, "na": 5, "pending": 27 },
      "items": [
        {
          "id": "SM-1",
          "category": "在庫一覧",
          "scenario": "在庫表のページが表示される",
          "effective_status": "ok",
          "trials": [
            { "trial": 1, "status": "ng", "memo": "再現手順..." },
            { "trial": 2, "status": "ok", "memo": "修正確認" },
            { "trial": 3, "status": "pending", "memo": null }
          ]
        }
      ]
    },
    "orders": { ... },
    "scenarios": { ... }
  },
  "signatures": {
    "hitoshi": { "date": "2026-05-27", "name": "森本" },
    "shingo": { "date": "2026-05-27", "name": "しんご" }
  }
}
```

`effective_status` は「最新の non-pending」を採用 (3 回目 > 2 回目 > 1 回目)。

### 5. Claude Code が読み取る場合

`docs/audit/qa_results_history/qa_results_*.json` を Read して `status="ng"` の項目を抽出。memo に書かれた再現手順 / 期待 / 実測を元に修正 PR を起票するフロー。

詳細: `~/.claude/projects/.../memory/feedback_qa_checksheet_workflow.md`

## 既知制約

- **チェックボックスの状態はブラウザ毎** (LocalStorage、共有不可) → 結果は JSON 書き出しで共有
- **複数人同時操作の競合制御なし** → 別々の時間に QA するか、最終的に JSON マージ
- **テスト 3 回固定** → 4 回以上必要なら別ブランチで HTML 拡張

## 関連ファイル

- 運用 memo: `~/.claude/projects/.../memory/feedback_qa_checksheet_workflow.md`
- 過去シート (UI 全体): `ui_qa_checksheet_2026-05-16.md`

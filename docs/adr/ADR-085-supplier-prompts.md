# ADR-085: 仕入先別 Gemini 解析プロンプトの管理

| 項目 | 内容 |
|------|------|
| ステータス | Accepted（管理レイヤ + パーサ統合とも実装） |
| 作成日 | 2026-05-31 |
| 起案 | Claude Code (Hikky-dev) |
| 関連 | migration 057/058（knowledge_rules / supplier_aliases）/ inventory_parser_llm |

> **更新 (2026-05-31)**: 当初「パーサ統合は Proposed（保留）」としたが、ひとしさんの指示で
> 実装した（後述「パーサ統合（実装済）」節）。出力形式の不一致は、Gemini の
> `response_schema`（structured output）で JSON を強制することで解消した
> （プロンプト本文に 8 列出力指示があっても JSON が返る）。

## What

仕入先（supplier）ごとに、Gemini に在庫メッセージを解析させる際のプロンプトを管理できるようにする。スプレッドシート「API解析」シート 6 行目 ♻️[Knowledge]（仕入先ごとのプロンプト 33 本）を取り込む。

### 本 ADR で実装する範囲（MVP・管理レイヤ）

- `public.supplier_prompts`（`supplier_id` UNIQUE / `prompt` TEXT）を新設（migration 087）。
- backend: `GET/PUT /super-admin/suppliers/{id}/prompt`（upsert）。
- frontend: 「正規化ルール / 別名」タブ（`knowledge` タブ）の先頭に**仕入先別プロンプト編集 UI**（仕入先 select + textarea + 保存）を追加。タブ名を「解析プロンプト / ルール」に変更。
- seed: `API解析.csv` 6 行目を仕入先名で突合し取り込み。

### パーサ統合（実装済 / 2026-05-31 追記）

- `parse_inventory_message` で `supplier_prompts` から有効プロンプトをロード（`_load_supplier_prompt`）。
- プロンプトがある仕入先は、**メッセージ全文**を Gemini に投げて解析（`_apply_supplier_prompt_llm` → `parse_with_gemini(..., supplier_prompt=...)`）。rule_v1 を上書きし `parse_engine='llm_supplier_prompt'`（status=`parsed_llm`）。
- 出力は `response_schema`（structured output）で現行 JSON スキーマ `{items:[...]}` に**強制**。プロンプト本文の 8 列出力指示は無視され、ダウンストリームの商品マッチング等は無改修で動く。
- フォールバック: budget HARD_STOP / LLM 設定なし / 呼び出し失敗 → rule_v1 結果。プロンプト未登録の仕入先は従来どおり rule_v1 + 別名 + knowledge。
- `supplier_prompts` テーブル不在の環境では `_load_supplier_prompt` が None を返し解析継続（非破壊）。

### 当初は保留としていた（現在は実装済）

> **重要**: 取り込んだプロンプトを**実際の Gemini 解析に使う配線は本 PR では行わない。**
> 理由: スプレッドシートのプロンプトは「**メッセージ全文 → 8 列フォーマット出力**」を前提とするが、
> 現行パーサは「rule_v1 で解けなかった**行のみ → JSON items 出力**」（`inventory_parser_llm.py`）。
> 入力範囲も出力スキーマも異なるため、プロンプトをそのまま現行経路へ差すと出力が壊れる。
> 「プロンプトがあれば正規化ルール / 別名も不要」を真に満たすには、**全文を Gemini に投げ
> 8 列出力を CRM スキーマへ変換する新経路**が必要（=出力スキーマ変更を伴う大改修）。
> これは別 ADR / 別 PR で、ひとしさんの方針確認のうえ実装する。

## Why

ひとしさん要望（QA 2026-05-31）：「仕入れ先ごとに Gemini に解析させる際のプロンプトを管理できるようにしてほしい。値はスプレッドシートから取り込んで。それがあれば正規化ルールも仕入元別名も不要」。

仕入先ごとに在庫メッセージの書式が大きく異なるため、グローバルな正規化ルール/別名より、仕入先別のプロンプトの方が解析精度を出しやすい（GAS 版の運用実績）。

## 非破壊方針

- `knowledge_rules` / `supplier_aliases`（テーブル・API・UI）は**削除しない**。プロンプト未登録の仕入先（12 社）は従来の rule_v1 + 別名 + knowledge で動作する必要があるため。
- パーサ統合（後続）後に、プロンプト登録済み仕入先のみ新経路へ切り替える想定。

## Consequences

- 仕入先別プロンプトを UI で編集・スプレッドシートから一括取込できる。
- 実際の解析への反映は後続（出力フォーマット整合の設計判断が前提）。
- seed 時、CSV ヘッダの仕入先名の末尾空白・表記ゆれは `TRIM(name)` 突合で吸収。一致しない仕入先はスキップ。

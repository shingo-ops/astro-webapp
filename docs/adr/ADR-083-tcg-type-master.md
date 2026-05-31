# ADR-083: TCG シリーズの「種別」をマスタ表 + UI 管理へ移行する

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-30 |
| 起案 | Claude Code (Hikky-dev) |
| 関連 | migration 061（tcg_series_master 初版）/ spec.md v1.1 F2（TCG シリーズマスタ）|

## What

TCG シリーズの「種別」(ポケモンカード / ワンピース 等) を、固定リストから **`public.tcg_type_master` 表 + UI 管理**へ移行し、**種別自体を画面から増減可能**にする。

### Scope

- `public.tcg_type_master` 新設（`code`(UNIQUE) / `name_ja` / `name_en` / `sort_order` / `is_active`）。既存 6 種別を seed。
- `tcg_series_master.tcg_type` の固定 **CHECK 制約を撤廃**（種別を自由に増減できるようにする）。`tcg_type` の値集合の正本は `tcg_type_master` とする。
- バックエンド: `/super-admin/tcg/types` の CRUD（GET/POST/PATCH/DELETE）。DELETE は使用中（その種別のシリーズが存在）なら 409 で拒否。Pydantic の固定値バリデータ (`_VALID_TCG_TYPES`) を撤廃。
- フロント: `TcgSeriesTab` の種別ドロップダウンを API 駆動に変更。「種別の管理」セクション（追加 / 削除）を追加。種別の表示名は master の `name_ja` を使用。

### 併せて是正するバグ

旧実装はフロントが種別値 `pokemon` を送る一方、DB の CHECK は `pokemon_booster_box` を要求しており**不整合**だった。そのため**ポケモンのシリーズは新規作成も一覧表示もできない**状態だった。master の `code`（= `pokemon_booster_box`）を正本にすることで是正する。

### 非対象

- `code` は安定キーとして**変更不可**（既存シリーズが参照するため）。改名は `name_ja`/`name_en` で行う。
- 種別とシリーズの間に DB の外部キー制約は張らない（撤廃した CHECK の代替は backend の「使用中チェック」で担保。FK は migration-test の最小ベースラインとの相性を避け、運用上のシンプルさを優先）。

## Why

- ひとしさん要望（QA 2026-05-30）「シリーズ種別自体も増減したいニーズがある。うまくマスタメンテナンスできるように」。
- 取り扱う TCG は増える前提（リポジトリに Degimon / GUNDUM / hololive / LORCANA 等の CSV が既に存在）。固定 CHECK ではゲーム追加のたびに migration + コード変更が必要で運用が硬直化する。
- 種別をデータ（マスタ表）として持てば、UI から追加・削除でき、表示名の i18n もデータ側に集約できる。

## Consequences

- 種別追加が DB マイグレーション不要・UI 操作のみで可能になる。
- 種別の表示名は DB（`name_ja`/`name_en`）が正本。旧 i18n 固定ラベル `superAdmin.tcg.types.*` への依存を解消（キー自体は当面温存）。
- Pokemon BB シード（別 PR）は `tcg_type='pokemon_booster_box'` で投入すれば一覧に正しく表示される。
- 将来: 種別の `is_active` による表示制御 UI、並び替え UI は本 ADR の範囲外（必要時に拡張）。

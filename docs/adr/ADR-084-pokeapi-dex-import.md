# ADR-084: ポケモン図鑑を PokeAPI から取込（差分プレビュー→一括反映）

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-30 |
| 起案 | Claude Code (Hikky-dev) |
| 関連 | migration 061（pokemon_dex / trainer_dex）/ ADR-083（TCG 種別マスタ）|

## What

「ポケモン/トレーナー図鑑」タブに、**外部ソース（PokeAPI）から最新のポケモンを取得し、既存 `public.pokemon_dex` との差分をプレビューしてから一括取込する**機能を追加する。

- `POST /super-admin/dex/pokemon/import/preview`: PokeAPI の全国図鑑一覧と既存 `dex_number` を突合し、**DB に無い新規分**を日本語名（`ja-Hrkt`）・英語名・世代つきで返す（**DB 書込なし**）。
- `POST /super-admin/dex/pokemon/import/apply`: プレビューで得た新規分のみ `INSERT ... ON CONFLICT (dex_number) DO NOTHING`（既存は不変）。
- フロント（DexTab）: 「PokeAPIから取込」ボタン → 差分プレビュー（新規件数＋一覧）→「一括取込」ボタン。

### Scope / 非対象

- **ポケモンのみ**。トレーナー図鑑は PokeAPI にデータが無く、入れるデータも未定義のため対象外（ひとしさん確認済み 2026-05-30）。
- **新規追加のみ**を検出・取込。既存エントリの名称修正の全件照合は、全 1025 件の詳細取得が必要で外部負荷が大きいため本 ADR では行わない（将来検討）。
- 削除（PokeAPI に無いが DB にある）も行わない（誤削除回避）。

## Why

ひとしさん要望（QA 2026-05-30）：「wiki などから最新情報を取得して反映させる機能。取込ボタン→差分解析→結果表示→一括取込」。新世代・新セット追加時にポケモン名マスタを手作業で足すのは手間で漏れも出るため、構造化ソースから取り込めるようにする。

PokeAPI を採用（調査済み）：構造化 JSON API・キー不要・`ja-Hrkt`/`en`/`generation` を返し現 DB に 1:1 対応。Bulbapedia 等のスクレイピングは規約配慮・実装難度が高く、PokeAPI が最適。

## 安全策

- **手動トリガのみ**（super-admin が取込ボタンを押した時だけ）。自動同期はしない。
- 外部 URL は固定（SSRF 防止・ユーザー入力 URL を受けない）。`require_super_admin` ガード。
- httpx タイムアウト（接続10s/全体30s）＋ 並列度制限（Semaphore 5）＋ 取得件数上限（`max_fetch=500`）。
- **一覧取得は 1 リクエスト**。詳細取得は「DB に無い新規番号」だけに絞るため、既に最新（新規 0 件）なら一覧 1 リクエストで完了し外部負荷は最小（PokeAPI Fair Use 準拠）。
- 2 フェーズ（preview = stateless 差分計算 / apply = 冪等 UPSERT）。

## Consequences

- 新ポケモン追加が UI 操作のみで反映可能になる。既存データは保護（追加のみ・上書き/削除なし）。
- 名称修正・トレーナーは将来フェーズ。PokeAPI の規約・利用範囲の最終判断はしんごさんマター（社内マスタ名称同期用途）。

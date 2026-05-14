# ADR-034: 新規テナント migration 自動化

| 項目 | 内容 |
|------|------|
| ステータス | Proposed |
| 作成日 | 2026-05-15 |
| 関連 | ADR-028（撮影テナント分離）|

## What

1. deploy.yml に「全テナントへの migration 適用ループ」を追加する
2. 新規テナント作成スクリプト（setup_tenant.py）に「過去の全 migration を適用する」処理を追加する
3. tenant_006 に未適用の migration を全て適用する

## Why

2026-05-14（Meta App Review 撮影準備中）に tenant_006 で以下の3件の migration 未適用が発覚した：

1. public.meta_page_routing への自動登録欠落 → webhook が届かない
2. tenant_006.meta_messages の9カラム欠落 → Inbox が500エラー
3. tenant_006.meta_messages.message_id が VARCHAR(100) のまま → Instagram DM（172文字）が保存できない

これらは全て「tenant_006 が古いテンプレートで作成され、その後の migration が適用されていない」という同一原因から発生した。

ローンチ後に新規クライアントのテナントを作成した際、同じ問題が発生する。
新規クライアントが Channels を接続してもメッセージが届かない = 直接的なクレームにつながる。

## Scope 外

- スキーマ分離方式の変更（現設計を維持）
- 既存テナント（tenant_001〜005）のスキーマ変更
- Row Level Security への移行

## 実装方針

### 1. deploy.yml に全テナント migration ループを追加

migration SQL ファイルを「テナント共通」と「テナント固有」に分類し、テナント固有の migration は全テナントに対してループで実行する。

### 2. 新規テナント作成スクリプトの修正

scripts/setup_tenant.py に「既存の全 migration を適用するステップ」を追加する。

### 3. tenant_006 の未適用 migration を確認・適用

tenant_001〜005 と tenant_006 のスキーマ差分を洗い出し、全て適用する。

## 事業上の制約

- 既存テナント（tenant_001〜005）への影響は最小化する
- migration は idempotent（何度実行しても同じ結果）に設計する
- マージ判断は Shingo（自動マージ禁止）

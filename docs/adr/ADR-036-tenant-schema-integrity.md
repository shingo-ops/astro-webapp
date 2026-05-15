# ADR-036: テナントスキーマ整合性保証

## What

以下の4レベルで「新規テナントを作成しても同じ問題が2度と発生しない」状態を実現する。

### Level 1（即時）: tenant_004 と tenant_006 の完全差分解消

scripts/db/sync_tenant_schema.py を実装:
- tenant_004 の全テーブル・カラム・型・パーミッションを基準として
- 全テナント（tenant_001〜006）との差分を検出
- 差分を自動で適用

### Level 2（ADR-034 完全版）: setup_tenant.py の完全版

新規テナント作成時に:
- tenant_004 のスキーマスナップショットを取得
- 新テナントに完全適用
- 適用後に整合性チェックを実行

### Level 3（CI/CD）: スキーマ整合性チェッカー

.github/workflows/schema-check.yml を追加:
- 全テナントのスキーマを比較
- 差分があればPRをブロック
- deploy.yml にも組み込む

### Level 4（自動テスト）: テナントスキーマテスト

backend/tests/test_tenant_schema_integrity.py を追加:
- 全テナントのテーブル数・カラム数・型が一致しているかテスト
- パーミッション数が一致しているかテスト
- pytest CI に組み込む

## Why

2026-05-14〜15 に tenant_006 で以下の4件が発生:
1. meta_page_routing の sync トリガー欠落
2. meta_messages の 9 カラム欠落
3. message_id VARCHAR(100) → TEXT 未適用
4. パーミッション設定欠落

全て「新規テナントに過去の migration が適用されない」同一原因。
ローンチ後に新規クライアントを追加するたびに同じ問題が発生するリスクがある。

## Scope 外
- マルチテナントの設計変更（スキーマ分離方式の維持）
- テナント間のデータ共有

## 事業上の制約
- 既存テナント（tenant_001〜006）への影響は最小化
- 全操作は idempotent（何度実行しても安全）
- マージ判断は Shingo（自動マージ禁止）

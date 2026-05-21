# ADR-065: asyncpg プリペアドステートメントキャッシュ無効化

## ステータス
Accepted

## 日付
2026-05-21

## コンテキスト

本番環境（FastAPI + SQLAlchemy 2.x asyncpg + PostgreSQL 16）において、
Dockerコンテナ再起動直後に `/api/v1/conversations` の**最初のリクエストだけ 500 エラー**が発生する問題が報告された。

### エラー内容

```
asyncpg.exceptions.InvalidCachedStatementError:
  cached statement plan is invalid due to a database schema or configuration change
(SQLAlchemy asyncpg dialect will now invalidate all prepared caches in response to this exception)
```

### 発生メカニズム

1. asyncpg はデフォルトで接続ごとに最大 100 件の プリペアドステートメントを LRU キャッシュする
2. DBスキーマ変更（マイグレーション適用）後にコンテナを再起動すると、
   PostgreSQL サーバー側の実行計画が古いスキーマに基づいたまま残っている場合がある
3. asyncpg が古いキャッシュエントリを使ってクエリを送ると
   PostgreSQL が `InvalidCachedStatementError` を返す
4. SQLAlchemy asyncpg ダイアレクトはこのエラーを受け取ると**自動でキャッシュ全消去**して
   次のリクエストから正常化する（自己回復）
5. 結果として「1回目失敗 → リロードで成功」というユーザー体験になる

### ユーザー影響

- コンテナ再起動（デプロイ・障害復旧）のたびに最初のリクエストが失敗する
- フロントエンドに「会話一覧の取得に失敗しました Reload」と表示される
- 自己回復するが、ユーザーが手動でリロードする必要がある

## 決定

`backend/app/database.py` の `create_async_engine` に
`connect_args={"prepared_statement_cache_size": 0}` を追加し、
asyncpg のプリペアドステートメントキャッシュを無効化する。

### 正しいパラメータ名について

SQLAlchemy 2.x asyncpg ダイアレクトの DBAPI 引数名は
`prepared_statement_cache_size`（SQLAlchemy管理）である。
`statement_cache_size`（asyncpg ネイティブ）は asyncpg に直接渡る別ルートであり、
SQLAlchemy レイヤーで管理されないため将来バージョンで壊れるリスクがある。

## 変更内容

```python
# backend/app/database.py
if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_size=20,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
        connect_args={"prepared_statement_cache_size": 0},  # ADR-065
    )
```

## 影響範囲

| 対象 | 影響 |
|------|------|
| FastAPI 非同期エンドポイント（asyncpg） | キャッシュ無効化（対象） |
| Celery タスク（psycopg2 同期エンジン） | 影響なし（別ドライバ） |
| テスト環境（SQLite） | 影響なし（postgresql ガード内のみ適用） |
| 接続プール（pool_size=20, max_overflow=10） | 影響なし（プール管理とは独立） |

## パフォーマンストレードオフ

- キャッシュ無効化により、同一SQLの実行ごとにPostgreSQLでパース・実行計画生成が走る
- 追加コスト：1クエリあたり数百μs〜数ms程度
- 中小規模CRM（月間PV 10万以下）では I/O がボトルネックのため体感影響は軽微と判断
- 将来的にスケールした場合は、PgBouncer導入や`prepared_statement_cache_size`を
  小さい値（例: 10）に設定する段階的調整を検討する

## 代替案（不採用）

| 案 | 不採用理由 |
|----|-----------|
| `DEALLOCATE ALL` をコンテナ起動時に実行 | 全接続に対し発行が必要で複雑。entrypoint改修が必要 |
| `pool_recycle` 短縮 | 再起動後1回目の失敗を防げない |
| `pool_pre_ping=True` のみ | 死活確認であり、キャッシュ無効化とは別問題 |
| 自己回復を許容してUIでハンドリング | ユーザーが手動リロードを強いられる根本解決にならない |

## レビュー

- Reviewer: CONDITIONAL_APPROVE → パラメータ名修正後 APPROVE 相当
- 主な指摘: `statement_cache_size` → `prepared_statement_cache_size` に修正済み
- 追加指摘（別チケット）: `list_conversations` の `unread_only` フィルタが
  SQL LIMIT 適用後にPython側で実施されているページネーションバグ（中優先度）

## 参照

- SQLAlchemy 2.x asyncpg ダイアレクト §asyncpg_prepared_statement_cache
- asyncpg 0.31.0 `connect()` API: `statement_cache_size` パラメータ
- 発生ログ: `astro-webapp-backend-1` 2026-05-21 (本番確認)

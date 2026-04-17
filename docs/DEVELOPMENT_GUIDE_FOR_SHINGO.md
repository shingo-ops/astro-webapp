# 開発ガイド（しんごさん向け）

> 2026-04-17 時点の状況に基づく。新規機能の追加開発を始める前に必ず読んでください。

---

## 1. プロジェクト構成

```
astro-webapp/
├── backend/              ← FastAPI (Python 3.12)
│   ├── app/
│   │   ├── main.py           ← FastAPIアプリ本体・ルーター登録
│   │   ├── routers/          ← APIエンドポイント（customers/deals/leads/roles/teams/etc.）
│   │   ├── schemas/          ← Pydanticバリデーション
│   │   ├── services/         ← テナント管理・監査ログ
│   │   ├── auth/             ← Firebase認証・権限チェック（require_permission）
│   │   ├── tasks/            ← Celeryタスク（ダッシュボードKPI/レポートCSV/メンテナンス）
│   │   ├── cache.py          ← Redis キャッシュ管理
│   │   ├── database.py       ← DB接続プール設定
│   │   └── models.py         ← SQLAlchemy モデル（publicスキーマのTenant/Userのみ）
│   ├── tests/                ← pytest（SQLiteインメモリ）
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/             ← React 18 + TypeScript + Vite
│   ├── src/
│   │   ├── App.tsx           ← ルーティング定義
│   │   ├── App.css           ← 全スタイル（CSS変数でダークモード対応）
│   │   ├── components/       ← Layout/NavDropdown/ConfirmModal/ProtectedRoute
│   │   ├── pages/            ← 各ページコンポーネント
│   │   ├── hooks/            ← usePermissions（権限取得フック）
│   │   ├── lib/              ← api.ts（APIクライアント+自動リトライ）/ firebase.ts
│   │   └── contexts/         ← AuthContext（Firebase認証状態管理）
│   ├── package.json
│   └── Dockerfile
├── migrations/           ← SQLマイグレーション（手動実行、Alembicは未使用）
├── scripts/              ← マイグレーション・バックアップ等の運用スクリプト
├── nginx/                ← Nginx設定
├── monitoring/           ← Prometheus/Grafana/Loki/Promtail設定
├── docker-compose.yml    ← 全コンテナ定義
└── docs/                 ← 各種ドキュメント
```

---

## 2. ブランチ運用ルール

### 基本フロー
```
develop（開発統合）  →  main（本番）
    ↑                        ↑
feature/xxx/機能名     PR (develop → main) でリリース
```

### ブランチ命名規則
```
feature/<あなたの名前>/機能を英語で簡潔に
```

例:
```
feature/shingo/inventory-management
feature/shingo/quote-pdf-export
feature/shingo/meta-webhook-integration
```

### 守るべきルール
| ルール | 理由 |
|-------|------|
| **`develop` や `main` に直接コミットしない** | レビューなしの変更は事故の元 |
| **必ず `develop` から feature ブランチを切る** | main は本番リリース専用 |
| **feature → develop はPRでマージ** | 変更履歴とレビューが残る |
| **develop → main もPRでマージ** | GitHub Actions で自動デプロイが走る |

### 作業開始手順
```bash
# 1. developを最新化
git checkout develop
git pull origin develop

# 2. featureブランチを作成
git checkout -b feature/shingo/my-new-feature

# 3. 作業＆コミット（こまめに！30分に1回以上）
git add -A
git commit -m "WIP: ○○の実装途中"

# 4. 作業終了・中断時は必ずpushまで
git push origin HEAD
```

---

## 3. 現在のブランチ状況

### アクティブなブランチ
| ブランチ | 状態 | 説明 |
|---------|------|------|
| `main` | 本番稼働中 | VPS (jarvis-claude.uk) で稼働 |
| `develop` | 開発統合 | main と同期済み。**新ブランチはここから切る** |

### 全てマージ済み（触る必要なし）
`feature/morimoto/*` ブランチが多数ありますが、**全て develop にマージ済み**です。GitHub上にリモートブランチが残っていますが、作業中のものはありません。

### オープンなPR
**なし**（2026-04-17 時点）

---

## 4. 触ってはいけないファイル / 変更時に注意が必要なファイル

### :no_entry: 変更禁止（理由がない限り触らない）

| ファイル | 理由 |
|---------|------|
| `backend/app/auth/dependencies.py` | 認証・認可の中核。`get_current_user` / `get_current_tenant` / `require_permission` はセキュリティの根幹 |
| `backend/app/services/tenant.py` | テナントスキーマ作成・RLSポリシー・システムロールシード。変更すると全テナントに影響 |
| `backend/app/cache.py` | JWT/権限/テナントキャッシュ。TTL設計とfail-closed設計が重要 |
| `backend/app/middleware/audit.py` | 認証イベント自動記録 |
| `migrations/001_*`, `002_*`, `003_*` | 適用済みマイグレーション。既存ファイルは変更不可（新規 `004_*` で対応） |
| `docker-compose.yml` | 全コンテナ構成。変更する場合は必ずVPS側のメモリ制約（1GB）を考慮 |

### :warning: 変更時に注意が必要

| ファイル | 注意点 |
|---------|--------|
| `backend/app/main.py` | ルーター登録。新機能追加時にここにルーター追加が必要 |
| `backend/app/models.py` | `public` スキーマのモデル（Tenant/User）のみ。業務テーブルはテナントスキーマで raw SQL |
| `frontend/src/App.tsx` | ルーティング。新ページ追加時にここにRoute追加 |
| `frontend/src/components/Layout.tsx` | トップナビ。メニュー項目を追加する場合はここ |
| `frontend/src/App.css` | 全スタイル定義。CSS変数（`var(--bg-surface)` 等）を使うこと。直接の色コード使用は避ける |
| `frontend/src/index.css` | CSS変数定義（ライト/ダークモード）。色追加はここ |
| `nginx/nginx.conf` | 新APIパスを追加する場合はrate limit設定にも注意 |

---

## 5. 開発で守るべきパターン（セキュリティ）

全ての新規エンドポイントで以下を必ず守ってください。

### 5.1 認証・認可

```python
from app.auth.dependencies import get_current_user, get_current_tenant, require_permission

@router.get(
    "/my-resource",
    dependencies=[Depends(require_permission("my_resource.view"))],  # 権限チェック
)
async def list_my_resource(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),  # search_path自動切替
    current_user: User = Depends(get_current_user),
):
    ...
```

### 5.2 SQLクエリ

```python
# ✅ 正しい: パラメータ化クエリ
result = await db.execute(
    text("SELECT * FROM my_table WHERE id = :id"),
    {"id": some_id},
)

# ❌ 間違い: f-string で値を埋め込む → SQLインジェクション
result = await db.execute(text(f"SELECT * FROM my_table WHERE id = {some_id}"))
```

### 5.3 監査ログ

すべてのCREATE / UPDATE / DELETE で `record_audit_log()` を呼ぶ:

```python
from app.services.audit import record_audit_log

await record_audit_log(
    db=db, tenant_id=tenant_id, user_id=current_user.id,
    action="create",  # create / update / delete
    table_name="my_table",
    record_id=new_record_id,
    new_data={"field": "value"},  # パスワード等は入れない
)
```

### 5.4 commit 後の注意

```python
# ❌ commit後にテナントテーブルをSELECTするとエラーになる場合がある
await db.commit()
result = await db.execute(text("SELECT * FROM my_table WHERE id = :id"), ...)
# → "relation my_table does not exist"

# ✅ 方法1: UPDATE/INSERT RETURNING で commit 前にデータ取得
result = await db.execute(text("UPDATE ... RETURNING *"), ...)
row = result.mappings().first()
await db.commit()
return MyResponse(**dict(row))

# ✅ 方法2: commit後に search_path を再設定
from app.auth.dependencies import reset_tenant_context
await db.commit()
await reset_tenant_context(db, tenant_id)
result = await db.execute(text("SELECT ..."), ...)
```

### 5.5 PATCH（部分更新）のホワイトリスト

```python
# 更新可能なカラムを明示的に制限する
_UPDATABLE_COLUMNS = {"name", "email", "phone"}

update_data = data.model_dump(exclude_unset=True)
update_data = {k: v for k, v in update_data.items() if k in _UPDATABLE_COLUMNS}
```

---

## 6. 新機能を追加する時のチェックリスト

### バックエンド

- [ ] `backend/app/schemas/` に Pydantic スキーマ作成（Create / Update / Response）
- [ ] `backend/app/routers/` にルーター作成（CRUD + 権限チェック）
- [ ] `backend/app/main.py` にルーター登録
- [ ] 新テーブルが必要なら `backend/app/services/tenant.py` の `_TENANT_TABLES_SQL` にCREATE TABLE追加
- [ ] 同テーブルに RLS ポリシー追加（`_RLS_ENABLE_SQL` + `_RLS_POLICY_SQL`）
- [ ] 既存テナント用のマイグレーション SQL を `migrations/004_*.sql` として作成
- [ ] 新しい権限キーが必要なら `migrations/` でINSERTし、`seed_system_roles` のロール定義も更新
- [ ] `record_audit_log()` を全 CREATE/UPDATE/DELETE で呼び出し
- [ ] `invalidate_dashboard_cache(tenant_id)` をデータ変更後に呼び出し
- [ ] テスト追加（`backend/tests/`）

### フロントエンド

- [ ] `frontend/src/pages/` にページコンポーネント作成
- [ ] `frontend/src/App.tsx` にルート追加
- [ ] `frontend/src/components/Layout.tsx` にナビ項目追加（既存のComingSoonページから置き換え）
- [ ] 権限チェック: `usePermissions()` フックの `hasPermission("xxx.view")` で表示制御
- [ ] CSS は `App.css` の CSS変数（`var(--bg-surface)` 等）を使用（ダークモード対応のため）

### ドキュメント

- [ ] `docs/ACCESS_CONTROL.md` の権限マトリクスを更新
- [ ] `docs/FEATURE_SPECIFICATION.md` の対応状況を更新

---

## 7. テストの実行方法

```bash
# Mac側で実行（Docker不要、SQLiteインメモリで動く）
cd backend
DATABASE_URL="sqlite+aiosqlite:///:memory:" python -m pytest tests/ -v

# 特定テストだけ実行
DATABASE_URL="sqlite+aiosqlite:///:memory:" python -m pytest tests/test_customers.py -v

# フロントエンドの型チェック
cd frontend
npx tsc --noEmit
```

### 既知の失敗テスト（無視してOK）
- `test_delete_customer_with_deal_returns_409` — SQLite が FK 制約を強制しないため
- `test_delete_deal_with_order_returns_409` — 同上（PostgreSQL 本番では正常動作）

---

## 8. デプロイの流れ

```
feature/shingo/xxx → PR → develop にマージ
                              ↓
                     develop → PR → main にマージ
                              ↓
                     GitHub Actions 「Deploy to VPS」 が自動実行
                              ↓
                     VPS で docker compose up --build が走る
                              ↓
                     https://jarvis-claude.uk に反映
```

### DB マイグレーションが必要な場合（新テーブル/カラム追加時）

GitHub Actions の自動デプロイではマイグレーション SQL は実行されません。VPS に SSH して手動実行が必要です:

```bash
# VPS側で実行
ssh ubuntu@49.212.137.46

cd /home/ubuntu/astro-webapp

# 例: 新しいマイグレーション適用
docker compose exec -T postgres psql -U jarvis -d jarvis_db < migrations/004_your_migration.sql

# または Python スクリプト経由
docker compose cp scripts backend:/app/scripts
docker compose exec backend python /app/scripts/your_migration.py
```

---

## 9. 環境情報

| 項目 | 値 |
|------|-----|
| 本番URL | https://jarvis-claude.uk |
| GitHub | https://github.com/shingo-ops/astro-webapp |
| VPS | さくらVPS 49.212.137.46 (Ubuntu 24.04, 1GB RAM) |
| DB | PostgreSQL 16（マルチテナント・スキーマ分離） |
| 認証 | Firebase Authentication + MFA |
| CI/CD | GitHub Actions → SSH → docker compose up --build |

---

## 10. Phase 2 以降で実装予定の機能（参考）

詳細は `docs/FEATURE_SPECIFICATION.md` を参照。

| Phase | 機能 | 現状のルート |
|-------|------|------------|
| 2 | 在庫管理（商品マスタ） | `/inventory` → ComingSoonPage |
| 2 | 見積もり管理 | `/quotes`, `/quotes/new` → ComingSoonPage |
| 2 | 請求書管理 | `/invoices/new` → ComingSoonPage |
| 3 | レポート・分析 | `/reports` → ComingSoonPage |
| 4 | Meta連携（WhatsApp/Instagram） | `/lead-chat` → ComingSoonPage |
| 4 | 設定 | `/settings` → ComingSoonPage |
| 4 | テンプレート管理 | `/templates` → ComingSoonPage |
| 5 | データ管理 | `/data` → ComingSoonPage |
| 5 | 商材ナレッジ | `/knowledge` → ComingSoonPage |
| 5 | 翻訳プロンプト | `/prompts` → ComingSoonPage |

---

## 11. 困ったときの連絡先

| 担当 | 連絡先 | 対応範囲 |
|------|--------|---------|
| hitoshi（morimoto） | 業務委託 | インフラ・セキュリティ・バックエンド・フロントエンド全般 |

質問がある場合は、GitHub の Issue または PR のコメントに書いてください。コードベースの意図を説明できます。

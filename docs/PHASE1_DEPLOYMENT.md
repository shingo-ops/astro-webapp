# Phase 1 デプロイ手順書

## 変更履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-04-16 | 初版作成（Phase 1デプロイ手順） |

---

## 概要

Phase 1 実装では以下の新機能を追加しました。

- Discord式カスタムロール・権限システム（roles/permissions/user_roles）
- リード管理（leads + 見込度自動算出 + 案件化）
- チーム管理（teams/team_members）
- 顧客マスタ拡張（請求先/配送先、customer_code自動採番）
- 案件拡張（deal_code、stage、probability、currency、assigned_to）

## デプロイ手順

### 1. 事前準備（ローカル・Mac側）

```
# feature/morimoto/phase1-rbac-leads-teams ブランチからPRを作成
cd /Users/hitoshi/Documents/副業/業務委託/しんごさん/CRMシステム/astro-webapp
gh pr create --base develop --head feature/morimoto/phase1-rbac-leads-teams \
  --title "feat: Phase 1 ロール・権限・リード・チーム実装" \
  --body "$(cat <<'EOF'
## 概要
Phase 1 として、Discord式カスタムロール＋リード＋チーム＋
顧客/案件拡張を実装。

## 変更内容
- `migrations/002_add_permissions_master.sql` 追加
- `migrations/003_add_phase1_tenant_tables.sql` 追加
- `scripts/migrate_phase1.py` 追加
- バックエンド: roles/leads/teams ルーター新設、customers/deals 拡張、
  require_permission 統合
- フロントエンド: RolesPage/LeadsPage/TeamsPage 新設、
  usePermissions フックによるUI権限制御
- ドキュメント: ACCESS_CONTROL/SECURITY/FEATURE_SPECIFICATION 更新

## テスト
- 既存テスト96件合格（SQLiteでFK制約を前提にした2件は既存の既知問題）
EOF
)"
```

### 2. developブランチへのマージ

レビュー後、GitHub上でマージ。

### 3. VPS側でのマイグレーション実行

developにマージされた変更が本番デプロイされた後、マイグレーションを実行します。

**VPS側（ubuntu@49.212.137.46）**:
```
cd /home/ubuntu/astro-webapp
git pull origin develop

# permissions マスターテーブル作成（公開スキーマ）
docker compose exec -T postgres psql -U jarvis -d jarvis_db < migrations/002_add_permissions_master.sql

# 全テナントにPhase 1テーブル追加＋システムロールシード
docker compose exec backend python /app/scripts/migrate_phase1.py
```

### 4. 動作確認

ブラウザで https://jarvis-claude.uk にアクセスし、以下を確認:

- [ ] ログインできる（既存機能の後方互換）
- [ ] サイドバーに「リード管理」「チーム管理」「ロール・権限」が表示される
- [ ] 顧客管理画面のタブ（基本情報/請求先/配送先）が動作する
- [ ] ロール・権限画面で「オーナー」「メンバー」が表示される
- [ ] リード新規登録で見込度ランクが自動算出される
- [ ] 権限を剥奪したユーザーで対象画面が非表示になる（要Redis権限キャッシュパージ）

### 5. ロールバック手順（必要時）

マイグレーションSQL は全て `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`
を使っており、追加のみで破壊的変更なし。データは保持される。

万一問題が発生した場合:

**バックエンドロールバック**:
```
cd /home/ubuntu/astro-webapp
git checkout <前回のコミットハッシュ>
docker compose up -d --build backend
```

**DBロールバック（必要な場合のみ）**:
追加されたテーブル・カラムは残しても従来機能に影響なし。どうしても削除したい場合:
```
docker compose exec postgres psql -U jarvis -d jarvis_db <<'EOF'
-- 全テナントから新テーブルを削除（要事前バックアップ）
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT schema_name FROM information_schema.schemata
             WHERE schema_name LIKE 'tenant_%'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.team_members, %I.teams, %I.user_roles, %I.role_permissions, %I.roles, %I.leads CASCADE',
            r.schema_name, r.schema_name, r.schema_name, r.schema_name, r.schema_name, r.schema_name);
    END LOOP;
END $$;
DROP TABLE IF EXISTS public.permissions CASCADE;
EOF
```

## セキュリティチェックリスト

Phase 1実装時に以下のセキュリティ対策を全新規エンドポイントに適用:

- [x] `Depends(get_current_tenant)` でスキーマ切替 + RLS設定
- [x] `require_permission()` で権限チェック
- [x] パラメータ化SQL（`text()` + named params）
- [x] `record_audit_log()` を全 CREATE/UPDATE/DELETE で呼出
- [x] `invalidate_dashboard_cache()` / `invalidate_tenant_permissions()` でキャッシュ破棄
- [x] Pydantic `Field(max_length=...)` + validator による入力検証
- [x] キャッシュキーに `tenant_id` を含める
- [x] 新テーブル（leads/roles/teams）にRLS有効化 + ポリシー適用
- [x] tenant_id はDBから取得（URL・JWT直接受け取り禁止）

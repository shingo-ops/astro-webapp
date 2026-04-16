# アクセス制御ポリシー - Jarvis CRM

## 変更履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-04-17 | CS ロールの表記を「カスタマーサクセス」→「カスタマーサポート」に修正（業態に合わせた用語選択） |
| 2026-04-16 | GAS版互換ロール5種（オーナー/システム管理者/リーダー/営業/CS）を既定に変更。メンバーロール廃止。新規ユーザーの既定ロールを CS に変更。 |
| 2026-04-16 | Phase 1: Discord式カスタムロール制へ移行。権限マスタ導入、エンドポイント毎の`require_permission`を追加。leads/teams/roles を新設。 |
| 2026-03-xx 以前 | admin/user の2値ロール制 |

---

## 1. ロールシステム（Discord式カスタムロール）

テナント管理者はロール自体を自由に作成し、リソース×アクション単位の権限を割り当てられる。

### 1.1 ロールの基本ルール
- **1ユーザー＝複数ロール可**、権限は全ロールの**和集合**（Discord式）
- ロールには**priority**（優先順位）があり、自分の最大priorityより低いロールのみ管理可能
- `is_system=TRUE`のロール（オーナー/メンバー）は**削除/編集不可**
- 権限マスタ（`public.permissions`）は全テナント共有

### 1.2 既定ロール（テナント作成時に自動生成、GAS版互換）

| ロール名 | priority | is_system | 権限 | 用途 |
|---------|---------|-----------|------|------|
| オーナー | 1000 | ✅ | 全権限 | テナント代表者。削除/編集不可 |
| システム管理者 | 900 | ❌（編集可） | system.manage 以外の全権限 | IT/運用管理担当 |
| リーダー | 500 | ❌（編集可） | チーム/リード/案件管理、レポート参照 | チームマネージャー |
| 営業 | 300 | ❌（編集可） | 顧客・リード・案件・注文のCRUD | 営業担当者 |
| CS | 300 | ❌（編集可） | 顧客フォロー、閲覧中心 | カスタマーサポート |

オーナー以外の4ロールは既定テンプレートとして作成されるが、テナント管理者が自由に権限編集可。また、独自のカスタムロールを追加作成もできる（Discord式）。

### 1.3 後方互換
既存の `public.users.role` カラム（admin/user）は保持。Phase 1マイグレーションで既存ユーザーにロールを自動付与:
- `role='admin'` → 「オーナー」
- `role='user'` → 「CS」（旧メンバー相当）

新規ユーザー（`POST /api/v1/auth/register`）には **CS** ロールが自動付与される。

---

## 2. 権限キー一覧（`public.permissions` テーブル）

| カテゴリ | 権限キー | 説明 |
|---------|---------|------|
| システム | `system.manage` | システム設定の管理 |
| システム | `system.audit_view` | 監査ログの閲覧 |
| ロール | `roles.view` | ロール一覧の閲覧 |
| ロール | `roles.create` | ロールの作成 |
| ロール | `roles.update` | ロールの編集・権限割当 |
| ロール | `roles.delete` | ロールの削除 |
| ロール | `roles.assign` | ユーザーへのロール付与 |
| 顧客 | `customers.view/create/update/delete` | 顧客CRUD |
| リード | `leads.view/create/update/delete/convert` | リードCRUD＋案件化 |
| 案件 | `deals.view/create/update/delete` | 案件CRUD |
| 注文 | `orders.view/create/update/delete` | 注文CRUD |
| チーム | `teams.view/create/update/delete/manage_members` | チームCRUD＋メンバー管理 |
| レポート | `dashboard.view` `reports.view` `reports.export` | 可視化機能 |

---

## 3. APIエンドポイント権限マトリクス

### 認証不要（パブリック）
| エンドポイント | メソッド | 用途 |
|---------------|---------|------|
| `/api/health` | GET | ヘルスチェック |
| `/api/v1/auth/register` | POST | ユーザー登録 |
| `/api/v1/auth/logout` | POST | ログアウト |

### 認証必須（権限チェックあり）

| エンドポイント | メソッド | 必要権限 |
|---------------|---------|---------|
| `/api/v1/customers` | GET | `customers.view` |
| `/api/v1/customers` | POST | `customers.create` |
| `/api/v1/customers/{id}` | PATCH | `customers.update` |
| `/api/v1/customers/{id}` | DELETE | `customers.delete` |
| `/api/v1/leads` | GET | `leads.view` |
| `/api/v1/leads` | POST | `leads.create` |
| `/api/v1/leads/{id}` | PATCH | `leads.update` |
| `/api/v1/leads/{id}` | DELETE | `leads.delete` |
| `/api/v1/leads/{id}/convert` | POST | `leads.convert` |
| `/api/v1/deals` | GET | `deals.view` |
| `/api/v1/deals` | POST | `deals.create` |
| `/api/v1/deals/{id}` | PATCH | `deals.update` |
| `/api/v1/deals/{id}` | DELETE | `deals.delete` |
| `/api/v1/orders` | GET/POST/PATCH/DELETE | （注文系権限は現状admin/userのまま、Phase 2で追加） |
| `/api/v1/teams` | GET | `teams.view` |
| `/api/v1/teams` | POST | `teams.create` |
| `/api/v1/teams/{id}` | PATCH | `teams.update` |
| `/api/v1/teams/{id}` | DELETE | `teams.delete` |
| `/api/v1/teams/{id}/members` | POST/DELETE | `teams.manage_members` |
| `/api/v1/roles` | GET | `roles.view` |
| `/api/v1/roles` | POST | `roles.create` |
| `/api/v1/roles/{id}` | PATCH | `roles.update` |
| `/api/v1/roles/{id}` | DELETE | `roles.delete` |
| `/api/v1/roles/{id}/permissions` | PUT | `roles.update` |
| `/api/v1/users/{id}/roles` | PUT | `roles.assign` |
| `/api/v1/permissions` | GET | 認証のみ（マスタ参照） |
| `/api/v1/me/permissions` | GET | 認証のみ（自身の権限確認） |
| `/api/v1/dashboard` | GET | `dashboard.view` |
| `/api/v1/reports/export` | POST | `reports.export` |
| `/api/v1/reports/{id}/status` | GET | `reports.view` または `reports.export` |
| `/api/v1/reports/{id}/download` | GET | `reports.view` または `reports.export` |

### 管理者限定（admin ロール、後方互換）
| エンドポイント | メソッド | 用途 |
|---------------|---------|------|
| `/api/v1/admin/tenants` | POST | テナント作成 |

---

## 4. テナント分離（変更なし）

- 各テナントは独立したPostgreSQLスキーマ（`tenant_{id:03d}`）を持つ
- Row Level Security (RLS) により、テナント間のデータアクセスを完全に防止
- API認証時に自動的にDB接続のsearch_pathを切り替え
- テナントIDはDB上のユーザーレコードから取得（JWTやURLからは受け取らない）
- Phase 1 で追加された roles / leads / teams テーブルにもRLSポリシーを適用

---

## 5. 権限キャッシュ

- Redis に `perms:{tenant_id}:{user_id}` 形式で権限キー集合を5分間キャッシュ
- ロール更新/権限割当変更時は対象テナント全体のキャッシュを一括パージ (`invalidate_tenant_permissions`)
- ユーザーのロール変更時は該当ユーザーのキャッシュのみ削除 (`invalidate_user_permissions`)

---

## 6. インフラアクセス制御（変更なし）

### SSHアクセス
- 鍵認証のみ（パスワード認証無効）
- Fail2Banによるブルートフォース防止
- ポート22のみ許可（UFW）

### データベースアクセス
- 内部ネットワーク（backnet）のみ
- 専用ユーザー（jarvis）、スーパーユーザー使用禁止
- 外部ポート非公開

### Redisアクセス
- パスワード認証必須
- 内部ネットワーク（backnet）のみ

### GitHub
- main/developブランチへの直接コミット禁止
- featureブランチ → PR → レビュー → マージ

---

## 7. 定期レビュー

| 項目 | 頻度 | 実施内容 |
|------|------|---------|
| SSHキー棚卸し | 月次 | 不要なキーの削除 |
| DBユーザー確認 | 月次 | 不要なユーザーの削除 |
| GitHub権限確認 | 月次 | コラボレーター/Deploy Key確認 |
| ロール割り当て確認 | 四半期 | 各ユーザーのロール妥当性確認、priority設計の妥当性確認 |
| 権限マスタ棚卸し | 四半期 | 未使用権限キーの削除、新機能追加時の権限追加漏れ確認 |

# アクセス制御ポリシー - Jarvis CRM

## 1. ロール定義

| ロール | 権限 | 対象者 |
|--------|------|--------|
| admin | テナント管理、ユーザー管理、全CRM操作 | システム管理者 |
| user | CRM操作（顧客・商談・注文の閲覧/編集） | 一般ユーザー |

## 2. APIエンドポイント権限マトリクス

### 認証不要（パブリック）
| エンドポイント | メソッド | 用途 |
|---------------|---------|------|
| `/api/health` | GET | ヘルスチェック |
| `/api/v1/auth/register` | POST | ユーザー登録 |
| `/api/v1/auth/logout` | POST | ログアウト |

### 認証必須（全ロール）
| エンドポイント | メソッド | 用途 |
|---------------|---------|------|
| `/api/v1/customers` | GET/POST/PATCH/DELETE | 顧客管理 |
| `/api/v1/deals` | GET/POST/PATCH/DELETE | 商談管理 |
| `/api/v1/orders` | GET/POST/PATCH/DELETE | 注文管理 |
| `/api/v1/dashboard` | GET | ダッシュボード |
| `/api/v1/reports/export` | POST | レポートエクスポート |
| `/api/v1/reports/{id}/status` | GET | エクスポート状態確認 |
| `/api/v1/reports/{id}/download` | GET | CSVダウンロード |

### 管理者限定（admin）
| エンドポイント | メソッド | 用途 |
|---------------|---------|------|
| `/api/v1/admin/tenants` | POST | テナント作成 |

## 3. テナント分離

- 各テナントは独立したPostgreSQLスキーマ（`tenant_{id:03d}`）を持つ
- Row Level Security (RLS) により、テナント間のデータアクセスを完全に防止
- API認証時に自動的にDB接続のsearch_pathを切り替え
- テナントIDはDB上のユーザーレコードから取得（JWTやURLからは受け取らない）

## 4. インフラアクセス制御

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

## 5. 定期レビュー

| 項目 | 頻度 | 実施内容 |
|------|------|---------|
| SSHキー棚卸し | 月次 | 不要なキーの削除 |
| DBユーザー確認 | 月次 | 不要なユーザーの削除 |
| GitHub権限確認 | 月次 | コラボレーター/Deploy Key確認 |
| ロール割り当て確認 | 四半期 | 各ユーザーのロール妥当性確認 |

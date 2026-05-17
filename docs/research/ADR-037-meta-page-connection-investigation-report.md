# ADR-037 調査レポート: Meta（Facebook/Instagram）ページ接続経路の現状

- **調査日**: 2026-05-17
- **調査者**: Claude Code（Partner）
- **対象 ADR**: `docs/adr/ADR-037-meta-page-connection-investigation.md`
- **調査対象ブランチ**: develop

---

## Codebase Reconnaissance

ADR 本文中の referent を全件抽出し、コードベース実体と突き合わせた結果：

| # | Referent Type | ADR 概念表現 | grep cmd | Hit Count | Top file:line | Action | 最終実体 |
|---|---|---|---|---|---|---|---|
| 1 | ファイル | `meta_graph.py` | `grep -rn "meta_graph" backend/` | 19 files | `backend/app/services/meta_graph.py` | Found | `backend/app/services/meta_graph.py` |
| 2 | 関数 | `list_user_pages()` | `grep -rn "list_user_pages"` | 4 files | `backend/app/services/meta_graph.py:367` | Found | `backend/app/services/meta_graph.py:367` |
| 3 | API パス | `/me/accounts` | `grep -rn "/me/accounts"` | 7 files | `backend/app/services/meta_graph.py:382` | Found | `backend/app/services/meta_graph.py:382` |
| 4 | OAuth scope | `business_management` | `grep -rn "business_management"` | 2 files | `backend/tests/test_meta_oauth_scope.py:68` | **NOT in scope** — テストで明示的に禁止確認済 | `_OAUTH_SCOPE` 定数に不含 |
| 5 | API パス | `/me/businesses` | `grep -rn "/me/businesses"` | **0 hit** | ADR-037 本文のみ | Not Implemented | 実装なし |
| 6 | API パス | `/{business-id}/owned_pages` | `grep -rn "owned_pages"` | **0 hit** | ADR-037 本文のみ | Not Implemented | 実装なし |
| 7 | DB テーブル | `tenant_meta_config` | `grep -rn "tenant_meta_config"` | 41 files | `migrations/040_create_tenant_meta_config.sql` | Found | `migrations/040_create_tenant_meta_config.sql` |
| 8 | DB テーブル | `meta_page_routing` | `grep -rn "meta_page_routing"` | 25 files | `migrations/043_create_meta_page_routing.sql` | Found | `migrations/043_create_meta_page_routing.sql` |
| 9 | OAuth 開始エンドポイント | OAuth 認可 URL 発行 | コード確認 | 1 | `backend/app/routers/meta_inbox.py:283` | Found | `POST /meta/connect/start` |
| 10 | OAuth コールバック | OAuth コールバック受取 | コード確認 | 1 | `backend/app/routers/meta_inbox.py:321` | Found | `GET /meta/connect/callback` |
| 11 | ADR | ADR-024 | ファイル確認 | 1 | `docs/adr/ADR-024_meta_integration_structural_fix.md` | Found | 同左 |
| 12 | ADR | ADR-025 | ファイル確認 | 1 | `docs/adr/ADR-025_meta_integration_operational_hardening.md` | Found | 同左 |
| 13 | ADR | ADR-028 | ファイル確認 | 1 | `docs/adr/ADR-028-screencast-tenant-isolation.md` | Found | 同左 |

0-hit referent: `/me/businesses`（#5）、`/{business-id}/owned_pages`（#6）は **コードベースに存在しない**。これらはまだ実装されていないフォールバック経路の候補であり、ADR-037 が調査依頼している内容そのものである。

---

## 調査項目1: OAuth スコープの現状

### 事実（コードから確認）

**現在 Sales Anchor がリクエストしている OAuth スコープ** (`backend/app/routers/meta_inbox.py:56-63`):

```python
_OAUTH_SCOPE = ",".join([
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_messages",
])
```

合計 **6 permission**。`business_management` は **含まれていない**。

この状態は意図的に設計されている。`backend/tests/test_meta_oauth_scope.py:64-78` に以下のテストが存在する：

```python
def test_oauth_scope_does_not_contain_unrequested_permissions() -> None:
    """過剰申請を防ぐ: business_management、ads_management 等が含まれない。"""
    forbidden = [
        "business_management",
        ...
    ]
    for perm in forbidden:
        assert perm not in scope
```

つまり `business_management` は **設計上、意図的に申請しない permission** として明示的にテストで管理されている。

### OAuth 認可 URL 構築の実体

`backend/app/routers/meta_inbox.py:128-138` の `_build_authorize_url()` で構築される URL のパターン:

```
https://www.facebook.com/v19.0/dialog/oauth
  ?client_id=<META_APP_ID>
  &redirect_uri=<META_OAUTH_REDIRECT_URI>
  &state=<csrf-state>
  &scope=pages_show_list,pages_manage_metadata,pages_messaging,pages_read_engagement,instagram_basic,instagram_manage_messages
  &response_type=code
```

Graph API バージョン: `META_GRAPH_API_VERSION` 環境変数（デフォルト `v19.0`）

---

## 調査項目2: `list_user_pages()` の現状実装

### 事実（コードから確認）

`backend/app/services/meta_graph.py:367-407`:

```python
async def list_user_pages(user_access_token: str, ...) -> list[dict]:
    url = f"{graph_base_url()}/me/accounts"
    body = await _request("GET", url, params={
        "fields": "id,name,access_token,instagram_business_account",
        "access_token": user_access_token,
    })
    data = body.get("data", [])
    ...
```

**実装の特徴**:
- `/me/accounts` エンドポイント **のみ** を使用
- `/me/businesses` や `/{business-id}/owned_pages` へのフォールバックは **一切実装されていない**
- `data` キーが空リスト `[]` の場合、空リストをそのまま返す（例外は投げない）

### 空リスト返却時のエラーハンドリング

`backend/app/routers/meta_inbox.py:401-405`:

```python
if not pages:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="管理可能な Facebook Page が見つかりませんでした。Page を作成して再度お試しください",
    )
```

**問題**: このエラーメッセージは「Page を作成して」と案内しているが、実際の原因が Business Manager 管理ページの `/me/accounts` 不返却である場合は **誤誘導** になる。ユーザーは新しい Page を作るのではなく、接続方法の問題を調査する必要がある。

### `_request()` 内でのエラー処理

Meta から `{"error": {...}}` が返った場合は `MetaGraphAPIError` が発生し、コールバック側でキャッチして HTTP 502 を返す。空リスト（`/me/accounts` が `{"data": []}` を返す）はエラーではなく正常レスポンスとして処理されるため、上記の HTTP 400 パスに到達する。

---

## 調査項目3: 既存テナントの接続状態

### `tenant_meta_config` テーブルのスキーマ

`migrations/040_create_tenant_meta_config.sql` より、各テナントのスキーマ（`{schema}` = `tenant_NNN`）に以下のテーブルが存在する：

| カラム名 | 型 | 用途 |
|---|---|---|
| `id` | SERIAL PK | 内部識別子 |
| `tenant_id` | INTEGER | テナント識別子 |
| `page_id` | VARCHAR(50) | Facebook Page ID |
| `page_name` | VARCHAR(200) | Page 表示名 |
| `page_access_token_encrypted` | BYTEA | Fernet 暗号化済みトークン |
| `page_token_expires_at` | TIMESTAMPTZ | トークン有効期限（約 60 日） |
| `instagram_business_account_id` | VARCHAR(50) | IG Business Account ID（nullable） |
| `instagram_username` | VARCHAR(100) | IG ユーザー名（nullable） |
| `subscribed_fields` | JSONB | subscribe 済みフィールド一覧 |
| `connected_by_staff_id` | INTEGER FK→staff | 接続操作したスタッフ |
| `connected_at` | TIMESTAMPTZ | 接続日時 |
| `last_token_refreshed_at` | TIMESTAMPTZ | 最終リフレッシュ日時 |
| `is_active` | BOOLEAN | 現在アクティブか |
| `deactivated_at` | TIMESTAMPTZ | 非アクティブ化日時 |

**注意**: Business Manager 管理か個人アカウント所有かを示すカラムは存在しない。接続経路の情報は保存されていない。

### `meta_page_routing` テーブルのスキーマ

`migrations/043_create_meta_page_routing.sql` より、`public` スキーマに以下のテーブルが存在する：

| カラム名 | 型 | 用途 |
|---|---|---|
| `tenant_id` | INTEGER | テナント識別子 |
| `config_id` | INTEGER | `tenant_meta_config.id` |
| `schema_name` | TEXT | テナントスキーマ名 |
| `page_id` | VARCHAR(50) | Facebook Page ID（Messenger 逆引き用） |
| `instagram_business_account_id` | VARCHAR(50) | IG Account ID（Instagram 逆引き用） |
| `is_active` | BOOLEAN | アクティブか |
| `updated_at` | TIMESTAMPTZ | 最終更新日時 |

### DB からのテナント別状態（コードベースで確認可能な範囲）

**直接 DB クエリは実施していない**（コードベース外の操作のため）。以下はスキーマ構造から導出できる事実：

- `tenant_006`（ADR-028 で作成された `tenant_review`）で Facebook Page 接続が失敗した場合、`tenant_meta_config` にレコードは存在しないか `is_active=FALSE` の状態になっているはず
- Business Manager 管理ページの場合、OAuth フロー自体は完了するが `list_user_pages()` で空配列が返り、接続が完了しない可能性がある
- `subscribed_fields=NULL` になっているレコードが存在する場合は ADR-024 で問題となった「OAuth フロー外 INSERT」が行われた痕跡

DB の実態確認コマンド（PO 確認時に使用）:
```sql
-- tenant_006 の tenant_meta_config 状態確認
SET search_path TO tenant_006;
SELECT id, page_id, page_name, instagram_business_account_id,
       subscribed_fields, is_active, connected_at, deactivated_at
FROM tenant_meta_config
ORDER BY connected_at DESC;

-- public.meta_page_routing の tenant_006 レコード
SELECT * FROM public.meta_page_routing WHERE tenant_id = 6;

-- audit_logs で接続試行の証跡を確認
SELECT action, created_at, new_data
FROM audit_logs
WHERE action IN ('meta_page_connected', 'oauth_token_exchange_failed')
ORDER BY created_at DESC
LIMIT 20;
```

---

## 調査項目4: 既存 ADR との整合性

### Meta/Facebook 連携に関する既存 ADR 一覧

| ADR | 内容 | 本件への関連 |
|---|---|---|
| **ADR-018** | Instagram Send Endpoint 修正 | `/{page_id}/messages` で IGSID を受取人に渡す設計 |
| **ADR-024** | Meta 連携の構造的不整合の修正 | `subscribed_apps` 未登録・暗号化キー不一致の修正 |
| **ADR-025** | Meta 連携の運用整備強化 | `business_management` 未申請が明示的に設計されていることを背景として理解 |
| **ADR-028** | Meta App Review 撮影用テナント分離 | `tenant_006` = `tenant_review` の文脈を提供 |

### 設計上の制約・決定事項

1. **`business_management` は現在 App Review 申請済みではない**  
   `test_meta_oauth_scope.py` で「申請対象外」として管理されている。追加には Meta App Review の審査範囲拡大が必要。

2. **`/me/accounts` は v17/v18 以降で Business Manager 管理ページを返さない仕様**  
   現実装はこの制約に対して何も対処していない。

3. **ADR-024 の教訓**: 「DB 上は接続済み・Meta 上は未接続」という不整合を発生させないため、OAuth フロー外の DB INSERT は禁止（ADR-025）

4. **ADR-025 の 3 点セット要件**: 外部連携を含む機能には「機能本体 + 検証スクリプト + 監視・通知」が必須

---

## 調査項目5: Claude Code の所見

### 現状の確認

**tenant_006 での接続失敗の直接原因はコードから特定できない**が、以下の 2 シナリオが考えられる：

**シナリオ A: Business Manager 管理ページ問題（構造的）**  
- `HIGH LIFE JPN Test Page` が Business Manager 経由で管理されている場合、`/me/accounts` は v17/v18 以降でこのページを返さない
- 結果: `list_user_pages()` が空配列を返し、HTTP 400「Page が見つかりませんでした」エラーになる
- これは **全 B2B 顧客に発生し得る構造的問題**

**シナリオ B: Business Integration 削除後の一時的問題**  
- ADR-037 の背景に「Business Integration の手動削除」が記載されている
- Meta 側で Business Integration が削除された後、再 OAuth するとスコープが再付与されない場合がある
- この場合は再 OAuth フローで解消できる可能性がある

### フォールバック実装の選択肢と Meta App Review への影響

#### オプション 1: `business_management` 権限を追加してフォールバック経路実装

**実装概要**:
1. `_OAUTH_SCOPE` に `business_management` を追加
2. `list_user_pages()` で `/me/accounts` が空の場合、`/me/businesses` → `/{business-id}/owned_pages` で再取得するフォールバックを実装

**Meta App Review への影響**:
- `business_management` は **Advanced Access が必要な権限**（高い審査ハードル）
- Meta の公式説明: "This permission is designed for advertisers or other businesses that manage multiple Pages"
- B2B SaaS として全顧客に要求するには、Business Manager での複数 Page 管理シナリオの詳細な Use Case 説明が必要
- **撮影シナリオへの影響**: `business_management` を追加してから App Review を通過するまでの間、撮影は実施できない（審査に時間がかかる）
- **リスク**: 6 permission での App Review が通過前に scope 変更すると、審査が最初からやり直しになる可能性がある

**推奨度**: 中（中長期的には必要だが、直近の撮影ブロッカーを解消しない）

#### オプション 2: System User Token 方式

**実装概要**:
- Sales Anchor の Meta アプリを Business Manager に紐付け、System User Token を発行して利用

**Meta App Review への影響**:
- System User Token は **個々のユーザー認証を必要としない**非推奨の方式
- Meta は Standard OAuth Flow を推奨しており、System User Token は B2B SaaS の自社ページ管理向け（Multi-Page Manager 等）
- Sales Anchor が顧客のページに接続する構造では適用が困難
- App Review に提出できる形式でもない

**推奨度**: 低（アーキテクチャ的に不適合）

#### オプション 3: エラーメッセージの改善 + 接続ガイドの提供（最小介入）

**実装概要**:
- 現在の「Page を作成して再度お試しください」を「接続できませんでした。ページが Business Manager で管理されている場合は、Business Manager の設定をご確認ください」に変更
- ヘルプ記事 or FAQ で Business Manager 経由でのページ接続ガイドを用意

**Meta App Review への影響**:
- コードの変更なし → 現在進行中の App Review 審査に影響しない
- 撮影シナリオで Business Manager 管理でないページ（個人所有ページ）を使えば、現状の実装で動作する

**推奨度**: 高（即効性あり、リスクなし）

#### オプション 4: `pages_show_list` + `pages_manage_metadata` の組み合わせで Business Manager ページを取得（v21+ API）

Meta v21.0 以降では一部の Business Manager ページが `pages_show_list` のみで返るよう仕様が緩和されているケースがある（コミュニティレポート）。Graph API バージョンを v21.0 以上にアップグレードしてテストする価値がある。

**Meta App Review への影響**: API バージョン変更は既存 App Review 審査に影響しない。ただし動作保証はない。

**推奨度**: 中（試験的に確認する価値あり）

### 現状コードに対する変更影響範囲の概算

| オプション | 変更ファイル数 | 変更規模 | App Review リスク |
|---|---|---|---|
| 1（`business_management` 追加） | 3-4 | 中（`meta_graph.py`, `meta_inbox.py`, テスト更新） | **高**（審査範囲拡大） |
| 2（System User Token） | 多 | 大（認証フロー全体の再設計） | **高** |
| 3（エラーメッセージ改善） | 1 | 小（`meta_inbox.py` 1 行） | **なし** |
| 4（API バージョンアップ） | 1-2 | 小（`.env` または `meta_graph.py` のデフォルト変更） | **低** |

### 推奨案

**短期（現在の撮影ブロッカー解消）**: オプション 3 + オプション 4 の組み合わせ

1. **即時対応**: エラーメッセージを改善し、Business Manager 管理ページであることを示唆するメッセージに変更
2. **検証**: Graph API バージョンを v21.0 にアップグレードして `tenant_006` での再 OAuth テストを実施
3. **撮影**: Test Page が個人 Facebook アカウントで直接管理されているか確認。個人所有なら現状実装で動作する可能性が高い

**中長期（B2B SaaS としての構造的対応）**: オプション 1 を App Review 通過後の Phase 2 で実装

- App Review 通過後、`business_management` を追加 permission として申請
- `/me/accounts` → `/me/businesses` → `/{business-id}/owned_pages` のフォールバック経路を実装
- B2B 顧客（ほぼ全員が Business Manager 管理ページを持つ）への対応を完成させる

### 推奨案の判断根拠

1. **現在の 6 permission での App Review 審査が進行中**と想定される。`business_management` 追加は審査をリセットするリスクがある（要 PO 確認）
2. **撮影に使う `HIGH LIFE JPN Test Page` の管理形態が不明**。個人所有であれば現状実装で問題ない可能性が高い
3. **エラーメッセージ改善（オプション 3）は実装 1 行でリスクゼロ**。撮影シナリオに影響しない
4. Meta v19.0 は既に `business_management` 非保持で Business Manager ページを返さない確定仕様であるため、API バージョンアップ（オプション 4）の効果は限定的かもしれないが、試す価値はある

---

## 後続 ADR 起案時の論点リスト

以下を次の ADR 起案で明確化することを推奨する：

1. **`HIGH LIFE JPN Test Page` は個人 Facebook アカウント所有か、Business Manager 管理か？**  
   → これが「特殊ケース」か「構造的問題」かの分水嶺

2. **現在 Meta App Review 審査は何 permission で進行中か？**  
   → `business_management` 追加が審査のやり直しに繋がるかどうかの判断基準

3. **Business Integration 削除後の挙動: 再 OAuth で接続は復旧するか？**  
   → Meta 側仕様の確認（コードだけでは判断不能）

4. **`business_management` の App Review 審査要件（Use Case 説明の難易度）**  
   → Advanced Access 取得が現実的かどうか

5. **Graph API v21.0 へのアップグレードの副作用確認**  
   → 既存の webhook 受信・メッセージ送信に破壊的変更がないか

6. **Phase 2 でのフォールバック実装範囲**  
   → `business_management` 経由の追加取得、または個別テナントへの「接続ガイド」提供のどちらを優先するか

---

## 付録: 現状コードの関連実体マップ

```
OAuth フロー:
POST /meta/connect/start
  └─ meta_inbox.py:283
     └─ _build_authorize_url() → Facebook OAuth Dialog
        └─ scope: pages_show_list, pages_manage_metadata, pages_messaging,
                  pages_read_engagement, instagram_basic, instagram_manage_messages
           ※ business_management は含まない

GET /meta/connect/callback
  └─ meta_inbox.py:321
     ├─ exchange_code_for_short_token()  → /oauth/access_token
     ├─ exchange_short_token_for_long_token() → /oauth/access_token
     ├─ list_user_pages() → /me/accounts  ← ここが問題箇所
     │   └─ 空リスト → HTTP 400「Page を作成して再度お試しください」（誤誘導）
     ├─ subscribe_page_to_app() → /{page-id}/subscribed_apps
     └─ _upsert_tenant_meta_config() → tenant_NNN.tenant_meta_config

DB テーブル:
  tenant_NNN.tenant_meta_config  ← per-tenant 接続情報
  public.meta_page_routing       ← Webhook 逆引き（trigger で同期）
```

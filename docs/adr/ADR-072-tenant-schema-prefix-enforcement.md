# ADR-072: tenant schema 修飾の戦略統一（schema prefix と reset_tenant_context のハイブリッド）

## ステータス
Proposed (v2 — Reviewer 指摘 PR #774 反映 2026-05-25)

## 日付
2026-05-25

## コンテキスト

### 連続した同根バグの発生

2026-05-22〜25 にかけて、tenant スキーマ内テーブルに対する raw `text()` SQL
で **schema prefix を付与せず `search_path` に依存している箇所** が広範に
存在することが判明し、3 件連続でバグ／hotfix が発生した:

| 起源 | 対象 | 状態 |
|---|---|---|
| Issue #563 / PR #564 | `tenant_profile.py` の PUT | MERGED 2026-05-24 |
| Issue #565 / PR #757 | `bots.py` / `leads.py` / `deals.py` / `products.py` / `orders.py` / `order_financials.py` | MERGED 2026-05-25 |
| Issue #766 / PR #768 | `order_shipping_details.py` / `order_purchase_details.py` / `order_commissions.py` | MERGED 2026-05-25 |

### 根本原因

SQLAlchemy AsyncSession の `commit()` 後に新コネクションが払い出される
過程で、session-level の `search_path` が失われる可能性がある。raw `text()`
で `FROM bots` のように bare-table 名を書いていると、payload-out の
`UndefinedTableError` を引き起こす（Issue #563 で初観測）。

### 既存メカニズムの存在（v2 で追記、Reviewer 指摘）

ADR-072 v1 起案時に **既存実装の調査が不十分**で見落としていたが、`backend/app/auth/dependencies.py` に既に対応関数が存在する:

```python
# backend/app/auth/dependencies.py:204-243

def _dialect_supports_search_path(db: AsyncSession) -> bool:
    """PostgreSQL 系のみ SET search_path / SET app.tenant_id をサポート。
    SQLite (pytest) では no-op に倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


async def reset_tenant_context(db: AsyncSession, tenant_id: int) -> None:
    """commit() 後にテナントコンテキスト（search_path + app.tenant_id）を再設定する。"""
    if not _dialect_supports_search_path(db):
        return
    safe_id = int(tenant_id)
    schema_name = f"tenant_{safe_id:03d}"
    await db.execute(text(f"SET search_path = {schema_name}, public"))
    await db.execute(text(f"SET app.tenant_id = '{safe_id}'"))
```

**残 13 router の grep 結果（origin/develop HEAD で確認）**:

| status | router (8) |
|---|---|
| `reset_tenant_context()` を呼んでいる | `contacts.py` / `meta_inbox.py` / `teams.py` / `archives.py` / `quotes.py` / `invoices.py` / `companies.py` / `customers.py` |
| 呼んでいない | `staff.py` / `suppliers.py` / `dashboard.py` / `roles.py` / `shifts.py` |

つまり 13 router のうち **8 / 13 は既に案 B (reset_tenant_context) のパターンを採用済**。残 5 router が呼び忘れている状態。

PR #564 / #757 / #768 で 9 router (tenant_profile + 6 + 3) を **案 A (schema prefix 明示)** で修正してきたのは、`reset_tenant_context` の存在を知らずに別パターンを発展させた経緯。

### 設計選択肢

| 案 | 内容 | メリット | デメリット |
|---|---|---|---|
| **A. schema prefix 明示**（v1 提案、PR #564/#757/#768 既採用） | raw SQL で `tenant_{id:03d}.{name}` 形式を必ず書く | search_path 依存ゼロ、commit タイミング不問、root cause 消滅 | 70+ 箇所の SQL 書き換え、可読性低下、新規開発負荷 |
| **B. reset_tenant_context 強制**（既存 8 router 採用） | commit 後に必ず `await reset_tenant_context(db, tenant_id)` を呼ぶ | SQL は bare-table のまま、変更量小 | 呼び忘れリスク常時、lint で検出しにくい、context propagation の責務分散 |
| **C. ハイブリッド（v2 で採択）** | 既存 9 router (PR #564/#757/#768) は **案 A 維持**、残 13 router は **案 B 統一** (5 router に reset_tenant_context 追加) | 既存修正を捨てない、最小コストで全 router カバー、CI lint で両方検証可 | router 内のパターンが二分される、新規 router の選択基準が必要 |

## 決定

### 1. ハイブリッド戦略採用（案 C）

- **既に schema prefix 化済の 9 router** (tenant_profile / bots / leads / deals / products / orders / order_financials / order_shipping_details / order_purchase_details / order_commissions) は **案 A を維持**。これらを案 B に revert しない（PR #564/#757/#768 の投資を保全）。
- **残 5 router** (`staff.py` / `suppliers.py` / `dashboard.py` / `roles.py` / `shifts.py`) に `reset_tenant_context()` 呼び出しを **追加**して案 B に統一。
- **既に reset_tenant_context() を呼んでいる 8 router** (contacts / meta_inbox / teams / archives / quotes / invoices / companies / customers) は現状維持。

### 2. 新規 router の判断基準

- **デフォルト**: 案 B (`reset_tenant_context()` を `await db.commit()` 直後に呼ぶ)。コード量が少なく既存メカニズムを再利用できる。
- **例外（案 A 採用）**: tenant スキーマと public スキーマを同一クエリで JOIN する必要がある router（例: `inventory_search.py`）は案 A で schema prefix を明示する。

### 3. helper 共通化（Major 2 反映、v1 の方針見直し）

v1 で提案した `app/db/tenant_schema.py` 新設は**取り下げる**。`is_postgresql` の実装は `app/auth/dependencies.py:_dialect_supports_search_path` と byte-equivalent で重複の上塗りになるため。

代わりに以下を実施:

- **既存 10 ローカル helper** (PR #564 / #757 / #768 で追加した `_is_postgresql` / `_t`) を **`app/auth/dependencies.py` から再 export** して統合する
- export 名: `tenant_table_ref(db, tenant_id, name)` / `is_postgresql(db)` （public API として）
- 既存 10 ファイル内の `_is_postgresql` / `_t` を削除し、`from app.auth.dependencies import tenant_table_ref, is_postgresql` に置換
- 新規 export は `_dialect_supports_search_path` をラップする実装にし、二重実装を避ける

### 4. CI linter で両パターンを検証

`.github/workflows/lint.yml` 等に静的解析ジョブを追加し、`backend/app/routers/` 配下で以下のいずれかを検出して fail させる:

1. **案 A 違反**: tenant 内テーブル名が `text(...)` 内に bare-table で出現し、**かつ** 同 endpoint が `reset_tenant_context()` を呼ばない
2. **案 B 違反**: write 系 endpoint (`POST` / `PUT` / `PATCH` / `DELETE`) で `await db.commit()` を呼んでいるのに、その後 `reset_tenant_context()` を呼ばない

PoC は `grep` / `ripgrep` ベースの shell スクリプトで開始する（false positive 率 < 5% を目標）。将来は `ast` 解析で `sqlalchemy.text(...)` 引数の文字列解析、および endpoint 関数の AST 走査によるカスタム linter ルールへ昇格。

### 5. 段階的移行計画（v2 改訂）

| Phase | 内容 | 目安 | 依存 |
|---|---|---|---|
| **Phase 0** | ADR-072 (v2) 起案 + 総括 Issue #773 で 13 router をチェックボックス化 | 本 PR | - |
| **Phase 1** | `app/auth/dependencies.py` に公開 helper (`tenant_table_ref` / `is_postgresql`) を追加、既存ローカル helper 10 ファイルを置換（pure refactor） | 1 PR | Phase 0 |
| **Phase 2** | 残 5 router (`staff.py` / `suppliers.py` / `dashboard.py` / `roles.py` / `shifts.py`) に `reset_tenant_context()` を追加 | 1-2 PR | Phase 1 |
| **Phase 3** | CI linter PoC を追加（initial は warning のみ） | 1 PR | Phase 2 |
| **Phase 4** | linter を CI lint ジョブの required check に昇格 | 1 PR | Phase 3 |

各 Phase は ADR-056 の Merge stage = develop（Claude merge）で進める。

## 結果

### 影響範囲

- `backend/app/auth/dependencies.py` に公開 helper 追加 (Phase 1)
- `backend/app/routers/` 配下の 10 ファイルでローカル helper を統合（Phase 1, pure refactor）
- 残 5 router に `reset_tenant_context()` 追加（Phase 2）
- `.github/workflows/lint.yml` 等に lint ジョブ追加（Phase 3, 4）

**v1 と比較した変更量**:
- v1: 13 router × 70 箇所の SQL 書き換え
- v2: 10 ファイルの import 文置換 + 5 router の 1 行追加 + lint ジョブ追加

→ **コードベース変更量を 1/5 以下に削減**。

### 期待される効果

- `UndefinedTableError` の予防（Phase 1-2 で残 router をカバー、case A/B 両方 lint で物理 block）
- helper 重複の解消（10 ファイル → 1 ファイル）
- 新規 router 追加時の同種バグを CI で物理 block
- 既存 PR #564/#757/#768 の投資保全

### リスク

- ハイブリッド戦略のため、router 内のパターンが二分される（**新規開発者の混乱を招く可能性** → §2 の判断基準で軽減）
- `reset_tenant_context()` 呼び忘れの検出が lint だけでは false negative が出る可能性（write endpoint の判定ロジック）
- 既存 8 router (contacts 等) の `reset_tenant_context` 呼び出し位置に不整合があるかを Phase 2 着手前に再確認すべき

### Open question

- Phase 1 で `tenant_table_ref` / `is_postgresql` を `app/auth/dependencies.py` から export する API 名でいいか、別 module に分けるか（例: `app/db/__init__.py`）
- Phase 3 の linter false positive 数値目標（5% は妥当か）
- `inventory_search.py` の例外扱いを ADR 本文で明示するか、別 README で扱うか

## 関連

- Issue #563 / PR #564 (tenant_profile.py、起源)
- Issue #565 / PR #757 (6 router、第一弾、案 A)
- Issue #766 / PR #768 (3 router、第二弾、案 A)
- Issue #773 (tracker, 残 13 router のチェックボックス管理)
- PR #774 (本 ADR、v1 → v2 改訂)
- ADR-056 (merge ポリシー二段構え、本 ADR の段階移行と整合)
- ADR-065 (asyncpg prepared statement cache 無効化、context propagation 系の先例)
- memory: `feedback-pr-merge-stage-explicit`（PR 起案時のステージ明示ルール）

## 変更履歴

- **v1** (2026-05-25): 案 A 一択で起案。`app/db/tenant_schema.py` 新設提案。
- **v2** (2026-05-25): Reviewer (PR #774) 指摘 Major 1 / Major 2 を反映。既存 `reset_tenant_context()` / `_dialect_supports_search_path` の発見を踏まえ、案 C (ハイブリッド) に方針変更。helper 共通化先を `app/auth/dependencies.py` に変更。Phase 計画を全面改訂。

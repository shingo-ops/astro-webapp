# ADR-072: tenant schema prefix の義務化と helper 共通化

## ステータス
Proposed

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

### 残存範囲

PR #768 マージ後の `origin/develop` で `grep` した結果、**追加 13 router
の合計 ~70 箇所** に同種の bare-table が残存している:

| router | 残存箇所 |
|---|---|
| `companies.py` | 13 |
| `contacts.py` | 12 |
| `invoices.py` | 9 |
| `quotes.py` | 8 |
| `customers.py` | 6 |
| `staff.py` | 5 |
| `suppliers.py` | 5 |
| `dashboard.py` | 3 |
| `roles.py` | 3 |
| `shifts.py` | 2 |
| `archives.py` | 2 |
| `meta_inbox.py` | 1 |
| `teams.py` | 1 |

これらは connection pool stickiness で偶然動いている状態であり、本番運用
タイミングで `UndefinedTableError` が顕在化するリスクが残る。

### 既存 helper の重複問題

PR #564 / #757 / #768 では各 router ファイル内に `_is_postgresql` /
`_t(db, tenant_id, name)` のローカルヘルパーを byte-equivalent なコピーで
追加してきた（現在 10 ファイル）。今後 13 router 修正で 23 ファイルに
増えると保守性が損なわれる。

## 決定

### 1. tenant スキーマ修飾の義務化

全 router の raw `text()` SQL で tenant スキーマ内テーブルを参照する場合、
**PostgreSQL では `tenant_{id:03d}.{name}` 形式の schema prefix を必須**
とする。`search_path` 依存は禁止。

公式テーブル参照ヘルパー経由でのみ修飾名を取得すること。

### 2. helper 共通化

`backend/app/db/tenant_schema.py`（新規）に以下を集約:

```python
from sqlalchemy.ext.asyncio import AsyncSession


def is_postgresql(db: AsyncSession) -> bool:
    """db の dialect が PostgreSQL 系か判定する。

    pytest は SQLite (aiosqlite) で実行されるため、schema prefix を入れると
    "no such table: tenant_NNN.<table>" で失敗する。本判定で SQLite 系を
    検出して prefix なしに倒す。
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    if bind is None:
        bind = getattr(db, "bind", None)
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.startswith("postgresql")


def t(db: AsyncSession, tenant_id: int, name: str) -> str:
    """tenant スキーマ修飾テーブル参照を返す。

    - PostgreSQL: `tenant_{id:03d}.{name}` (schema prefix 明示)
    - SQLite (pytest): `{name}` (schema 概念なし)

    AsyncSession の commit 後は新コネクションが払い出されて session-level
    の search_path が失われる可能性があるため、raw text() を使う箇所では
    schema prefix を明示するのが安全 (ADR-072 / Issue #563 / #565 / #766)。
    """
    if is_postgresql(db):
        safe_id = int(tenant_id)
        return f"tenant_{safe_id:03d}.{name}"
    return name
```

呼び出し側は:

```python
from app.db.tenant_schema import t

bots_t = t(db, tenant_id, "bots")
result = await db.execute(text(f"SELECT ... FROM {bots_t} WHERE ..."))
```

既存の各 router ローカルヘルパー（PR #564 / #757 / #768 で追加）は段階的
に共通実装へ移行する。public スキーマ参照（`public.products` 等）は対象外。

### 3. CI linter で残存検出

`.github/workflows/lint.yml` 等に静的解析ジョブを追加し、`backend/app/routers/`
配下で「`text(...)` 内に tenant スキーマ内テーブル名が prefix なしで出現」
を検出して fail させる。

PoC: grep / ripgrep ベースの shell スクリプト。tenant スキーマ内テーブル
リストは migration 由来で抽出する（または allowlist で管理）。

将来的には `ast` 解析で `sqlalchemy.text(...)` の引数文字列を解析する
カスタム linter ルールへ昇格させる。

### 4. 段階的移行計画

| Phase | 内容 | 目安 |
|---|---|---|
| Phase 0 | ADR-072 起案 + 総括 Issue で 13 router をチェックボックス化 | 本 ADR |
| Phase 1 | `app/db/tenant_schema.py` 新規作成 + linter PoC | 1 PR |
| Phase 2 | 残 13 router の hotfix（規模順に 2-4 PR に分割） | 2-3 PR |
| Phase 3 | 既存 10 ローカル helper を共通実装に統合（純粋 refactor） | 1 PR |
| Phase 4 | linter を CI lint ジョブの required check に昇格 | 1 PR |

各 Phase は ADR-056 の Merge stage = develop（Claude merge）で進める。

## 結果

### 影響範囲

- backend/app/routers/ 配下の追加 13 router を修正対象
- backend/app/db/tenant_schema.py 新規追加
- backend/tests/ に共通 helper の単体テスト追加
- .github/workflows/ に lint ジョブ追加

### 期待される効果

- `UndefinedTableError` の予防（Phase 移行で本番運用前にゼロ化）
- helper 重複の解消（10 ファイル → 1 ファイル）
- 新規 router 追加時の同種バグを CI で物理 block

### リスク

- 13 router × 70 箇所の修正は機械的だが、`order_commissions.py` のように
  内部 helper シグネチャ変更を伴うファイルもある。各 PR で慎重に確認。
- 既存テスト（SQLite モック）でカバーされていない経路は本番投入後に
  顕在化する可能性。`tenant-review` (tenant_006) での smoke 検証必須。

## 関連

- Issue #563 / PR #564 (tenant_profile.py、起源)
- Issue #565 / PR #757 (6 router、第一弾)
- Issue #766 / PR #768 (3 router、第二弾)
- ADR-056 (merge ポリシー二段構え、本 ADR の段階移行と整合)
- Issue #773 (tracker, 残 13 router のチェックボックス管理)
- memory: `feedback-pr-merge-stage-explicit`（PR 起案時のステージ明示ルール）

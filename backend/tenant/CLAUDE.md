# backend/tenant — テナント操作ルール（ADR-072）

`backend/CLAUDE.md` の詳細ページ。`backend/app/routers/` 配下の write エンドポイント実装時に参照。

---

## write エンドポイント実装チェックリスト

`@router.post|put|patch|delete` を実装するたびに全て確認すること:

- [ ] `await db.commit()` の**直後**に `await reset_tenant_context(db, tenant_id)` を呼ぶ
- [ ] インポート: `from app.database import reset_tenant_context`
- [ ] commit が複数ある場合は、**各 commit の直後**にそれぞれ呼ぶ（1対1対応）
- [ ] `tenant_id` は `Depends(get_current_tenant)` 経由で受け取っているか

違反は **pre-commit フック**と **CI（lint-tenant-schema.yml）** が自動検出して FAIL させる。
ローカルでも確認: `python3 scripts/lint_tenant_schema.py --mode strict backend/app/routers/`

---

## なぜ必要か

`db.commit()` でデータが保存されると、PostgreSQL の `search_path` がデフォルトに戻る。
`reset_tenant_context()` を呼ばないと、**次のクエリが別テナントのデータを参照してしまう**（データ漏洩リスク）。

---

## 実装例

```python
@router.post("/items")
async def create_item(
    data: ItemCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant),
):
    db.add(Item(**data.dict(), tenant_id=tenant_id))
    await db.commit()
    await reset_tenant_context(db, tenant_id)  # ← 必須
    return {"ok": True}
```

---

## 過去の再発事例

| 日付 | ファイル | 関数名 |
|------|---------|--------|
| 2026-06-02 | `discord_ticket_config.py` | deploy-button endpoint |
| 2026-06-02 | `discord_announcement.py` | `post_announcement` |

---

## 関連リンク

- linter: `scripts/lint_tenant_schema.py`
- ADR: `docs/adr/ADR-072-tenant-schema-prefix-enforcement.md`

"""Phase 1-B-2 Step 5d / PR γ スモークテスト。

PR γ（最終クリーンアップ）の差分を schema レベル + grep レベルで確認する。
実 pytest baseline は別件 (app.auth.dependencies AttributeError) で実行不可のため、
Pydantic schemas / 静的 grep / ファイル存在確認のみで局所検証する。

検証項目:
  1. *Response.contact_id が int 必須化されている (deal/order/quote/invoice)
  2. customer_resolver.py が削除されている
  3. tenant.py から _customer_migration_map への参照（コード行）が消えている
  4. tenant.py の deals/orders/quotes/invoices CREATE TABLE から customer_id 列が消えている
  5. data_migration の使い切りスクリプトが archive 配下に移動している
  6. .github/workflows/ 直下に dangling な Phase 1-B-2 step3/step4 workflow が残っていない
  7. deploy.yml に migration 036 の実行ブロックが入っている
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# 1. *Response.contact_id が int 必須
# -----------------------------------------------------------------------------
def test_deal_response_contact_id_is_required_int():
    from app.schemas.deal import DealResponse

    field = DealResponse.model_fields["contact_id"]
    assert field.annotation is int, f"DealResponse.contact_id annotation: {field.annotation}"
    assert field.is_required(), "DealResponse.contact_id must be required"


def test_order_response_contact_id_is_required_int():
    from app.schemas.order import OrderResponse

    field = OrderResponse.model_fields["contact_id"]
    assert field.annotation is int
    assert field.is_required()


def test_quote_response_contact_id_is_required_int():
    from app.schemas.quote import QuoteResponse

    field = QuoteResponse.model_fields["contact_id"]
    assert field.annotation is int
    assert field.is_required()


def test_invoice_response_contact_id_is_required_int():
    from app.schemas.invoice import InvoiceResponse

    field = InvoiceResponse.model_fields["contact_id"]
    assert field.annotation is int
    assert field.is_required()


def test_response_rejects_none_contact_id():
    """None を渡すと ValidationError になることを確認（int 必須化の効果）"""
    from pydantic import ValidationError

    from app.schemas.deal import DealResponse

    try:
        DealResponse(
            id=1,
            deal_code="D-001",
            company_id=10,
            contact_id=None,  # type: ignore[arg-type]
            lead_id=None,
            title="t",
            amount=None,
            currency="JPY",
            status="open",
            stage=None,
            probability=None,
            lost_reason=None,
            assigned_to=None,
            expected_close_date=None,
            notes=None,
            created_at="2026-04-27T00:00:00+00:00",  # type: ignore[arg-type]
            updated_at="2026-04-27T00:00:00+00:00",  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        assert any("contact_id" in str(e["loc"]) for e in exc.errors())
    else:
        raise AssertionError("DealResponse(contact_id=None) should raise ValidationError")


# -----------------------------------------------------------------------------
# 2. customer_resolver.py が削除済
# -----------------------------------------------------------------------------
def test_customer_resolver_module_deleted():
    path = REPO_ROOT / "backend" / "app" / "services" / "customer_resolver.py"
    assert not path.exists(), f"customer_resolver.py should be deleted but exists: {path}"


def test_no_import_of_customer_resolver_in_backend():
    backend_app = REPO_ROOT / "backend" / "app"
    pat = re.compile(r"from\s+app\.services\.customer_resolver|import\s+customer_resolver")
    offenders: list[str] = []
    for py in backend_app.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if pat.search(text):
            offenders.append(str(py.relative_to(REPO_ROOT)))
    assert not offenders, f"customer_resolver imports should be 0 but: {offenders}"


# -----------------------------------------------------------------------------
# 3. tenant.py から _customer_migration_map への live 参照が消滅
# -----------------------------------------------------------------------------
def test_tenant_py_has_no_live_customer_migration_map_reference():
    path = REPO_ROOT / "backend" / "app" / "services" / "tenant.py"
    src = path.read_text(encoding="utf-8")
    # コメント行を除去（先頭が `--` または `#` のもの）
    code_lines = []
    for ln in src.split("\n"):
        stripped = ln.strip()
        if stripped.startswith("--"):
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(ln)
    code = "\n".join(code_lines)
    assert "_customer_migration_map" not in code, (
        "tenant.py のコード行に _customer_migration_map への参照が残っています"
    )


# -----------------------------------------------------------------------------
# 4. tenant.py の deals/orders/quotes/invoices CREATE TABLE に customer_id が無い
# -----------------------------------------------------------------------------
def test_tenant_py_downstream_tables_have_no_customer_id_column():
    path = REPO_ROOT / "backend" / "app" / "services" / "tenant.py"
    src = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"CREATE TABLE IF NOT EXISTS \{schema\}\.(deals|orders|quotes|invoices) \((.*?)\n\);",
        re.DOTALL,
    )
    for m in pattern.finditer(src):
        table = m.group(1)
        body = m.group(2)
        # SQL コメント行（`--`）を除去
        code = "\n".join(
            ln for ln in body.split("\n") if not ln.strip().startswith("--")
        )
        assert not re.search(r"\bcustomer_id\b", code), (
            f"tenant.py の CREATE TABLE {table} に customer_id 列が残っています:\n{code}"
        )


# -----------------------------------------------------------------------------
# 5. data_migration 使い切りスクリプトが archive 化済
# -----------------------------------------------------------------------------
def test_data_migration_archived_files_moved():
    archived = [
        "scripts/_archive/data_migration/migrate_companies_contacts_from_customers.py",
        "scripts/_archive/data_migration/verify_companies_contacts_migration.py",
        "scripts/_archive/data_migration/verify_downstream_fk_migration.py",
        "scripts/_archive/data_migration/migrate_customers_from_sheet.py",
        "scripts/_archive/data_migration/verify_customers_migration.py",
    ]
    for rel in archived:
        assert (REPO_ROOT / rel).exists(), f"missing archived file: {rel}"

    not_at_old_path = [
        "scripts/data_migration/migrate_companies_contacts_from_customers.py",
        "scripts/data_migration/verify_companies_contacts_migration.py",
        "scripts/data_migration/verify_downstream_fk_migration.py",
        "scripts/data_migration/migrate_customers_from_sheet.py",
        "scripts/data_migration/verify_customers_migration.py",
    ]
    for rel in not_at_old_path:
        assert not (REPO_ROOT / rel).exists(), (
            f"file should be archived but still at old path: {rel}"
        )


def test_archived_workflows_removed_from_actions_dir():
    """`.github/workflows/` 直下に archive 対象 workflow が dangling 残置していない。"""
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    direct = {p.name for p in workflows_dir.iterdir() if p.is_file()}
    assert "run-phase1-b2-step3-migration.yml" not in direct
    assert "verify-phase1-b2-step4-migration.yml" not in direct

    # archive 配下に移動済を再確認
    archive_dir = workflows_dir / "_archive"
    assert (archive_dir / "run-phase1-b2-step3-migration.yml").exists()
    assert (archive_dir / "verify-phase1-b2-step4-migration.yml").exists()


# -----------------------------------------------------------------------------
# 6. deploy.yml に migration 036 が登録済
# -----------------------------------------------------------------------------
def test_deploy_yml_invokes_migration_036():
    path = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
    src = path.read_text(encoding="utf-8")
    assert "migrations/036_drop_customer_migration_map.sql" in src, (
        "deploy.yml に migration 036 の psql 実行ブロックが見つかりません"
    )
    # 035 → 036 の順序確認
    idx_035 = src.find("migrations/035_")
    idx_036 = src.find("migrations/036_")
    assert idx_035 != -1 and idx_036 != -1
    assert idx_035 < idx_036, "deploy.yml で 036 は 035 より後に実行されるべき"

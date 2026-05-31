"""ADR-021 Phase 5 / Sprint 5 — 担当者報酬計算 MVP のテスト。

検証範囲（spec.md AC-5.1〜5.11）:
  1) 計算ロジック (services.commission_calculator.calculate)
     - 5 ロール各々の現行 OrderFlow 式忠実再現
       * 営業 / 受注 / 発送 → キャンセル時 0
       * 仕入 / トラブル    → キャンセル判定なし
       * 全ロール → 未割当時 0、is_employee 時 0
       * sales / order = rate (commission_base_amount × value)
       * ship / purchase / trouble = fixed (value そのまま)
  2) tenant_commission_settings get-or-create + PATCH
  3) /orders/{id}/commissions/assign UPSERT
  4) /orders/{id}/commissions/recalc 全ロール再計算
  5) /orders/{id}/commissions GET（5 ロール一覧、未登録 null）
  6) /commissions/monthly?year=&month= by_staff / by_role / total
  7) マルチテナント分離（権限 require_permission チェック）

SQLite 互換のため tenant_commission_settings.commission_rates は TEXT に JSON 文字列、
NOW() は test_engine の create_function でモック値が返る前提で書く。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.tenant_commission_settings import (
    DEFAULT_COMMISSION_RATES,
    CommissionRate,
    CommissionRatesConfig,
)
from app.services.commission_calculator import (
    FinancialSnapshot,
    StaffSnapshot,
    calculate,
    calculate_all,
)


# ---------------------------------------------------------------------------
# 1. 計算ロジック単体（純関数）
# ---------------------------------------------------------------------------


class TestCalculateLogic:
    """spec.md の 5 ロール表を 1:1 でなぞるテスト。

    - rates はデフォルト（営業/受注 10% rate / 発送 200 fixed / 仕入 100 fixed / トラブル 500 fixed）
    - financial.commission_base_amount = 10000 で営業/受注は 1000 円になる前提
    """

    def setup_method(self):
        self.rates = DEFAULT_COMMISSION_RATES
        self.fin = FinancialSnapshot(commission_base_amount=Decimal("10000"))
        self.regular_staff = StaffSnapshot(id=1, is_employee=False)
        self.employee = StaffSnapshot(id=2, is_employee=True)

    # --- 未割当時 0（全ロール共通）---
    @pytest.mark.parametrize("role", ["sales", "order", "ship", "purchase", "trouble"])
    def test_unassigned_returns_zero(self, role):
        result = calculate(
            order_status="pending",
            financial=self.fin,
            rates=self.rates,
            role=role,
            staff=None,
        )
        assert result == Decimal("0.00")

    # --- is_employee=True → 0（全ロール共通）---
    @pytest.mark.parametrize("role", ["sales", "order", "ship", "purchase", "trouble"])
    def test_is_employee_returns_zero(self, role):
        result = calculate(
            order_status="pending",
            financial=self.fin,
            rates=self.rates,
            role=role,
            staff=self.employee,
        )
        assert result == Decimal("0.00")

    # --- 営業 / 受注 / 発送 → キャンセル時 0 ---
    @pytest.mark.parametrize("role", ["sales", "order", "ship"])
    def test_cancelled_returns_zero_for_sales_order_ship(self, role):
        result = calculate(
            order_status="cancelled",
            financial=self.fin,
            rates=self.rates,
            role=role,
            staff=self.regular_staff,
        )
        assert result == Decimal("0.00")

    # --- 仕入 / トラブル → キャンセル判定なし（キャンセルでも支払う）---
    def test_cancelled_purchase_still_pays_fixed(self):
        result = calculate(
            order_status="cancelled",
            financial=self.fin,
            rates=self.rates,
            role="purchase",
            staff=self.regular_staff,
        )
        # 仕入は 100 円固定、キャンセル判定対象外
        assert result == Decimal("100.00")

    def test_cancelled_trouble_still_pays_fixed(self):
        result = calculate(
            order_status="cancelled",
            financial=self.fin,
            rates=self.rates,
            role="trouble",
            staff=self.regular_staff,
        )
        # トラブルは 500 円固定、キャンセル判定対象外
        assert result == Decimal("500.00")

    # --- 通常時の rate 計算（営業/受注は売上 × 10%）---
    @pytest.mark.parametrize("role,expected", [("sales", "1000.00"), ("order", "1000.00")])
    def test_rate_role_uses_commission_base_amount(self, role, expected):
        result = calculate(
            order_status="pending",
            financial=self.fin,
            rates=self.rates,
            role=role,
            staff=self.regular_staff,
        )
        assert result == Decimal(expected)

    # --- rate ロールで financial 未登録 → 0 ---
    @pytest.mark.parametrize("role", ["sales", "order"])
    def test_rate_role_returns_zero_when_financial_missing(self, role):
        result = calculate(
            order_status="pending",
            financial=None,
            rates=self.rates,
            role=role,
            staff=self.regular_staff,
        )
        assert result == Decimal("0.00")

    # --- fixed ロールは financial 未登録でも value を返す ---
    @pytest.mark.parametrize(
        "role,expected",
        [("ship", "200.00"), ("purchase", "100.00"), ("trouble", "500.00")],
    )
    def test_fixed_role_returns_value_even_without_financial(self, role, expected):
        result = calculate(
            order_status="pending",
            financial=None,
            rates=self.rates,
            role=role,
            staff=self.regular_staff,
        )
        assert result == Decimal(expected)

    # --- カスタム rate を反映した計算（テナント別 rate カスタマイズ AC）---
    def test_custom_rate_overrides_default(self):
        custom = CommissionRatesConfig(
            sales=CommissionRate(type="rate", value=Decimal("0.20")),  # 20%
            order=CommissionRate(type="rate", value=Decimal("0.05")),  # 5%
            ship=CommissionRate(type="fixed", value=Decimal("300")),
            purchase=CommissionRate(type="fixed", value=Decimal("150")),
            trouble=CommissionRate(type="fixed", value=Decimal("750")),
        )
        # 売上 10000 × 20% = 2000
        assert calculate(
            order_status="pending",
            financial=self.fin,
            rates=custom,
            role="sales",
            staff=self.regular_staff,
        ) == Decimal("2000.00")
        # 売上 10000 × 5% = 500
        assert calculate(
            order_status="pending",
            financial=self.fin,
            rates=custom,
            role="order",
            staff=self.regular_staff,
        ) == Decimal("500.00")
        # ship 300 / purchase 150 / trouble 750
        assert calculate(
            order_status="pending",
            financial=self.fin,
            rates=custom,
            role="ship",
            staff=self.regular_staff,
        ) == Decimal("300.00")
        assert calculate(
            order_status="pending",
            financial=self.fin,
            rates=custom,
            role="purchase",
            staff=self.regular_staff,
        ) == Decimal("150.00")
        assert calculate(
            order_status="pending",
            financial=self.fin,
            rates=custom,
            role="trouble",
            staff=self.regular_staff,
        ) == Decimal("750.00")

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError):
            calculate(
                order_status="pending",
                financial=self.fin,
                rates=self.rates,
                role="unknown_role",
                staff=self.regular_staff,
            )

    def test_calculate_all_returns_5_roles(self):
        out = calculate_all(
            order_status="pending",
            financial=self.fin,
            rates=self.rates,
            staff_by_role={
                "sales": self.regular_staff,
                "order": self.regular_staff,
                "ship": self.regular_staff,
                "purchase": self.regular_staff,
                "trouble": self.regular_staff,
            },
        )
        assert set(out.keys()) == {"sales", "order", "ship", "purchase", "trouble"}
        assert out["sales"] == Decimal("1000.00")
        assert out["order"] == Decimal("1000.00")
        assert out["ship"] == Decimal("200.00")
        assert out["purchase"] == Decimal("100.00")
        assert out["trouble"] == Decimal("500.00")

    def test_calculate_all_cancelled_only_zeroes_three_roles(self):
        """キャンセル時 0 適用範囲が営業/受注/発送のみ・仕入/トラブルは支払う"""
        out = calculate_all(
            order_status="cancelled",
            financial=self.fin,
            rates=self.rates,
            staff_by_role={
                "sales": self.regular_staff,
                "order": self.regular_staff,
                "ship": self.regular_staff,
                "purchase": self.regular_staff,
                "trouble": self.regular_staff,
            },
        )
        assert out["sales"] == Decimal("0.00")
        assert out["order"] == Decimal("0.00")
        assert out["ship"] == Decimal("0.00")
        assert out["purchase"] == Decimal("100.00")
        assert out["trouble"] == Decimal("500.00")


# ---------------------------------------------------------------------------
# 2. /tenant-commission-settings (get-or-create + PATCH)
# ---------------------------------------------------------------------------


class TestTenantCommissionSettings:
    async def test_get_returns_default_idempotent(self, client):
        """初回 GET で default 設定を作って返す（idempotent）"""
        res1 = await client.get("/api/v1/tenant-commission-settings")
        assert res1.status_code == 200, res1.text
        body1 = res1.json()
        assert body1["tenant_id"] == 999
        # default rate
        assert body1["commission_rates"]["sales"]["type"] == "rate"
        assert float(body1["commission_rates"]["sales"]["value"]) == 0.10
        assert body1["commission_rates"]["ship"]["type"] == "fixed"
        assert float(body1["commission_rates"]["ship"]["value"]) == 200
        first_id = body1["id"]

        # 二回目も同じ id（idempotent）
        res2 = await client.get("/api/v1/tenant-commission-settings")
        assert res2.status_code == 200
        assert res2.json()["id"] == first_id

    async def test_patch_updates_rates(self, client):
        """PATCH で rate を変更できる"""
        # まず default 作成
        await client.get("/api/v1/tenant-commission-settings")
        new_rates = {
            "commission_rates": {
                "sales": {"type": "rate", "value": 0.15},
                "order": {"type": "rate", "value": 0.08},
                "ship": {"type": "fixed", "value": 250},
                "purchase": {"type": "fixed", "value": 120},
                "trouble": {"type": "fixed", "value": 600},
            }
        }
        res = await client.patch("/api/v1/tenant-commission-settings", json=new_rates)
        assert res.status_code == 200, res.text
        body = res.json()
        assert float(body["commission_rates"]["sales"]["value"]) == 0.15
        assert float(body["commission_rates"]["ship"]["value"]) == 250

        # GET で更新後を確認
        get_res = await client.get("/api/v1/tenant-commission-settings")
        assert get_res.status_code == 200
        assert float(get_res.json()["commission_rates"]["sales"]["value"]) == 0.15

    async def test_patch_creates_if_missing(self, client):
        """既存設定が無い状態でいきなり PATCH しても作成される"""
        new_rates = {
            "commission_rates": {
                "sales": {"type": "rate", "value": 0.20},
                "order": {"type": "rate", "value": 0.20},
                "ship": {"type": "fixed", "value": 300},
                "purchase": {"type": "fixed", "value": 200},
                "trouble": {"type": "fixed", "value": 800},
            }
        }
        res = await client.patch("/api/v1/tenant-commission-settings", json=new_rates)
        assert res.status_code == 200, res.text
        assert float(res.json()["commission_rates"]["sales"]["value"]) == 0.20


# ---------------------------------------------------------------------------
# 3. assign / recalc / get / monthly のエンドポイント統合テスト
#
# orders / staff / order_financials を SQLite 上に作って実 API 経路で叩く。
# ---------------------------------------------------------------------------


async def _create_company_contact(client, name="報酬テスト"):
    co = await client.post("/api/v1/companies", json={"name": name})
    assert co.status_code == 201, co.text
    company_id = co.json()["id"]
    ct = await client.post("/api/v1/contacts", json={
        "company_id": company_id,
        "display_name": f"{name}の担当",
    })
    assert ct.status_code == 201, ct.text
    return company_id, ct.json()["id"]


async def _create_order(client, order_number="ORD-COM-1", status_value="pending"):
    company_id, contact_id = await _create_company_contact(client, f"Co-{order_number}")
    res = await client.post(
        "/api/v1/orders",
        json={
            "company_id": company_id,
            "contact_id": contact_id,
            "order_number": order_number,
            "status": status_value,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


_role_counter = {"n": 1000}
_staff_counter = {"n": 1000}


async def _create_role_direct(db_session, name="営業", priority=10):
    """role を直接 INSERT して id を返す（test_staff_me と同じ方式）。

    /api/v1/roles 経由だと public.users 参照で失敗するため SQL で直接投入する。
    id は重複しないように単調増加させる。
    """
    from sqlalchemy import text

    _role_counter["n"] += 1
    rid = _role_counter["n"]
    await db_session.execute(
        text(
            """
            INSERT INTO roles (id, tenant_id, name, color, priority, is_system)
            VALUES (:id, 999, :name, '#888888', :pr, 0)
            """
        ),
        {"id": rid, "name": f"{name}-{rid}", "pr": priority},
    )
    await db_session.commit()
    return rid


async def _create_staff_direct(
    db_session,
    surname="山田",
    given="太郎",
    email="taro@example.com",
    is_employee=False,
    role_id=None,
):
    """staff を直接 INSERT して id を返す（test_staff_me と同じ方式）。

    /api/v1/staff 経由は role_id 検証 + audit log で複雑なので避ける。
    is_employee は migration 050 で追加された BOOLEAN カラム。
    """
    from sqlalchemy import text

    if role_id is None:
        role_id = await _create_role_direct(db_session)
    _staff_counter["n"] += 1
    sid = _staff_counter["n"]
    await db_session.execute(
        text(
            """
            INSERT INTO staff (
                id, tenant_id, staff_code, surname_jp, given_name_jp,
                primary_email, role_id, status, is_employee
            ) VALUES (
                :id, 999, :code, :sjp, :gjp,
                :email, :rid, 'active', :is_emp
            )
            """
        ),
        {
            "id": sid,
            "code": f"EMP-{sid:05d}",
            "sjp": surname,
            "gjp": given,
            "email": email,
            "rid": role_id,
            "is_emp": 1 if is_employee else 0,
        },
    )
    await db_session.commit()
    return sid


async def _create_staff(
    client,
    surname="山田",
    given="太郎",
    email="taro@example.com",
    is_employee=False,
    role_id=None,
    db_session=None,
):
    """フィクスチャ：直接 SQL で staff を作って id を返す。"""
    # テスト関数からは db_session フィクスチャを直接受けてもらう経路を使うが、
    # 既存のテストは client のみを引数にする慣習があるため、conftest の
    # db_session を fixture 経由で持ち回ったほうが綺麗だが本ファイル内の
    # 利便性最大化を優先し、`client` 経由で `app.dependency_overrides` から
    # セッションを引き出す。
    if db_session is None:
        from app.main import app
        from app.database import get_db
        # client fixture が override_get_db でセッションを yield しており、
        # その同じ db_session が dependency_overrides[get_db] に登録されている。
        override = app.dependency_overrides.get(get_db)
        if override is None:
            raise RuntimeError("client fixture が DB セッションを登録していません")
        # override は async generator 関数。1 回 next 相当で session を取り出す。
        agen = override()
        db_session = await agen.__anext__()
    return await _create_staff_direct(
        db_session,
        surname=surname,
        given=given,
        email=email,
        is_employee=is_employee,
        role_id=role_id,
    )


async def _create_financial(client, order_id, commission_base_amount):
    res = await client.post(
        f"/api/v1/orders/{order_id}/financial",
        json={"commission_base_amount": commission_base_amount},
    )
    assert res.status_code == 201, res.text


class TestAssignEndpoint:
    async def test_assign_creates_row_for_role(self, client):
        order_id = await _create_order(client, "ORD-COM-ASSIGN-1")
        staff_id = await _create_staff(client, email="assign1@example.com")

        res = await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "sales", "staff_id": staff_id},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["role"] == "sales"
        assert body["staff_id"] == staff_id
        assert body["staff_name"] == "山田 太郎"
        assert float(body["calculated_amount"]) == 0.0  # recalc 前は 0

    async def test_assign_upsert_overwrites_staff(self, client):
        """既存行に再 assign すると staff_id が上書きされる（UPSERT）"""
        order_id = await _create_order(client, "ORD-COM-UPSERT")
        staff1 = await _create_staff(client, email="up1@example.com", surname="A")
        staff2 = await _create_staff(client, email="up2@example.com", surname="B")
        await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "sales", "staff_id": staff1},
        )
        res = await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "sales", "staff_id": staff2},
        )
        assert res.status_code == 200, res.text
        assert res.json()["staff_id"] == staff2

    async def test_assign_unknown_order_returns_404(self, client):
        res = await client.post(
            "/api/v1/orders/9999999/commissions/assign",
            json={"role": "sales", "staff_id": 1},
        )
        assert res.status_code == 404

    async def test_assign_unknown_staff_returns_400(self, client):
        order_id = await _create_order(client, "ORD-COM-BADSTAFF")
        res = await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "sales", "staff_id": 9999999},
        )
        assert res.status_code == 400

    async def test_assign_invalid_role_returns_422(self, client):
        order_id = await _create_order(client, "ORD-COM-BADROLE")
        staff_id = await _create_staff(client, email="badrole@example.com")
        res = await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "manager", "staff_id": staff_id},  # 5 ロール外
        )
        assert res.status_code == 422

    async def test_assign_5_roles(self, client):
        """5 ロール全てに割当可能"""
        order_id = await _create_order(client, "ORD-COM-5ROLES")
        staff_id = await _create_staff(client, email="five@example.com")
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            res = await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": role, "staff_id": staff_id},
            )
            assert res.status_code == 200, f"role={role} failed: {res.text}"


class TestRecalcEndpoint:
    async def test_recalc_applies_current_formula(self, client):
        """recalc で 5 ロールが現行式通り計算される"""
        order_id = await _create_order(client, "ORD-COM-RECALC-1", status_value="pending")
        staff_id = await _create_staff(client, email="recalc1@example.com")
        await _create_financial(client, order_id, 10000)
        # 5 ロールに staff を割当
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": role, "staff_id": staff_id},
            )

        res = await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")
        assert res.status_code == 200, res.text
        body = res.json()
        commissions = body["commissions"]
        assert float(commissions["sales"]["calculated_amount"]) == 1000.0
        assert float(commissions["order"]["calculated_amount"]) == 1000.0
        assert float(commissions["ship"]["calculated_amount"]) == 200.0
        assert float(commissions["purchase"]["calculated_amount"]) == 100.0
        assert float(commissions["trouble"]["calculated_amount"]) == 500.0
        # calculated_at が記録されている
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            assert commissions[role]["calculated_at"] is not None

    async def test_recalc_cancelled_order_zeroes_three_roles(self, client):
        """キャンセル受注 → 営業/受注/発送 0、仕入/トラブルは支払う"""
        order_id = await _create_order(
            client, "ORD-COM-RECALC-CANCEL", status_value="cancelled"
        )
        staff_id = await _create_staff(client, email="cancel@example.com")
        await _create_financial(client, order_id, 10000)
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": role, "staff_id": staff_id},
            )
        res = await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")
        assert res.status_code == 200
        commissions = res.json()["commissions"]
        assert float(commissions["sales"]["calculated_amount"]) == 0.0
        assert float(commissions["order"]["calculated_amount"]) == 0.0
        assert float(commissions["ship"]["calculated_amount"]) == 0.0
        assert float(commissions["purchase"]["calculated_amount"]) == 100.0
        assert float(commissions["trouble"]["calculated_amount"]) == 500.0

    async def test_recalc_employee_returns_zero_all_roles(self, client):
        """is_employee=True の staff → 全ロール 0"""
        order_id = await _create_order(client, "ORD-COM-EMP")
        staff_id = await _create_staff(
            client, email="emp@example.com", is_employee=True
        )
        await _create_financial(client, order_id, 10000)
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": role, "staff_id": staff_id},
            )
        res = await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")
        assert res.status_code == 200
        commissions = res.json()["commissions"]
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            assert float(commissions[role]["calculated_amount"]) == 0.0

    async def test_recalc_uses_custom_rates(self, client):
        """テナント設定 PATCH 後に recalc すると新 rate で計算される"""
        # rate を 20% / fixed 1000 に変更
        await client.patch(
            "/api/v1/tenant-commission-settings",
            json={
                "commission_rates": {
                    "sales": {"type": "rate", "value": 0.20},
                    "order": {"type": "rate", "value": 0.20},
                    "ship": {"type": "fixed", "value": 1000},
                    "purchase": {"type": "fixed", "value": 1000},
                    "trouble": {"type": "fixed", "value": 1000},
                }
            },
        )
        order_id = await _create_order(client, "ORD-COM-CUSTOM")
        staff_id = await _create_staff(client, email="custom@example.com")
        await _create_financial(client, order_id, 10000)
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": role, "staff_id": staff_id},
            )
        res = await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")
        assert res.status_code == 200
        commissions = res.json()["commissions"]
        assert float(commissions["sales"]["calculated_amount"]) == 2000.0  # 10000 × 20%
        assert float(commissions["order"]["calculated_amount"]) == 2000.0
        assert float(commissions["ship"]["calculated_amount"]) == 1000.0
        assert float(commissions["purchase"]["calculated_amount"]) == 1000.0
        assert float(commissions["trouble"]["calculated_amount"]) == 1000.0

    async def test_recalc_without_financial_zeroes_rate_roles(self, client):
        """financial 未登録 → 営業/受注 (rate) は 0、ship/purchase/trouble (fixed) は支払う"""
        order_id = await _create_order(client, "ORD-COM-NOFIN")
        staff_id = await _create_staff(client, email="nofin@example.com")
        # financial を作らない
        for role in ("sales", "order", "ship", "purchase", "trouble"):
            await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": role, "staff_id": staff_id},
            )
        res = await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")
        assert res.status_code == 200
        commissions = res.json()["commissions"]
        assert float(commissions["sales"]["calculated_amount"]) == 0.0
        assert float(commissions["order"]["calculated_amount"]) == 0.0
        assert float(commissions["ship"]["calculated_amount"]) == 200.0
        assert float(commissions["purchase"]["calculated_amount"]) == 100.0
        assert float(commissions["trouble"]["calculated_amount"]) == 500.0

    async def test_recalc_unknown_order_404(self, client):
        res = await client.post("/api/v1/orders/9999999/commissions/recalc")
        assert res.status_code == 404


class TestGetEndpoint:
    async def test_get_returns_5_keys_with_nulls(self, client):
        """未登録ロールは null で返る（必ず 5 キー）"""
        order_id = await _create_order(client, "ORD-COM-GET-1")
        staff_id = await _create_staff(client, email="get1@example.com")
        await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "sales", "staff_id": staff_id},
        )
        res = await client.get(f"/api/v1/orders/{order_id}/commissions")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["order_id"] == order_id
        # 必ず 5 キー
        assert set(body["commissions"].keys()) == {
            "sales",
            "order",
            "ship",
            "purchase",
            "trouble",
        }
        assert body["commissions"]["sales"] is not None
        assert body["commissions"]["order"] is None
        assert body["commissions"]["ship"] is None

    async def test_get_unknown_order_returns_404(self, client):
        res = await client.get("/api/v1/orders/9999999/commissions")
        assert res.status_code == 404


class TestUnassignEndpoint:
    async def test_unassign_keeps_row_with_null_staff(self, client):
        """担当解除すると行は残るが staff_id=None / amount=0"""
        order_id = await _create_order(client, "ORD-COM-UNASSIGN")
        staff_id = await _create_staff(client, email="unassign@example.com")
        await _create_financial(client, order_id, 10000)
        await client.post(
            f"/api/v1/orders/{order_id}/commissions/assign",
            json={"role": "sales", "staff_id": staff_id},
        )
        await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")

        res = await client.delete(f"/api/v1/orders/{order_id}/commissions/sales")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["staff_id"] is None
        assert float(body["calculated_amount"]) == 0.0

        # GET でも sales が「行あり / staff_id=null」
        get_res = await client.get(f"/api/v1/orders/{order_id}/commissions")
        sales = get_res.json()["commissions"]["sales"]
        assert sales is not None
        assert sales["staff_id"] is None

    async def test_unassign_unknown_role_returns_404(self, client):
        order_id = await _create_order(client, "ORD-COM-UNASSIGN-404")
        res = await client.delete(f"/api/v1/orders/{order_id}/commissions/sales")
        assert res.status_code == 404


class TestMonthlyEndpoint:
    async def test_monthly_aggregates_by_staff_and_role(self, client):
        """月次集計: by_staff / by_role / total が返る"""
        # 2 受注 × 2 staff で recalc
        order1 = await _create_order(client, "ORD-COM-MON-1")
        order2 = await _create_order(client, "ORD-COM-MON-2")
        staff_a = await _create_staff(client, email="mona@example.com", surname="月次A")
        staff_b = await _create_staff(client, email="monb@example.com", surname="月次B")
        await _create_financial(client, order1, 10000)
        await _create_financial(client, order2, 20000)
        # order1: sales=A
        await client.post(
            f"/api/v1/orders/{order1}/commissions/assign",
            json={"role": "sales", "staff_id": staff_a},
        )
        # order2: sales=B, ship=A
        await client.post(
            f"/api/v1/orders/{order2}/commissions/assign",
            json={"role": "sales", "staff_id": staff_b},
        )
        await client.post(
            f"/api/v1/orders/{order2}/commissions/assign",
            json={"role": "ship", "staff_id": staff_a},
        )
        await client.post(f"/api/v1/orders/{order1}/commissions/recalc")
        await client.post(f"/api/v1/orders/{order2}/commissions/recalc")

        # recalc 時に Python 側で datetime.now(UTC) を calculated_at に書き込むため、
        # 月次集計は当該テスト実行月（JST）で照会する。
        # UTC.month を使うと月末 JST0:00〜UTC0:00 の9時間で月境界がずれるため JST で取得。
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
        res = await client.get(
            f"/api/v1/commissions/monthly?year={now_jst.year}&month={now_jst.month}"
        )
        assert res.status_code == 200, res.text
        body = res.json()

        by_staff = {item["staff_id"]: float(item["total"]) for item in body["by_staff"]}
        # A = order1 sales (1000) + order2 ship (200) = 1200
        # B = order2 sales (2000) = 2000
        assert by_staff[staff_a] == 1200.0
        assert by_staff[staff_b] == 2000.0

        by_role = {item["role"]: float(item["total"]) for item in body["by_role"]}
        # sales = 1000 + 2000 = 3000、ship = 200
        assert by_role["sales"] == 3000.0
        assert by_role["ship"] == 200.0
        # total = 3200
        assert float(body["total"]) == 3200.0

    async def test_monthly_empty_returns_zero_total(self, client):
        """データが無くてもエラーにならず total=0 を返す"""
        res = await client.get("/api/v1/commissions/monthly?year=2026&month=1")
        assert res.status_code == 200
        body = res.json()
        assert float(body["total"]) == 0.0
        assert body["by_staff"] == []
        assert body["by_role"] == []

    async def test_monthly_invalid_month_returns_422(self, client):
        res = await client.get("/api/v1/commissions/monthly?year=2026&month=13")
        assert res.status_code == 422


class TestMonthlyJstBoundary:
    """ADR-021 J2 fix (2026-05-13): /commissions/monthly の JST 暦月境界。

    JST 業務日基準で月末 23:59:59 までを当該月にカウントする。
    UTC 換算では当該月の前月末 15:00:00 〜 当該月末 15:00:00 が範囲。

    SQLite テストでは Python 側で UTC 等価 datetime を生成し、それを
    raw SQL で order_commissions.calculated_at に直接 INSERT する。
    """

    async def _insert_commission_with_calc_at(
        self,
        order_id: int,
        role: str,
        staff_id: int | None,
        amount: float,
        calc_at_utc: "datetime",
    ):
        """テスト用に order_commissions 行を SQL で直接挿入する。

        recalc は datetime.now(UTC) を書き込むため境界テストには使えず、
        ここでは calc_at_utc（aware UTC datetime）をそのまま calculated_at
        にセットする。SQLAlchemy が SQLite に向けて文字列化したものと
        router 側の bind 値が完全に一致するよう、両方で aware datetime
        を使う。
        """
        from sqlalchemy import text

        from app.database import get_db
        from app.main import app

        override = app.dependency_overrides.get(get_db)
        if override is None:
            raise RuntimeError("client fixture が DB セッションを登録していません")
        agen = override()
        db = await agen.__anext__()
        await db.execute(
            text(
                """
                INSERT INTO order_commissions
                    (order_id, tenant_id, role, staff_id, calculated_amount, calculated_at)
                VALUES (:oid, 999, :role, :sid, :amt, :cat)
                """
            ),
            {
                "oid": order_id,
                "role": role,
                "sid": staff_id,
                "amt": amount,
                "cat": calc_at_utc,
            },
        )
        await db.commit()

    async def test_monthly_includes_jst_late_night_order(self, client):
        """JST 2026-05-31 23:59:59 の行は month=5 集計に含まれ month=6 には含まれない"""
        from datetime import datetime, timezone
        order_id = await _create_order(client, "ORD-COM-JST-LATE")
        staff_id = await _create_staff(client, email="jstlate@example.com")
        # JST 2026-05-31 23:59:59 = UTC 2026-05-31 14:59:59
        await self._insert_commission_with_calc_at(
            order_id, "sales", staff_id, 1000.0,
            datetime(2026, 5, 31, 14, 59, 59, tzinfo=timezone.utc),
        )

        res_may = await client.get(
            "/api/v1/commissions/monthly?year=2026&month=5"
        )
        assert res_may.status_code == 200, res_may.text
        body_may = res_may.json()
        assert float(body_may["total"]) == 1000.0

        res_jun = await client.get(
            "/api/v1/commissions/monthly?year=2026&month=6"
        )
        assert res_jun.status_code == 200, res_jun.text
        assert float(res_jun.json()["total"]) == 0.0

    async def test_monthly_excludes_jst_month_start(self, client):
        """JST 2026-04-30 23:59:59 は 5 月集計に含まれず、JST 2026-05-01 00:00:00 は含まれる"""
        from datetime import datetime, timezone
        order_a = await _create_order(client, "ORD-COM-JST-APR-END")
        order_b = await _create_order(client, "ORD-COM-JST-MAY-START")
        staff_id = await _create_staff(client, email="jstboundary@example.com")
        # JST 2026-04-30 23:59:59 = UTC 2026-04-30 14:59:59
        await self._insert_commission_with_calc_at(
            order_a, "sales", staff_id, 500.0,
            datetime(2026, 4, 30, 14, 59, 59, tzinfo=timezone.utc),
        )
        # JST 2026-05-01 00:00:00 = UTC 2026-04-30 15:00:00
        await self._insert_commission_with_calc_at(
            order_b, "sales", staff_id, 700.0,
            datetime(2026, 4, 30, 15, 0, 0, tzinfo=timezone.utc),
        )

        res_may = await client.get(
            "/api/v1/commissions/monthly?year=2026&month=5"
        )
        assert res_may.status_code == 200, res_may.text
        # 5/1 00:00 の 700 のみ含まれる
        assert float(res_may.json()["total"]) == 700.0

        res_apr = await client.get(
            "/api/v1/commissions/monthly?year=2026&month=4"
        )
        assert res_apr.status_code == 200, res_apr.text
        # 4/30 23:59 の 500 のみ含まれる
        assert float(res_apr.json()["total"]) == 500.0

    async def test_monthly_december_jst_boundary_year_rollover(self, client):
        """12 月境界: JST 2026-12-31 23:59:59 は month=12、2027-01-01 00:00:00 は 2027 年 1 月"""
        from datetime import datetime, timezone
        order_dec = await _create_order(client, "ORD-COM-JST-DEC-END")
        order_jan = await _create_order(client, "ORD-COM-JST-JAN-START")
        staff_id = await _create_staff(client, email="jstdec@example.com")
        # JST 2026-12-31 23:59:59 = UTC 2026-12-31 14:59:59
        await self._insert_commission_with_calc_at(
            order_dec, "sales", staff_id, 1234.0,
            datetime(2026, 12, 31, 14, 59, 59, tzinfo=timezone.utc),
        )
        # JST 2027-01-01 00:00:00 = UTC 2026-12-31 15:00:00
        await self._insert_commission_with_calc_at(
            order_jan, "sales", staff_id, 5678.0,
            datetime(2026, 12, 31, 15, 0, 0, tzinfo=timezone.utc),
        )

        res_dec = await client.get(
            "/api/v1/commissions/monthly?year=2026&month=12"
        )
        assert res_dec.status_code == 200, res_dec.text
        assert float(res_dec.json()["total"]) == 1234.0

        res_jan = await client.get(
            "/api/v1/commissions/monthly?year=2027&month=1"
        )
        assert res_jan.status_code == 200, res_jan.text
        assert float(res_jan.json()["total"]) == 5678.0


class TestJstHelper:
    """ADR-021 J2 fix: services.time._jst_month_range_utc の単体検証。"""

    def test_returns_utc_aware_datetimes(self):
        from app.services.time import _jst_month_range_utc, JST
        start, end = _jst_month_range_utc(2026, 5)
        # 両方 aware で UTC
        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert start.utcoffset().total_seconds() == 0
        assert end.utcoffset().total_seconds() == 0
        # JST 換算で 1 日 00:00
        assert start.astimezone(JST).day == 1
        assert start.astimezone(JST).month == 5
        assert end.astimezone(JST).day == 1
        assert end.astimezone(JST).month == 6

    def test_may_has_31_days(self):
        from app.services.time import _jst_month_range_utc
        start, end = _jst_month_range_utc(2026, 5)
        # 5 月は 31 日
        assert (end - start).days == 31

    def test_february_leap_year(self):
        from app.services.time import _jst_month_range_utc
        # 2024 はうるう年
        start, end = _jst_month_range_utc(2024, 2)
        assert (end - start).days == 29

    def test_february_non_leap_year(self):
        from app.services.time import _jst_month_range_utc
        # 2026 はうるう年でない
        start, end = _jst_month_range_utc(2026, 2)
        assert (end - start).days == 28

    def test_december_rolls_over_year(self):
        from app.services.time import _jst_month_range_utc, JST
        start, end = _jst_month_range_utc(2026, 12)
        assert start.astimezone(JST).year == 2026
        assert end.astimezone(JST).year == 2027
        assert end.astimezone(JST).month == 1

    def test_may_start_is_utc_april_30_15_00(self):
        """JST 5/1 00:00 = UTC 4/30 15:00"""
        from datetime import datetime, timezone
        from app.services.time import _jst_month_range_utc
        start, end = _jst_month_range_utc(2026, 5)
        assert start == datetime(2026, 4, 30, 15, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 5, 31, 15, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 4. 権限・テナント分離
# ---------------------------------------------------------------------------


class TestPermissions:
    """spec.md AC-5.8: マルチテナント分離 + require_permission チェック。

    SQLite テスト基盤では物理的なテナント分離は再現できないが、
    権限チェック (orders.view / orders.update) が依存に残ることを確認する。
    """

    async def test_assign_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-COM-PERM-1")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.post(
                f"/api/v1/orders/{order_id}/commissions/assign",
                json={"role": "sales", "staff_id": 1},
            )
        assert res.status_code == 403

    async def test_recalc_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-COM-PERM-2")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.post(f"/api/v1/orders/{order_id}/commissions/recalc")
        assert res.status_code == 403

    async def test_get_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        order_id = await _create_order(client, "ORD-COM-PERM-3")
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get(f"/api/v1/orders/{order_id}/commissions")
        assert res.status_code == 403

    async def test_monthly_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get("/api/v1/commissions/monthly?year=2026&month=4")
        assert res.status_code == 403

    async def test_settings_get_requires_orders_view(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.get("/api/v1/tenant-commission-settings")
        assert res.status_code == 403

    async def test_settings_patch_requires_orders_update(self, client):
        from unittest.mock import patch

        async def _no_perms(db, tenant_id, user_id):
            return set()

        new_rates = {
            "commission_rates": {
                "sales": {"type": "rate", "value": 0.10},
                "order": {"type": "rate", "value": 0.10},
                "ship": {"type": "fixed", "value": 200},
                "purchase": {"type": "fixed", "value": 100},
                "trouble": {"type": "fixed", "value": 500},
            }
        }
        with patch("app.auth.dependencies.load_user_permissions", _no_perms):
            res = await client.patch(
                "/api/v1/tenant-commission-settings", json=new_rates
            )
        assert res.status_code == 403

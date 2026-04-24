#!/usr/bin/env python3
"""
Phase 1-B-2 Step 3: customers → companies + contacts データ移行スクリプト。

入力（DB から読む）:
    - {schema}.customers                      # 本体 52件
    - {schema}.customer_addresses             # billing / delivery
    - {schema}.customer_sales_channels        # 販売先
    - {schema}.customer_discord               # Discord連携
    - {schema}.customer_contact_channels      # Phase 1-B-1 連絡ツール

入力（CSV）:
    - sheets/manual_company_merge_map.csv     # 手動マージ判定（GROUP-01, GROUP-02, Ocean Harvest）

出力（DB に書く）:
    - {schema}.companies                      # グループ化後の会社マスタ
    - {schema}.contacts                       # 各 customer → 1 contact
    - {schema}.company_addresses              # 住所（branch_name 対応）
    - {schema}.company_sales_channels         # 販売先（会社単位で union）
    - {schema}.contact_contact_channels       # 連絡ツール（contact 単位）
    - {schema}.contact_discord                # Discord（contact 単位）
    - {schema}._customer_migration_map        # 監査ログ

グループ化ルール:
    1. sheets/manual_company_merge_map.csv に載っている customer は target_company_key で GROUP BY
    2. その他は normalize_company_name(company_name) で GROUP BY
    3. グループ leader = customer_code 昇順で先頭の customer
    4. company_code = CO-NNNNN（グループをソートして連番）

migration_method:
    - auto_single       : manual map なし、グループサイズ1（36 個人顧客 + 14 単独法人）
    - auto_multi_branch : manual map で merge_type=multi_branch（Card Galaxy 2支店）
    - manual_merge      : manual map で merge_type=same_branch / multi_contact
    - manual_override   : （将来拡張用、本スクリプトでは未使用）

冪等性:
    - companies/contacts は (tenant_id, company_code)/(tenant_id, contact_code) で UPSERT
    - 副テーブルは対応する parent id で DELETE → INSERT
    - _customer_migration_map は old_customer_id で UPSERT

実行方法（VPS 側 Docker コンテナ内）:
    docker compose exec backend python /app/scripts/data_migration/migrate_companies_contacts_from_customers.py

環境変数:
    DATABASE_URL: 接続先 (必須)
    TENANT_CODE : 対象テナント (デフォルト: 'test-corp')
    SHEETS_DIR  : CSV 配置ディレクトリ (デフォルト: /app/sheets)
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

TENANT_CODE = os.getenv("TENANT_CODE", "test-corp")
SHEETS_DIR = Path(os.getenv("SHEETS_DIR", "/app/sheets"))
MANUAL_MAP_CSV = SHEETS_DIR / "manual_company_merge_map.csv"
ALLOW_EMPTY_MANUAL_MAP = os.getenv("ALLOW_EMPTY_MANUAL_MAP", "").lower() in ("1", "true", "yes")

# analyze_company_names.py と同じ定義（ロジック同一性を担保）
COMPANY_SUFFIXES = [
    " ltd.", " ltd", " inc.", " inc", " llc",
    " co.,ltd.", " co., ltd.", " co ltd", " co,ltd",
    " corp.", " corp", " corporation",
    " limited", " pty ltd", " pty.ltd",
    "株式会社", "有限会社", "合同会社", "合資会社",
    "(株)", "（株）", "(有)", "（有）",
]

BUSINESS_KEYWORDS = [
    "shop", "trade", "cards", "harvest", "seafood", "cocoa",
    "&", "ltd", "inc", "corp", "llc", "corporation", "limited", "pty",
    "company", "co.", "store", "mart", "group", "holdings",
    "株式会社", "有限会社", "合同会社", "(株)", "（株）", "(有)", "（有）",
]


def normalize_company_name(name: Optional[str]) -> str:
    """会社名の正規化キーを生成（名寄せ判定用）。analyze_company_names.py と同一ロジック。"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).strip().lower()
    s = re.sub(r"[\(（][^)）]*[\)）]", "", s)
    for suffix in COMPANY_SUFFIXES:
        pattern = re.escape(suffix.strip())
        s = re.sub(rf"\s*{pattern}\b", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[.,;:\-_]+$", "", s)
    return s.strip()


def looks_like_individual(company: Optional[str], delivery_name: Optional[str]) -> bool:
    """個人顧客判定（analyze_company_names.py と同一ロジックの簡約版）。"""
    s = (company or "").strip()
    if not s:
        return True
    s_lower = s.lower()
    if any(kw in s_lower for kw in BUSINESS_KEYWORDS):
        return False
    if delivery_name and s == delivery_name.strip():
        return True
    words = s.split()
    if len(words) <= 2 and all(len(w) < 20 for w in words):
        return True
    return False


def extract_branch_name(company_name: Optional[str]) -> Optional[str]:
    """会社名の括弧書き部分を支店名として抽出。
    例: "Card Galaxy LTD(Essex)" → "Essex"
        "TCG TRADE(23 Worcester Street)" → "23 Worcester Street"
    括弧がなければ None。
    """
    if not company_name:
        return None
    m = re.search(r"[\(（]([^)）]+)[\)）]", company_name)
    if m:
        return m.group(1).strip() or None
    return None


def clean_company_name(company_name: Optional[str]) -> str:
    """会社名から括弧書き（支店名）を除去した表示用クリーン名。"""
    if not company_name:
        return ""
    s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*", " ", company_name)
    return re.sub(r"\s+", " ", s).strip()


# =============================================================================
# manual_company_merge_map.csv
# =============================================================================

@dataclass
class ManualMergeEntry:
    target_company_key: str   # "tcg_trade", "card_galaxy_ltd", "ocean_harvest_seafood"
    merge_type: str           # "same_branch" / "multi_branch" / "multi_contact"
    notes: str


def load_manual_map() -> dict[str, ManualMergeEntry]:
    """manual_company_merge_map.csv を読み、customer_code → ManualMergeEntry を返す。

    CSV が見つからない場合:
      - デフォルト: FileNotFoundError で loud に失敗（運用ミスでデータ破損するのを防ぐ）
      - ALLOW_EMPTY_MANUAL_MAP=1 の場合のみ空 dict を返して続行
        （新規テナントで手動マージ不要なことが確定している時の明示的オプトイン）
    """
    if not MANUAL_MAP_CSV.exists():
        if not ALLOW_EMPTY_MANUAL_MAP:
            raise FileNotFoundError(
                f"manual_company_merge_map.csv が見つかりません: {MANUAL_MAP_CSV}\n"
                "既知のマージ判定（GROUP-01 Card Galaxy / GROUP-02 TCG TRADE / Ocean Harvest）が\n"
                "反映されずにバラバラ投入されるのを防ぐため、本スクリプトは CSV 必須です。\n"
                "手動マージ不要なテナントで実行する場合は ALLOW_EMPTY_MANUAL_MAP=1 を明示指定してください。"
            )
        logger.warning(
            "manual_company_merge_map.csv が見つかりませんが ALLOW_EMPTY_MANUAL_MAP=1 のため続行: %s",
            MANUAL_MAP_CSV,
        )
        return {}
    result: dict[str, ManualMergeEntry] = {}
    with MANUAL_MAP_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = (row.get("old_customer_id") or "").strip()
            key = (row.get("target_company_key") or "").strip()
            merge_type = (row.get("merge_type") or "").strip()
            notes = (row.get("notes") or "").strip()
            if not cid or not key or not merge_type:
                continue
            if merge_type not in ("same_branch", "multi_branch", "multi_contact"):
                logger.warning("未知の merge_type: %s (customer=%s, skip)", merge_type, cid)
                continue
            result[cid] = ManualMergeEntry(
                target_company_key=key,
                merge_type=merge_type,
                notes=notes,
            )
    logger.info("manual merge map 読込: %d件", len(result))
    return result


# =============================================================================
# DB から全顧客データを取得
# =============================================================================

@dataclass
class CustomerSnapshot:
    """customers + 副テーブル全部を読み出した構造。"""
    id: int
    customer_code: str
    lead_id: Optional[int]
    sales_rep_id: Optional[int]
    company_name: Optional[str]
    trust_level: Optional[int]
    priority_focus: Optional[str]
    per_order_amount: Optional[float]
    monthly_frequency: Optional[int]
    monthly_forecast: Optional[float]
    monthly_forecast_source: Optional[str]
    monthly_forecast_updated_at: Optional[object]
    billing_display_name: Optional[str]
    payment_recipient_name: Optional[str]
    fedex_account: Optional[str]
    shipping_note: Optional[str]
    primary_contact_channel: Optional[str]
    status: str
    created_at: object
    addresses: list[dict] = field(default_factory=list)     # customer_addresses
    sales_channels: list[str] = field(default_factory=list) # customer_sales_channels
    discord: Optional[dict] = None                          # customer_discord 1行
    contact_channels: list[dict] = field(default_factory=list)  # customer_contact_channels


async def fetch_all_customers(conn, schema: str, tenant_id: int) -> list[CustomerSnapshot]:
    """customers + 副テーブルを一括取得。"""
    result = await conn.execute(
        text(f"""
            SELECT id, customer_code, lead_id, sales_rep_id, company_name,
                   trust_level, priority_focus, per_order_amount, monthly_frequency,
                   monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
                   billing_display_name, payment_recipient_name,
                   fedex_account, shipping_note, primary_contact_channel,
                   status, created_at
            FROM {schema}.customers
            WHERE tenant_id = :tid
            ORDER BY customer_code
        """),
        {"tid": tenant_id},
    )
    customers: list[CustomerSnapshot] = []
    for row in result.mappings():
        customers.append(CustomerSnapshot(
            id=row["id"],
            customer_code=row["customer_code"],
            lead_id=row["lead_id"],
            sales_rep_id=row["sales_rep_id"],
            company_name=row["company_name"],
            trust_level=row["trust_level"],
            priority_focus=row["priority_focus"],
            per_order_amount=float(row["per_order_amount"]) if row["per_order_amount"] is not None else None,
            monthly_frequency=row["monthly_frequency"],
            monthly_forecast=float(row["monthly_forecast"]) if row["monthly_forecast"] is not None else None,
            monthly_forecast_source=row["monthly_forecast_source"],
            monthly_forecast_updated_at=row["monthly_forecast_updated_at"],
            billing_display_name=row["billing_display_name"],
            payment_recipient_name=row["payment_recipient_name"],
            fedex_account=row["fedex_account"],
            shipping_note=row["shipping_note"],
            primary_contact_channel=row["primary_contact_channel"],
            status=row["status"],
            created_at=row["created_at"],
        ))

    # by id 索引
    by_id = {c.id: c for c in customers}

    # addresses
    addr_result = await conn.execute(
        text(f"""
            SELECT customer_id, address_type, name, email, telephone, tax_id,
                   address_line_1, address_line_2, address_line_3, city, state, zip, country_code
            FROM {schema}.customer_addresses
            WHERE customer_id = ANY(:cids)
            ORDER BY customer_id, address_type, id
        """),
        {"cids": list(by_id.keys())},
    )
    for a in addr_result.mappings():
        by_id[a["customer_id"]].addresses.append(dict(a))

    # sales channels
    sc_result = await conn.execute(
        text(f"""
            SELECT customer_id, channel
            FROM {schema}.customer_sales_channels
            WHERE customer_id = ANY(:cids)
        """),
        {"cids": list(by_id.keys())},
    )
    for s in sc_result.mappings():
        by_id[s["customer_id"]].sales_channels.append(s["channel"])

    # discord
    dc_result = await conn.execute(
        text(f"""
            SELECT customer_id, is_joined, channel_id, user_id, invoice_webhook, shipment_webhook
            FROM {schema}.customer_discord
            WHERE customer_id = ANY(:cids)
        """),
        {"cids": list(by_id.keys())},
    )
    for d in dc_result.mappings():
        by_id[d["customer_id"]].discord = dict(d)

    # contact channels (Phase 1-B-1)
    cc_result = await conn.execute(
        text(f"""
            SELECT customer_id, channel, purpose, is_primary
            FROM {schema}.customer_contact_channels
            WHERE customer_id = ANY(:cids)
            ORDER BY customer_id, id
        """),
        {"cids": list(by_id.keys())},
    )
    for cc in cc_result.mappings():
        by_id[cc["customer_id"]].contact_channels.append(dict(cc))

    logger.info(
        "顧客データ取得: customers=%d, addresses=%d, sales_channels=%d, discord=%d, contact_channels=%d",
        len(customers),
        sum(len(c.addresses) for c in customers),
        sum(len(c.sales_channels) for c in customers),
        sum(1 for c in customers if c.discord),
        sum(len(c.contact_channels) for c in customers),
    )
    return customers


# =============================================================================
# グループ化
# =============================================================================

@dataclass
class CompanyGroup:
    group_key: str                      # manual_map の company_key or normalized_name
    members: list[CustomerSnapshot]     # customer_code 昇順
    merge_type: Optional[str] = None    # manual_map の merge_type（あれば）
    manual_notes: str = ""              # manual_map の notes 連結

    @property
    def leader(self) -> CustomerSnapshot:
        return self.members[0]

    @property
    def size(self) -> int:
        return len(self.members)

    def migration_method(self) -> str:
        if self.merge_type == "multi_branch":
            return "auto_multi_branch"
        if self.merge_type in ("same_branch", "multi_contact"):
            return "manual_merge"
        # manual map 外
        return "auto_single" if self.size == 1 else "auto_multi_branch"


def group_customers(
    customers: list[CustomerSnapshot],
    manual_map: dict[str, ManualMergeEntry],
) -> list[CompanyGroup]:
    """
    customers を会社グループに分割。

    1. manual_map にある customer は target_company_key でグループ化
    2. その他は normalize_company_name(company_name) でグループ化
       （正規化後空文字なら customer_code を key にして単独グループ扱い）
    3. 各グループ内は customer_code 昇順でソート
    4. グループリストは leader.customer_code 昇順で返す
    """
    groups: dict[str, CompanyGroup] = {}

    for cust in customers:
        if cust.customer_code in manual_map:
            entry = manual_map[cust.customer_code]
            key = f"__manual__{entry.target_company_key}"
            grp = groups.setdefault(key, CompanyGroup(group_key=key, members=[]))
            grp.members.append(cust)
            grp.merge_type = entry.merge_type
            if entry.notes:
                grp.manual_notes = (grp.manual_notes + "\n" + entry.notes).strip()
        else:
            norm = normalize_company_name(cust.company_name)
            if not norm:
                # 正規化不能（会社名空欄等）→ customer_code 単独
                key = f"__single__{cust.customer_code}"
            else:
                key = f"__auto__{norm}"
            grp = groups.setdefault(key, CompanyGroup(group_key=key, members=[]))
            grp.members.append(cust)

    # 各グループ内を customer_code 昇順、グループリスト全体も leader.customer_code 昇順
    for grp in groups.values():
        grp.members.sort(key=lambda c: c.customer_code)
    sorted_groups = sorted(groups.values(), key=lambda g: g.leader.customer_code)

    logger.info(
        "グループ化完了: %d customers → %d companies（single=%d, multi=%d）",
        len(customers),
        len(sorted_groups),
        sum(1 for g in sorted_groups if g.size == 1),
        sum(1 for g in sorted_groups if g.size > 1),
    )
    for grp in sorted_groups:
        if grp.size > 1 or grp.merge_type:
            logger.info(
                "  %s (%s, size=%d, method=%s): %s",
                grp.group_key,
                grp.merge_type or "-",
                grp.size,
                grp.migration_method(),
                ", ".join(m.customer_code for m in grp.members),
            )
    return sorted_groups


# =============================================================================
# companies / contacts / 副テーブル INSERT
# =============================================================================

def choose_company_name(leader: CustomerSnapshot) -> str:
    """会社名。leader の company_name から括弧書きを除去。空ならbilling→display_name→customer_code。"""
    name = clean_company_name(leader.company_name)
    if name:
        return name
    if leader.billing_display_name:
        return leader.billing_display_name.strip()
    # 最終フォールバック
    return leader.customer_code


def dedupe_addresses(members: list[CustomerSnapshot], merge_type: Optional[str]) -> list[tuple[CustomerSnapshot, dict, Optional[str]]]:
    """
    グループ内の全 customer_addresses をマージ候補として返す。
    戻り値: [(source_customer, address_row, branch_name_or_None), ...]

    挙動:
      - multi_branch: 各 customer の住所を branch_name 付きで保持（leader=branch_name1、2人目=branch_name2）
      - same_branch: 先頭 customer の住所のみ保持（重複はドロップ）
      - multi_contact: 先頭 customer の住所のみ保持（2人目は同じ会社想定）
      - それ以外（auto_single, auto_multi_branch_非手動）: 各 customer の住所を branch_name 付きで保持

    address 完全一致（type + line1 + city + zip）は重複としてドロップ。
    """
    if merge_type in ("same_branch", "multi_contact"):
        # 先頭のみ
        result = []
        for addr in members[0].addresses:
            result.append((members[0], addr, None))
        return result

    # multi_branch / auto_multi_branch / auto_single
    result = []
    seen = set()  # (type, name, line1, city, zip) で重複判定
    for m in members:
        branch = extract_branch_name(m.company_name) if len(members) > 1 else None
        for addr in m.addresses:
            key = (
                addr["address_type"],
                (addr.get("name") or "").strip().lower(),
                (addr.get("address_line_1") or "").strip().lower(),
                (addr.get("city") or "").strip().lower(),
                (addr.get("zip") or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append((m, addr, branch))
    return result


async def upsert_company(
    conn, schema: str, tenant_id: int,
    company_code: str, leader: CustomerSnapshot,
    group: CompanyGroup,
) -> int:
    """companies を UPSERT して id を返す。"""
    name = choose_company_name(leader)
    norm = normalize_company_name(leader.company_name)
    # 個人顧客判定: leader の delivery name を使う
    delivery_name = None
    for a in leader.addresses:
        if a["address_type"] == "delivery":
            delivery_name = a.get("name")
            break
    # グループサイズ>1 なら明確に法人
    is_individual = False if group.size > 1 else looks_like_individual(leader.company_name, delivery_name)

    # leader の status が 'pending_dedup_review' なら、merge 完了時点で 'active' に昇格
    # （contact 側と同じロジック。手動マージ/auto グループ化でどちらの場合も dedup は解決済み）
    company_status = "active" if leader.status == "pending_dedup_review" else leader.status

    result = await conn.execute(
        text(f"""
            INSERT INTO {schema}.companies (
                tenant_id, company_code, lead_id, name, normalized_name, is_individual,
                trust_level, priority_focus, per_order_amount, monthly_frequency,
                monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
                billing_display_name, payment_recipient_name, fedex_account, shipping_note,
                status, sales_rep_id, created_at
            ) VALUES (
                :tenant_id, :company_code, :lead_id, :name, :normalized_name, :is_individual,
                :trust_level, :priority_focus, :per_order_amount, :monthly_frequency,
                :monthly_forecast, :monthly_forecast_source, :monthly_forecast_updated_at,
                :billing_display_name, :payment_recipient_name, :fedex_account, :shipping_note,
                :status, :sales_rep_id, COALESCE(:created_at, NOW())
            )
            ON CONFLICT (tenant_id, company_code) DO UPDATE SET
                lead_id = EXCLUDED.lead_id,
                name = EXCLUDED.name,
                normalized_name = EXCLUDED.normalized_name,
                is_individual = EXCLUDED.is_individual,
                trust_level = EXCLUDED.trust_level,
                priority_focus = EXCLUDED.priority_focus,
                per_order_amount = EXCLUDED.per_order_amount,
                monthly_frequency = EXCLUDED.monthly_frequency,
                monthly_forecast = EXCLUDED.monthly_forecast,
                monthly_forecast_source = EXCLUDED.monthly_forecast_source,
                monthly_forecast_updated_at = EXCLUDED.monthly_forecast_updated_at,
                billing_display_name = EXCLUDED.billing_display_name,
                payment_recipient_name = EXCLUDED.payment_recipient_name,
                fedex_account = EXCLUDED.fedex_account,
                shipping_note = EXCLUDED.shipping_note,
                status = EXCLUDED.status,
                sales_rep_id = EXCLUDED.sales_rep_id,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "company_code": company_code,
            "lead_id": leader.lead_id,
            "name": name,
            "normalized_name": norm or None,
            "is_individual": is_individual,
            "trust_level": leader.trust_level,
            "priority_focus": leader.priority_focus,
            "per_order_amount": leader.per_order_amount,
            "monthly_frequency": leader.monthly_frequency,
            "monthly_forecast": leader.monthly_forecast,
            "monthly_forecast_source": leader.monthly_forecast_source,
            "monthly_forecast_updated_at": leader.monthly_forecast_updated_at,
            "billing_display_name": leader.billing_display_name,
            "payment_recipient_name": leader.payment_recipient_name,
            "fedex_account": leader.fedex_account,
            "shipping_note": leader.shipping_note,
            "status": company_status,
            "sales_rep_id": leader.sales_rep_id,
            "created_at": leader.created_at,
        },
    )
    return result.scalar_one()


async def upsert_contact(
    conn, schema: str, tenant_id: int,
    company_id: int, source: CustomerSnapshot, is_primary: bool,
) -> int:
    """contacts を UPSERT して id を返す。"""
    # delivery address の name を surname/given/display の参考にする
    delivery_name = None
    for a in source.addresses:
        if a["address_type"] == "delivery":
            delivery_name = a.get("name")
            break
    display_name = (delivery_name or source.billing_display_name or source.company_name or source.customer_code).strip() or source.customer_code

    # primary_email / primary_phone は delivery/billing address から優先取得
    primary_email = None
    primary_phone = None
    for a in source.addresses:
        if a.get("email") and not primary_email:
            primary_email = a["email"]
        if a.get("telephone") and not primary_phone:
            primary_phone = a["telephone"]

    result = await conn.execute(
        text(f"""
            INSERT INTO {schema}.contacts (
                tenant_id, company_id, contact_code, lead_id,
                surname, given_name, display_name, job_title, department,
                is_primary_contact, primary_email, primary_phone, status, notes,
                created_at
            ) VALUES (
                :tenant_id, :company_id, :contact_code, :lead_id,
                NULL, NULL, :display_name, NULL, NULL,
                :is_primary, :primary_email, :primary_phone, :status, NULL,
                COALESCE(:created_at, NOW())
            )
            ON CONFLICT (tenant_id, contact_code) DO UPDATE SET
                company_id = EXCLUDED.company_id,
                lead_id = EXCLUDED.lead_id,
                display_name = EXCLUDED.display_name,
                is_primary_contact = EXCLUDED.is_primary_contact,
                primary_email = EXCLUDED.primary_email,
                primary_phone = EXCLUDED.primary_phone,
                status = EXCLUDED.status,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "company_id": company_id,
            "contact_code": source.customer_code,  # CT-NNNNN をそのまま contact_code に継承
            "lead_id": source.lead_id,
            "display_name": display_name,
            "is_primary": is_primary,
            "primary_email": primary_email,
            "primary_phone": primary_phone,
            "status": "active" if source.status == "pending_dedup_review" else source.status,
            "created_at": source.created_at,
        },
    )
    return result.scalar_one()


async def migrate_addresses(
    conn, schema: str, company_id: int, group: CompanyGroup,
) -> int:
    """company_addresses を DELETE → INSERT（冪等再投入対応）。"""
    await conn.execute(
        text(f"DELETE FROM {schema}.company_addresses WHERE company_id = :cid"),
        {"cid": company_id},
    )
    entries = dedupe_addresses(group.members, group.merge_type)
    # is_default: 各 address_type で最初の1件を default に
    default_set: dict[str, bool] = {"billing": False, "delivery": False}
    inserted = 0
    for _src, addr, branch in entries:
        atype = addr["address_type"]
        is_default = not default_set[atype]
        default_set[atype] = True
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.company_addresses (
                    company_id, address_type, branch_name,
                    name, email, telephone, tax_id,
                    address_line_1, address_line_2, address_line_3,
                    city, state, zip, country_code, is_default
                ) VALUES (
                    :cid, :atype, :branch,
                    :name, :email, :telephone, :tax_id,
                    :addr1, :addr2, :addr3,
                    :city, :state, :zip, :country, :is_default
                )
            """),
            {
                "cid": company_id,
                "atype": atype,
                "branch": branch,
                "name": addr.get("name"),
                "email": addr.get("email"),
                "telephone": addr.get("telephone"),
                "tax_id": addr.get("tax_id"),
                "addr1": addr.get("address_line_1"),
                "addr2": addr.get("address_line_2"),
                "addr3": addr.get("address_line_3"),
                "city": addr.get("city"),
                "state": addr.get("state"),
                "zip": addr.get("zip"),
                "country": addr.get("country_code"),
                "is_default": is_default,
            },
        )
        inserted += 1
    return inserted


async def migrate_sales_channels(
    conn, schema: str, company_id: int, group: CompanyGroup,
) -> int:
    """company_sales_channels を DELETE → INSERT（union of members, deduped）。"""
    await conn.execute(
        text(f"DELETE FROM {schema}.company_sales_channels WHERE company_id = :cid"),
        {"cid": company_id},
    )
    channels: set[str] = set()
    for m in group.members:
        for c in m.sales_channels:
            channels.add(c)
    for ch in sorted(channels):
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.company_sales_channels (company_id, channel)
                VALUES (:cid, :channel)
            """),
            {"cid": company_id, "channel": ch},
        )
    return len(channels)


async def migrate_contact_discord(
    conn, schema: str, contact_id: int, source: CustomerSnapshot,
) -> bool:
    """contact_discord を UPSERT。source.discord が None なら既存を削除。"""
    if source.discord is None:
        await conn.execute(
            text(f"DELETE FROM {schema}.contact_discord WHERE contact_id = :cid"),
            {"cid": contact_id},
        )
        return False
    d = source.discord
    await conn.execute(
        text(f"""
            INSERT INTO {schema}.contact_discord (
                contact_id, is_joined, channel_id, user_id,
                invoice_webhook, shipment_webhook
            ) VALUES (
                :cid, :is_joined, :channel_id, :user_id, :invoice, :shipment
            )
            ON CONFLICT (contact_id) DO UPDATE SET
                is_joined = EXCLUDED.is_joined,
                channel_id = EXCLUDED.channel_id,
                user_id = EXCLUDED.user_id,
                invoice_webhook = EXCLUDED.invoice_webhook,
                shipment_webhook = EXCLUDED.shipment_webhook,
                updated_at = NOW()
        """),
        {
            "cid": contact_id,
            "is_joined": bool(d.get("is_joined")),
            "channel_id": d.get("channel_id"),
            "user_id": d.get("user_id"),
            "invoice": d.get("invoice_webhook"),
            "shipment": d.get("shipment_webhook"),
        },
    )
    return True


async def migrate_contact_channels(
    conn, schema: str, contact_id: int, source: CustomerSnapshot,
) -> int:
    """contact_contact_channels を DELETE → INSERT（customer_contact_channels からコピー）。"""
    await conn.execute(
        text(f"DELETE FROM {schema}.contact_contact_channels WHERE contact_id = :cid"),
        {"cid": contact_id},
    )
    for cc in source.contact_channels:
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.contact_contact_channels (
                    contact_id, channel, purpose, is_primary
                ) VALUES (
                    :cid, :channel, :purpose, :is_primary
                )
            """),
            {
                "cid": contact_id,
                "channel": cc["channel"],
                "purpose": cc.get("purpose"),
                "is_primary": bool(cc.get("is_primary")),
            },
        )
    return len(source.contact_channels)


async def upsert_migration_map(
    conn, schema: str, old_customer_id: int, new_company_id: int, new_contact_id: int,
    method: str, notes: str,
) -> None:
    """_customer_migration_map UPSERT。"""
    await conn.execute(
        text(f"""
            INSERT INTO {schema}._customer_migration_map (
                old_customer_id, new_company_id, new_contact_id, migration_method, notes
            ) VALUES (
                :old_id, :new_co, :new_ct, :method, :notes
            )
            ON CONFLICT (old_customer_id) DO UPDATE SET
                new_company_id = EXCLUDED.new_company_id,
                new_contact_id = EXCLUDED.new_contact_id,
                migration_method = EXCLUDED.migration_method,
                notes = EXCLUDED.notes,
                migrated_at = NOW()
        """),
        {
            "old_id": old_customer_id,
            "new_co": new_company_id,
            "new_ct": new_contact_id,
            "method": method,
            "notes": notes or None,
        },
    )


# =============================================================================
# main
# =============================================================================

async def get_tenant_info(engine, tenant_code: str) -> tuple[int, str]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code AND is_active = true"),
            {"code": tenant_code},
        )
        row = result.first()
        if not row:
            raise RuntimeError(f"テナント '{tenant_code}' が見つからないか無効です")
        return row.id, f"tenant_{row.id:03d}"


async def main() -> None:
    logger.info("=" * 72)
    logger.info("Phase 1-B-2 Step 3: customers → companies/contacts 移行開始")
    logger.info("tenant_code=%s, manual_map=%s", TENANT_CODE, MANUAL_MAP_CSV)
    logger.info("=" * 72)

    manual_map = load_manual_map()
    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        tenant_id, schema = await get_tenant_info(engine, TENANT_CODE)
        logger.info("対象テナント: id=%d, schema=%s", tenant_id, schema)

        async with engine.begin() as conn:
            await conn.execute(text(f"SET search_path = {schema}, public"))
            await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

            # 1. 全 customers + 副テーブル取得
            customers = await fetch_all_customers(conn, schema, tenant_id)
            if not customers:
                logger.warning("customers が 0 件です。移行するデータがありません。")
                return

            # 2. グループ化
            groups = group_customers(customers, manual_map)

            # 3. 各グループを migrate
            companies_created = 0
            contacts_created = 0
            addresses_inserted = 0
            sales_channels_inserted = 0
            discord_migrated = 0
            contact_channels_inserted = 0

            for idx, group in enumerate(groups, start=1):
                company_code = f"CO-{idx:05d}"
                method = group.migration_method()
                notes_parts = []
                if group.manual_notes:
                    notes_parts.append(group.manual_notes)
                notes_parts.append(
                    f"merged_from={','.join(m.customer_code for m in group.members)}"
                )
                notes = "\n".join(notes_parts)

                # company
                company_id = await upsert_company(conn, schema, tenant_id, company_code, group.leader, group)
                companies_created += 1

                # 副: addresses, sales_channels
                addresses_inserted += await migrate_addresses(conn, schema, company_id, group)
                sales_channels_inserted += await migrate_sales_channels(conn, schema, company_id, group)

                # contacts（各 customer → 1 contact、leader のみ primary）
                for i, member in enumerate(group.members):
                    contact_id = await upsert_contact(
                        conn, schema, tenant_id, company_id, member, is_primary=(i == 0),
                    )
                    contacts_created += 1
                    if await migrate_contact_discord(conn, schema, contact_id, member):
                        discord_migrated += 1
                    contact_channels_inserted += await migrate_contact_channels(conn, schema, contact_id, member)
                    await upsert_migration_map(
                        conn, schema,
                        old_customer_id=member.id,
                        new_company_id=company_id,
                        new_contact_id=contact_id,
                        method=method,
                        notes=notes,
                    )

                logger.info(
                    "  ✓ %s [%s] '%s' (size=%d, method=%s)",
                    company_code,
                    group.merge_type or "-",
                    choose_company_name(group.leader),
                    group.size,
                    method,
                )

            logger.info("=" * 72)
            logger.info("✓ 移行完了:")
            logger.info("  companies:              %d", companies_created)
            logger.info("  contacts:               %d", contacts_created)
            logger.info("  company_addresses:      %d", addresses_inserted)
            logger.info("  company_sales_channels: %d", sales_channels_inserted)
            logger.info("  contact_discord:        %d", discord_migrated)
            logger.info("  contact_contact_channels: %d", contact_channels_inserted)
            logger.info("=" * 72)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

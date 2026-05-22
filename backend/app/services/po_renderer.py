"""PO PDF レンダラ (Sprint 8 / F8)

設計:
  - 内部表示は標準名 (public.products.name)、PDF / メール出力時のみ
    public.supplier_aliases.alias_text で置換 (該当 supplier_id × product_id、
    言語 = supplier.default_language を優先)。
  - 宛名: supplier_type で 「{name} 御中」(corporate) / 「{name} 様」(individual)
    (A4 確定)。
  - 差出人: {tenant_xxx}.tenant_profile から会社名・住所・連絡先 (A6 確定)。
  - alias 未登録の商品は標準名 + PDF 末尾 Notes 欄に「alias 未登録:」列挙。

依存:
  reportlab (PDF 生成、純 Python)
  日本語フォント: 環境変数 PO_PDF_FONT_PATH があればそれを使う。
                  なければ reportlab 標準 Helvetica にフォールバックし、
                  英 alias / 英 supplier_name_en を優先する (AC8.4 連携)。

呼出元:
  backend/app/routers/purchase_orders.py (PDF download endpoint)
  backend/app/services/po_mailer.py (添付 PDF メール送信)

関連:
  .claude-pipeline/spec.md F8 / AC8.1 / AC8.3 / AC8.4 / AC8.7 / AC8.8
  migrations/057_create_supplier_aliases.sql (alias 解決)
  migrations/069_create_tenant_profile.sql (差出人源泉)
  migrations/063_tenant_rbac_extensions.sql (snapshot 列)
"""
from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# フォント登録 (モジュール ロード時に 1 回だけ)
# ─────────────────────────────────────────────────────────────────────

_FONT_NAME_JA = "POJapaneseFont"
_FONT_NAME_FALLBACK = "Helvetica"
_FONT_REGISTERED: Optional[str] = None  # 実際に使えるフォント名 (ja / Helvetica)


def _register_japanese_font() -> str:
    """日本語フォントを登録し、登録名を返す。

    PO_PDF_FONT_PATH が指定されていればそれを使う。
    候補: NotoSansCJK-Regular.ttc / ipagp.ttf / ヒラギノ等。
    見つからない場合は Helvetica にフォールバック (日本語は ?? に化けるが
    PDF 生成は止めない、AC8.4 では英 alias を優先するため許容)。
    """
    global _FONT_REGISTERED
    if _FONT_REGISTERED is not None:
        return _FONT_REGISTERED

    candidates = []
    if env_path := os.getenv("PO_PDF_FONT_PATH"):
        candidates.append(env_path)
    # 一般的な日本語 TTF パス (Docker image / VPS)
    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/ipafont/ipagp.ttf",
        "/usr/share/fonts/truetype/ipafont-gothic/ipag.ttf",
        # macOS (開発機)
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(_FONT_NAME_JA, path))
            _FONT_REGISTERED = _FONT_NAME_JA
            logger.info("[po_renderer] registered japanese font: %s", path)
            return _FONT_NAME_JA
        except Exception as e:  # noqa: BLE001
            logger.warning("[po_renderer] failed to register font %s: %s", path, e)
            continue

    _FONT_REGISTERED = _FONT_NAME_FALLBACK
    logger.warning(
        "[po_renderer] no Japanese font found, using Helvetica fallback. "
        "Set PO_PDF_FONT_PATH to enable Japanese rendering."
    )
    return _FONT_NAME_FALLBACK


# ─────────────────────────────────────────────────────────────────────
# データクラス (純粋関数の引数として使う)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TenantProfile:
    company_name: Optional[str] = None
    company_name_en: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    seal_image_url: Optional[str] = None
    default_language: str = "ja"


@dataclass
class SupplierInfo:
    id: int
    name: str
    name_en: Optional[str] = None
    supplier_type: str = "corporate"  # 'corporate' | 'individual'
    default_language: str = "ja"
    email: Optional[str] = None


@dataclass
class POItemForRender:
    product_id: int
    standard_name: str  # public.products.name (内部標準名)
    alias_text: Optional[str]  # supplier_aliases.alias_text (該当言語、無ければ None)
    quantity: int
    unit_cost: float
    subtotal: float


@dataclass
class PODataForRender:
    po_id: int
    po_number: str
    total_amount: float
    notes: Optional[str]
    ordered_at: Optional[str]
    supplier: SupplierInfo
    tenant: TenantProfile
    items: list[POItemForRender]
    unregistered_aliases: list[str] = field(default_factory=list)  # AC8.3


# ─────────────────────────────────────────────────────────────────────
# データ取得 (DB アクセス)
# ─────────────────────────────────────────────────────────────────────

async def gather_po_render_data(
    db: AsyncSession,
    po_id: int,
    tenant_schema: str,
) -> PODataForRender:
    """PO レンダリングに必要な全データを取得する。

    Args:
        db: AsyncSession (tenant search_path 設定済)
        po_id: {tenant_xxx}.purchase_orders.id
        tenant_schema: テナントスキーマ名 (e.g. "tenant_006")

    Returns:
        PODataForRender (alias 解決 / 敬称 / 差出人すべて埋まった状態)
    """
    # 1. PO 本体 + items (テナント schema)
    po_row = (await db.execute(
        text(f"""
            SELECT id, po_number, supplier_id, status, total_amount,
                   notes, ordered_at
            FROM {tenant_schema}.purchase_orders
            WHERE id = :id
        """),
        {"id": po_id},
    )).mappings().first()
    if not po_row:
        raise ValueError(f"PO not found: id={po_id} in {tenant_schema}")

    item_rows = (await db.execute(
        text(f"""
            SELECT product_id, quantity, unit_cost, subtotal
            FROM {tenant_schema}.purchase_order_items
            WHERE purchase_order_id = :pid
            ORDER BY sort_order, id
        """),
        {"pid": po_id},
    )).mappings().all()

    # 2. supplier 解決 (まず tenant 側 suppliers から supplier_code 取得、
    #    public.suppliers にあれば優先、無ければ tenant 情報で代替)
    tenant_supplier_row = (await db.execute(
        text(f"SELECT supplier_code, name, email FROM {tenant_schema}.suppliers WHERE id = :sid"),
        {"sid": po_row["supplier_id"]},
    )).mappings().first()
    supplier_code = tenant_supplier_row["supplier_code"] if tenant_supplier_row else None

    public_supplier_row = None
    if supplier_code:
        public_supplier_row = (await db.execute(
            text("""
                SELECT id, name, supplier_type, default_language, email
                FROM public.suppliers
                WHERE supplier_code = :code AND is_active = TRUE
                LIMIT 1
            """),
            {"code": supplier_code},
        )).mappings().first()
    if public_supplier_row:
        supplier = SupplierInfo(
            id=public_supplier_row["id"],
            name=public_supplier_row["name"],
            supplier_type=public_supplier_row["supplier_type"] or "corporate",
            default_language=public_supplier_row["default_language"] or "ja",
            email=public_supplier_row["email"],
        )
    else:
        # public.suppliers にプロモートされていない fallback
        supplier = SupplierInfo(
            id=po_row["supplier_id"],
            name=(tenant_supplier_row["name"] if tenant_supplier_row else f"Supplier #{po_row['supplier_id']}"),
            supplier_type="corporate",
            default_language="ja",
            email=tenant_supplier_row["email"] if tenant_supplier_row else None,
        )

    # 3. tenant_profile (差出人)
    tp_row = (await db.execute(
        text(f"""
            SELECT company_name, company_name_en, address, phone, email,
                   website, seal_image_url, default_language
            FROM {tenant_schema}.tenant_profile
            ORDER BY id LIMIT 1
        """),
    )).mappings().first()
    tenant = TenantProfile(
        company_name=tp_row["company_name"] if tp_row else None,
        company_name_en=tp_row["company_name_en"] if tp_row else None,
        address=tp_row["address"] if tp_row else None,
        phone=tp_row["phone"] if tp_row else None,
        email=tp_row["email"] if tp_row else None,
        website=tp_row["website"] if tp_row else None,
        seal_image_url=tp_row["seal_image_url"] if tp_row else None,
        default_language=tp_row["default_language"] if tp_row else "ja",
    )

    # 4. items の alias 解決 (public.supplier_aliases から該当 supplier_id ×
    #    product_id × language で SELECT、無ければ標準名 + unregistered list へ)
    items: list[POItemForRender] = []
    unregistered: list[str] = []
    lang = supplier.default_language or "ja"

    for ir in item_rows:
        prod_id = ir["product_id"]
        # 標準名は public.products から、無ければ「(未登録 商品 #N)」
        prod_row = (await db.execute(
            text("SELECT name, name_en FROM public.products WHERE id = :pid"),
            {"pid": prod_id},
        )).mappings().first() if prod_id else None
        if prod_row:
            standard_name = prod_row["name"] if lang == "ja" else (prod_row["name_en"] or prod_row["name"])
        else:
            standard_name = f"商品 #{prod_id}"

        # alias 解決: 該当 supplier × product × language を最優先、
        # 同 supplier × product で別 language を fallback
        alias_row = (await db.execute(
            text("""
                SELECT alias_text, language
                FROM public.supplier_aliases
                WHERE supplier_id = :sid AND product_id = :pid
                ORDER BY (language = :lang) DESC, id
                LIMIT 1
            """),
            {"sid": supplier.id, "pid": prod_id, "lang": lang},
        )).mappings().first()

        alias_text = alias_row["alias_text"] if alias_row else None
        if alias_text is None:
            unregistered.append(standard_name)

        items.append(POItemForRender(
            product_id=prod_id,
            standard_name=standard_name,
            alias_text=alias_text,
            quantity=ir["quantity"],
            unit_cost=float(ir["unit_cost"] or 0),
            subtotal=float(ir["subtotal"] or 0),
        ))

    return PODataForRender(
        po_id=po_row["id"],
        po_number=po_row["po_number"] or f"PO-{po_row['id']:05d}",
        total_amount=float(po_row["total_amount"] or 0),
        notes=po_row["notes"],
        ordered_at=po_row["ordered_at"].isoformat() if po_row["ordered_at"] else None,
        supplier=supplier,
        tenant=tenant,
        items=items,
        unregistered_aliases=unregistered,
    )


# ─────────────────────────────────────────────────────────────────────
# 純粋関数: PDF レンダリング
# ─────────────────────────────────────────────────────────────────────

def format_supplier_addressee(supplier: SupplierInfo) -> str:
    """A4 敬称分岐 (AC8.8): corporate → 御中 / individual → 様"""
    name = supplier.name_en if supplier.default_language != "ja" and supplier.name_en else supplier.name
    if supplier.supplier_type == "individual":
        # 言語によらず 様 を使う (en でも Mr./Ms. でなく「様」が日系商習慣デフォルト、
        # 必要なら i18n 化、本 Sprint では「様」固定)
        return f"{name} 様"
    return f"{name} 御中"


def display_name_for_pdf(item: POItemForRender) -> str:
    """PDF / メール表示用の商品名: alias_text 優先、なければ標準名 (AC8.3)。"""
    return item.alias_text or item.standard_name


def render_po_pdf(data: PODataForRender) -> bytes:
    """PO PDF を bytes で返す (純粋関数、I/O なし、テスト容易)。

    レイアウト (A4 縦):
      - 上: 差出人 (tenant_profile)
      - 中央上: タイトル "発注書 / Purchase Order" + PO 番号
      - 左: 宛先 (supplier 敬称付き)
      - 表: items (display_name / qty / unit_cost / subtotal)
      - 末尾: total + notes + 「alias 未登録」列挙 (unregistered)
    """
    font = _register_japanese_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    y = height - 20 * mm

    # ── 1. 差出人 (テナント) ──
    c.setFont(font, 11)
    if data.tenant.company_name:
        c.drawString(20 * mm, y, f"発行: {data.tenant.company_name}")
        y -= 6 * mm
    if data.tenant.address:
        c.setFont(font, 9)
        c.drawString(20 * mm, y, data.tenant.address)
        y -= 5 * mm
    contact_parts = []
    if data.tenant.phone:
        contact_parts.append(f"TEL: {data.tenant.phone}")
    if data.tenant.email:
        contact_parts.append(f"Email: {data.tenant.email}")
    if contact_parts:
        c.setFont(font, 9)
        c.drawString(20 * mm, y, "  ".join(contact_parts))
        y -= 5 * mm
    if data.tenant.website:
        c.setFont(font, 9)
        c.drawString(20 * mm, y, f"Web: {data.tenant.website}")
        y -= 5 * mm

    # ── 2. タイトル + PO 番号 ──
    y -= 8 * mm
    c.setFont(font, 18)
    c.drawCentredString(width / 2, y, "発注書 / Purchase Order")
    y -= 8 * mm
    c.setFont(font, 11)
    c.drawCentredString(width / 2, y, f"PO番号: {data.po_number}")
    y -= 4 * mm
    if data.ordered_at:
        c.setFont(font, 9)
        c.drawCentredString(width / 2, y, f"発注日: {data.ordered_at[:10]}")
        y -= 6 * mm
    else:
        y -= 4 * mm

    # ── 3. 宛先 (supplier 敬称付き、AC8.8) ──
    y -= 4 * mm
    c.setFont(font, 14)
    c.drawString(20 * mm, y, format_supplier_addressee(data.supplier))
    y -= 8 * mm

    # ── 4. 明細表 ──
    c.setFont(font, 10)
    c.drawString(20 * mm, y, "商品名")
    c.drawRightString(120 * mm, y, "数量")
    c.drawRightString(150 * mm, y, "単価")
    c.drawRightString(190 * mm, y, "小計")
    y -= 2 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 5 * mm

    for item in data.items:
        if y < 40 * mm:
            c.showPage()
            c.setFont(font, 10)
            y = height - 20 * mm
        display_name = display_name_for_pdf(item)
        # 長すぎる名前は折り返し (簡易、最大 50 文字)
        if len(display_name) > 50:
            display_name = display_name[:47] + "..."
        c.drawString(20 * mm, y, display_name)
        c.drawRightString(120 * mm, y, str(item.quantity))
        c.drawRightString(150 * mm, y, f"¥{item.unit_cost:,.0f}")
        c.drawRightString(190 * mm, y, f"¥{item.subtotal:,.0f}")
        y -= 5 * mm

    # ── 5. 合計 ──
    y -= 4 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont(font, 12)
    c.drawRightString(150 * mm, y, "合計 / Total:")
    c.drawRightString(190 * mm, y, f"¥{data.total_amount:,.0f}")
    y -= 10 * mm

    # ── 6. Notes (本文 + AC8.3 「alias 未登録」列挙) ──
    if data.notes:
        c.setFont(font, 10)
        c.drawString(20 * mm, y, "備考 / Notes:")
        y -= 5 * mm
        c.setFont(font, 9)
        for line in data.notes.split("\n"):
            if y < 30 * mm:
                c.showPage()
                c.setFont(font, 9)
                y = height - 20 * mm
            c.drawString(22 * mm, y, line[:90])
            y -= 4 * mm

    if data.unregistered_aliases:
        y -= 4 * mm
        c.setFont(font, 9)
        c.drawString(20 * mm, y, "※ alias 未登録 / unregistered alias:")
        y -= 4 * mm
        for std_name in data.unregistered_aliases:
            if y < 25 * mm:
                c.showPage()
                c.setFont(font, 9)
                y = height - 20 * mm
            c.drawString(22 * mm, y, f"  - {std_name}")
            y -= 4 * mm

    c.save()
    return buf.getvalue()


async def render_po_pdf_for(
    db: AsyncSession, po_id: int, tenant_schema: str
) -> tuple[bytes, PODataForRender]:
    """便利関数: data 取得 + PDF 生成を 1 ステップで。"""
    data = await gather_po_render_data(db, po_id, tenant_schema)
    pdf = render_po_pdf(data)
    return pdf, data


def build_email_subject_and_body(data: PODataForRender) -> tuple[str, str]:
    """件名 / 本文を生成。alias_text のみ含み、標準名は含まない (AC8.2)。"""
    addressee = format_supplier_addressee(data.supplier)
    # 件名
    subject = f"【発注書】{data.tenant.company_name or 'Sales Anchor'} {data.po_number}"
    # 本文: 商品リストは alias_text 優先 (alias 無ければ標準名)、AC8.2 では標準名なし
    lines = [
        addressee,
        "",
        "いつもお世話になっております。",
        f"{data.tenant.company_name or '弊社'} です。",
        "",
        "下記内容にて発注させていただきます。",
        "添付の発注書 PDF をご確認ください。",
        "",
        f"発注番号: {data.po_number}",
        f"合計金額: ¥{data.total_amount:,.0f}",
        "",
        "発注内容:",
    ]
    for item in data.items:
        # alias_text を最優先 (AC8.2: 標準名は含まない)
        name = item.alias_text or item.standard_name
        lines.append(f"  - {name} × {item.quantity}")
    lines.append("")
    if data.tenant.company_name:
        lines.append(f"-- {data.tenant.company_name}")
    if data.tenant.phone:
        lines.append(f"   TEL: {data.tenant.phone}")
    if data.tenant.email:
        lines.append(f"   Email: {data.tenant.email}")
    return subject, "\n".join(lines)

/**
 * 見積もり作成ページ。
 * 顧客選択 + 明細行追加 + 送料自動計算 → draft で保存。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 *   2026-04-25: Phase 1-B-2 Step 5c-3 — 顧客セレクタを CompanyContactSelector
 *     （company + contact）に置換。
 *   2026-05-22: Sprint 7 / F7 — 既存 <select> ベースの商品選択を InventorySearchBar
 *     (全 7 種横断 + AND/OR + 在庫マスク対応) に置換。標準名は
 *     public.products.name (旧 tenant スキーマの name_ja とは別) を採用 (AC7.4)。
 */

import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import CompanyContactSelector from "../components/CompanyContactSelector";
import InventorySearchBar, { InventorySearchCandidate } from "../components/InventorySearchBar";

interface LineItem {
  product_id: number | null;
  product_name: string;
  quantity: number;
  unit_price: number;
  weight: number | null;
  /** AC7.5: 在庫 0 商品を選択した行はフラグでマークし、確認 UI を出す。 */
  zero_stock_warning?: boolean;
}

export default function QuoteCreatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [contactId, setContactId] = useState<number | null>(null);
  const [selectorError, setSelectorError] = useState("");
  const [currency, setCurrency] = useState("JPY");
  const [shippingFee, setShippingFee] = useState("");
  const [taxAmount, setTaxAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<LineItem[]>([{ product_id: null, product_name: "", quantity: 1, unit_price: 0, weight: null }]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const addItem = () => {
    setItems([...items, { product_id: null, product_name: "", quantity: 1, unit_price: 0, weight: null }]);
  };

  const removeItem = (index: number) => {
    if (items.length <= 1) return;
    setItems(items.filter((_, i) => i !== index));
  };

  const updateItem = (index: number, field: keyof LineItem, value: unknown) => {
    const newItems = [...items];
    (newItems[index] as unknown as Record<string, unknown>)[field] = value;
    setItems(newItems);
  };

  /**
   * InventorySearchBar から選択された商品で対象行を上書きする (AC7.4)。
   * 標準名 (public.products.name) と標準 unit_price を採用する。
   */
  const onPickProduct = (index: number, c: InventorySearchCandidate) => {
    const newItems = [...items];
    newItems[index] = {
      product_id: c.product_id,
      product_name: c.name, // AC7.4: 標準名 (public.products.name)
      quantity: 1,
      unit_price: c.unit_price ?? 0,
      weight: null,
      zero_stock_warning:
        c.stock_quantity !== null && c.stock_quantity <= 0,
    };
    setItems(newItems);
  };

  const subtotal = items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
  const shipping = shippingFee ? Number(shippingFee) : 0;
  const tax = taxAmount ? Number(taxAmount) : 0;
  const total = subtotal + shipping + tax;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSelectorError("");
    if (contactId === null) { setSelectorError(t("companyContactSelector.contactRequired")); return; }
    if (items.some((i) => !i.product_name || i.unit_price <= 0)) {
      setError("各明細行に商品名と単価を入力してください");
      return;
    }
    setSaving(true);
    try {
      await api.post("/quotes", {
        company_id: companyId,
        contact_id: contactId,
        currency,
        shipping_fee: shipping || null,
        tax_amount: tax || null,
        notes: notes || null,
        items: items.map((i) => ({
          product_id: i.product_id,
          product_name: i.product_name,
          quantity: i.quantity,
          unit_price: i.unit_price,
          weight: i.weight,
        })),
      });
      navigate("/quotes");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("quotes.newQuote")}</h2>
      </div>

      {error && <div className="error-message">{error}</div>}

      <form onSubmit={handleSubmit} style={{ background: "var(--bg-surface)", padding: 24, borderRadius: 8, boxShadow: "var(--shadow-sm)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <CompanyContactSelector
            value={{ companyId, contactId }}
            onChange={({ companyId: c, contactId: ct }) => {
              setCompanyId(c);
              setContactId(ct);
            }}
            required
            error={selectorError}
          />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
          <div className="form-group"><label>{t("common.currency")}</label>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="JPY">JPY</option>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
          <div className="form-group"><label>{t("common.notes")}</label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>

        <h3 style={{ marginBottom: 12 }}>{t("quotes.items")}</h3>
        <div style={{ overflowX: "auto", marginBottom: 16 }}>
          <table className="data-table" style={{ minWidth: 720 }}>
            <thead>
              <tr>
                <th>{t("quotes.selectProduct")}</th>
                <th>{t("quotes.product")}</th>
                <th>{t("quotes.quantity")}</th>
                <th>{t("quotes.unitPrice")}</th>
                <th>{t("quotes.weight")}</th>
                <th>{t("quotes.subtotal")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => (
                <tr key={i} data-testid={`quote-item-row-${i}`}>
                  <td style={{ minWidth: 280 }}>
                    <InventorySearchBar
                      onSelect={(c) => onPickProduct(i, c)}
                      testIdPrefix={`quote-inventory-search-${i}`}
                    />
                    {item.zero_stock_warning && (
                      <div
                        data-testid={`quote-item-row-${i}-zero-stock-warning`}
                        className="warning-message"
                        style={{ marginTop: 4, color: "var(--color-warning)", fontSize: "0.85em" }}
                      >
                        {t("inventory.search.zeroStockWarning", { name: item.product_name })}
                      </div>
                    )}
                  </td>
                  <td>
                    <input value={item.product_name} onChange={(e) => updateItem(i, "product_name", e.target.value)} style={{ minWidth: 120, maxWidth: "100%" }} data-testid={`quote-item-row-${i}-name`} />
                  </td>
                  <td>
                    <input type="number" min="1" value={item.quantity} onChange={(e) => updateItem(i, "quantity", Number(e.target.value))} style={{ width: 70 }} />
                  </td>
                  <td>
                    <input type="number" min="0" step="0.01" value={item.unit_price} onChange={(e) => updateItem(i, "unit_price", Number(e.target.value))} style={{ width: 90 }} />
                  </td>
                  <td>
                    <input type="number" min="0" step="0.001" value={item.weight || ""} onChange={(e) => updateItem(i, "weight", e.target.value ? Number(e.target.value) : null)} style={{ width: 80 }} />
                  </td>
                  <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{(item.quantity * item.unit_price).toLocaleString()}</td>
                  <td>
                    {items.length > 1 && (
                      <button type="button" className="btn-sm btn-danger" onClick={() => removeItem(i)}>{t("quotes.removeItem")}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="btn-secondary" onClick={addItem} style={{ marginBottom: 24 }}>{t("quotes.addItem")}</button>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
          <div className="form-group"><label>{t("quotes.shippingFee")}</label>
            <input type="number" min="0" step="1" value={shippingFee} onChange={(e) => setShippingFee(e.target.value)} />
          </div>
          <div className="form-group"><label>{t("quotes.tax")}</label>
            <input type="number" min="0" step="1" value={taxAmount} onChange={(e) => setTaxAmount(e.target.value)} />
          </div>
          <div className="form-group"><label>{t("quotes.total")}</label>
            <div style={{ padding: "8px 12px", fontWeight: 700, fontSize: "1.1rem" }}>{total.toLocaleString()} {currency}</div>
          </div>
        </div>

        <div className="form-actions">
          <button type="button" className="btn-secondary" onClick={() => navigate("/quotes")}>{t("common.cancel")}</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? t("common.saving") : t("quotes.saveDraft")}</button>
        </div>
      </form>
    </div>
  );
}

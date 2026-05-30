/**
 * 請求書作成ページ (QA 2026-05-31)。2 つの導線:
 *   1. 在庫表から: ProductsPage でチェックした商品が location.state.selectedProducts で渡る。
 *      会社/担当を選び明細を調整して POST /invoices（直接作成）。
 *   2. 既存見積から: 自テナントの「承認済み」見積を選び POST /invoices/from-quote/{id}。
 *      見積は RLS により自テナント分のみ取得されるため、選択スコープは自テナント限定。
 *
 * 明細エディタは QuoteCreatePage と同等（将来は共通コンポーネント化を検討）。
 */
import { useState, useEffect, FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import CompanyContactSelector from "../../components/CompanyContactSelector";
import InventorySearchBar, {
  InventorySearchCandidate,
} from "../../components/InventorySearchBar";

interface LineItem {
  product_id: number | null;
  product_name: string;
  quantity: number;
  unit_price: number;
  weight: number | null;
  zero_stock_warning?: boolean;
}

interface SelectedProduct {
  product_id: number;
  product_name: string;
  unit_price: number | null;
}

interface QuoteSummary {
  id: number;
  quote_code: string;
  company_id: number;
  currency: string;
  total_amount: number | null;
  status: string;
  created_at: string;
}

// 通貨つきで金額を表示（null は "-"）。invoices/quotes 共通の見せ方に合わせる。
function fmtAmount(n: number | null, ccy: string): string {
  if (n == null) return "-";
  try {
    return n.toLocaleString("ja-JP", { style: "currency", currency: ccy });
  } catch {
    return `${ccy} ${Math.round(n).toLocaleString()}`;
  }
}

const blankItem: LineItem = {
  product_id: null,
  product_name: "",
  quantity: 1,
  unit_price: 0,
  weight: null,
};

export default function InvoiceCreatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const handoff = (
    location.state as { selectedProducts?: SelectedProduct[] } | null
  )?.selectedProducts;
  const hasHandoff = !!handoff && handoff.length > 0;

  // 在庫表から来た場合は inventory モード、そうでなければ既存見積から選ぶ quote モード
  const [mode, setMode] = useState<"inventory" | "quote">(
    hasHandoff ? "inventory" : "quote",
  );

  // --- inventory モード ---
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [contactId, setContactId] = useState<number | null>(null);
  const [selectorError, setSelectorError] = useState("");
  const [currency, setCurrency] = useState("JPY");
  const [shippingFee, setShippingFee] = useState("");
  const [taxAmount, setTaxAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<LineItem[]>(
    hasHandoff
      ? handoff!.map((p) => ({
          product_id: p.product_id,
          product_name: p.product_name,
          quantity: 1,
          unit_price: p.unit_price ?? 0,
          weight: null,
        }))
      : [{ ...blankItem }],
  );

  // --- quote モード ---
  const [quotes, setQuotes] = useState<QuoteSummary[]>([]);
  const [quotesLoading, setQuotesLoading] = useState(false);

  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (mode !== "quote") return;
    setQuotesLoading(true);
    setError("");
    // 承認済みのみ請求へ変換可能。自テナント分のみ RLS で返る。
    api
      .get<QuoteSummary[]>("/quotes?status=approved")
      .then(setQuotes)
      .catch((e) =>
        setError(e instanceof Error ? e.message : t("common.fetchError")),
      )
      .finally(() => setQuotesLoading(false));
  }, [mode, t]);

  const addItem = () => setItems([...items, { ...blankItem }]);
  const removeItem = (index: number) => {
    if (items.length <= 1) return;
    setItems(items.filter((_, i) => i !== index));
  };
  const updateItem = (index: number, field: keyof LineItem, value: unknown) => {
    const next = [...items];
    (next[index] as unknown as Record<string, unknown>)[field] = value;
    setItems(next);
  };
  const onPickProduct = (index: number, c: InventorySearchCandidate) => {
    const next = [...items];
    const isOutOfStock = c.stock_quantity !== null && c.stock_quantity <= 0;
    next[index] = {
      product_id: c.product_id,
      product_name: c.name,
      quantity: isOutOfStock ? 0 : 1,
      unit_price: c.unit_price ?? 0,
      weight: null,
      zero_stock_warning: isOutOfStock,
    };
    setItems(next);
  };

  const subtotal = items.reduce((s, it) => s + it.quantity * it.unit_price, 0);
  const shipping = shippingFee ? Number(shippingFee) : 0;
  const tax = taxAmount ? Number(taxAmount) : 0;
  const total = subtotal + shipping + tax;

  const submitInventory = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSelectorError("");
    if (contactId === null) {
      setSelectorError(t("companyContactSelector.contactRequired"));
      return;
    }
    if (items.some((i) => !i.product_name || i.unit_price <= 0 || i.quantity <= 0)) {
      setError(t("quotes.itemsRequired"));
      return;
    }
    setSaving(true);
    try {
      const inv = await api.post<{ id: number }>("/invoices", {
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
      navigate(`/invoices/${inv.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const createFromQuote = async (quoteId: number) => {
    setError("");
    setSaving(true);
    try {
      const inv = await api.post<{ id: number }>(
        `/invoices/from-quote/${quoteId}`,
        {},
      );
      navigate(`/invoices/${inv.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        {/* eslint-disable-next-line no-restricted-syntax -- 作成ページ(route param 無し)は navKey 制約対象外 */}
        <h2>{t("invoices.createTitle")}</h2>
        <button className="btn-secondary" onClick={() => navigate("/invoices")}>
          {t("common.back")}
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div style={{ display: "flex", gap: "var(--space-2)", margin: "var(--space-3) 0" }}>
        <button
          className={mode === "inventory" ? "btn-primary" : "btn-secondary"}
          onClick={() => setMode("inventory")}
          data-testid="invoice-mode-inventory"
        >
          {t("invoices.fromInventory")}
        </button>
        <button
          className={mode === "quote" ? "btn-primary" : "btn-secondary"}
          onClick={() => setMode("quote")}
          data-testid="invoice-mode-quote"
        >
          {t("invoices.fromQuote")}
        </button>
      </div>

      {mode === "quote" ? (
        <div data-testid="invoice-from-quote">
          <p style={{ color: "var(--text-secondary)" }}>
            {t("invoices.fromQuoteHelp")}
          </p>
          {quotesLoading ? (
            <div className="loading">{t("common.loading")}</div>
          ) : quotes.length === 0 ? (
            <div className="empty">{t("invoices.noApprovedQuotes")}</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("quotes.quoteCode")}</th>
                  <th>{t("quotes.total")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {quotes.map((q) => (
                  <tr key={q.id} data-testid={`invoice-quote-${q.id}`}>
                    <td>{q.quote_code}</td>
                    <td>{fmtAmount(q.total_amount, q.currency)}</td>
                    <td>
                      <button
                        className="btn-sm btn-primary"
                        disabled={saving}
                        onClick={() => createFromQuote(q.id)}
                      >
                        {t("invoices.createFromThisQuote")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <form
          onSubmit={submitInventory}
          style={{ background: "var(--bg-surface)", padding: "var(--space-6)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)" }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", marginBottom: "var(--space-6)" }}>
            <div className="form-group">
              <label>{t("common.currency")}</label>
              <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <option value="JPY">JPY</option>
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
              </select>
            </div>
            <div className="form-group">
              <label>{t("common.notes")}</label>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
          </div>

          <h3 style={{ marginBottom: "var(--space-3)" }}>{t("quotes.items")}</h3>
          <div style={{ overflowX: "auto", marginBottom: "var(--space-4)" }}>
            <table className="data-table" style={{ minWidth: "var(--table-min-width-base)" }}>
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
                  <tr key={i} data-testid={`invoice-item-row-${i}`}>
                    <td style={{ minWidth: "var(--table-col-min-width)" }}>
                      <InventorySearchBar
                        onSelect={(c) => onPickProduct(i, c)}
                        testIdPrefix={`invoice-inventory-search-${i}`}
                      />
                      {item.zero_stock_warning && (
                        <div
                          data-testid={`invoice-item-row-${i}-zero-stock-warning`}
                          className="warning-message"
                          style={{ marginTop: "var(--space-1)", color: "var(--color-warning)", fontSize: "var(--font-sm)" }}
                        >
                          {t("inventory.search.zeroStockWarning", { name: item.product_name })}
                        </div>
                      )}
                    </td>
                    <td style={{ minWidth: "var(--table-col-product-name-min-w)" }}>
                      <input value={item.product_name} onChange={(e) => updateItem(i, "product_name", e.target.value)} style={{ width: "100%", minWidth: "var(--input-width-product-name)" }} />
                    </td>
                    <td>
                      <input type="number" min="1" value={item.quantity} onChange={(e) => updateItem(i, "quantity", Number(e.target.value))} style={{ width: "var(--input-width-qty)" }} />
                    </td>
                    <td>
                      <input type="number" min="0" step="0.01" value={item.unit_price} onChange={(e) => updateItem(i, "unit_price", Number(e.target.value))} style={{ width: "var(--input-width-year)" }} />
                    </td>
                    <td>
                      <input type="number" min="0" step="0.001" value={item.weight || ""} onChange={(e) => updateItem(i, "weight", e.target.value ? Number(e.target.value) : null)} style={{ width: "var(--input-width-weight)" }} />
                    </td>
                    <td style={{ fontWeight: "var(--font-weight-semi)", whiteSpace: "nowrap" }}>{(item.quantity * item.unit_price).toLocaleString()}</td>
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
          <button type="button" className="btn-secondary" onClick={addItem} style={{ marginBottom: "var(--space-6)" }}>{t("quotes.addItem")}</button>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-4)", marginBottom: "var(--space-6)" }}>
            <div className="form-group">
              <label>{t("quotes.shippingFee")}</label>
              <input type="number" min="0" step="1" value={shippingFee} onChange={(e) => setShippingFee(e.target.value)} />
            </div>
            <div className="form-group">
              <label>{t("quotes.tax")}</label>
              <input type="number" min="0" step="1" value={taxAmount} onChange={(e) => setTaxAmount(e.target.value)} />
            </div>
            <div className="form-group">
              <label>{t("quotes.total")}</label>
              <div style={{ padding: "var(--space-2) var(--space-3)", fontWeight: "var(--font-weight-bold)", fontSize: "var(--font-lg)" }}>{total.toLocaleString()} {currency}</div>
            </div>
          </div>

          <div className="form-actions">
            <button type="button" className="btn-secondary" onClick={() => navigate("/invoices")}>{t("common.cancel")}</button>
            <button type="submit" className="btn-primary" disabled={saving}>{saving ? t("common.saving") : t("invoices.createBtn")}</button>
          </div>
        </form>
      )}
    </div>
  );
}

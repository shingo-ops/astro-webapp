/**
 * 見積もり作成ページ。
 * 顧客選択 + 明細行追加 + 送料自動計算 → draft で保存。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

interface Customer {
  id: number;
  customer_code: string;
  company_name: string | null;
  billing_display_name: string | null;
}
const customerLabel = (c: Customer): string =>
  c.billing_display_name || c.company_name || c.customer_code;
interface Product { id: number; product_code: string | null; name_ja: string; unit_price: number | null; weight: number | null; quantity: number; }

interface LineItem {
  product_id: number | null;
  product_name: string;
  quantity: number;
  unit_price: number;
  weight: number | null;
}

export default function QuoteCreatePage() {
  const navigate = useNavigate();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [currency, setCurrency] = useState("JPY");
  const [shippingFee, setShippingFee] = useState("");
  const [taxAmount, setTaxAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<LineItem[]>([{ product_id: null, product_name: "", quantity: 1, unit_price: 0, weight: null }]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<Customer[]>("/customers?per_page=200").then(setCustomers).catch(() => {});
    api.get<Product[]>("/products?per_page=200&status=active").then(setProducts).catch(() => {});
  }, []);

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

  const selectProduct = (index: number, productId: string) => {
    const prod = products.find((p) => p.id === Number(productId));
    if (prod) {
      const newItems = [...items];
      newItems[index] = {
        product_id: prod.id,
        product_name: prod.name_ja,
        quantity: 1,
        unit_price: prod.unit_price || 0,
        weight: prod.weight,
      };
      setItems(newItems);
    }
  };

  const subtotal = items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
  const shipping = shippingFee ? Number(shippingFee) : 0;
  const tax = taxAmount ? Number(taxAmount) : 0;
  const total = subtotal + shipping + tax;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!customerId) { setError("顧客を選択してください"); return; }
    if (items.some((i) => !i.product_name || i.unit_price <= 0)) {
      setError("各明細行に商品名と単価を入力してください");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.post("/quotes", {
        customer_id: Number(customerId),
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
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>見積もり作成</h2>
      </div>

      {error && <div className="error-message">{error}</div>}

      <form onSubmit={handleSubmit} style={{ background: "var(--bg-surface)", padding: 24, borderRadius: 8, boxShadow: "var(--shadow-sm)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
          <div className="form-group"><label>顧客 *</label>
            <select required value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              <option value="">選択してください</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{customerLabel(c)}</option>)}
            </select>
          </div>
          <div className="form-group"><label>通貨</label>
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option value="JPY">JPY</option>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
          <div className="form-group"><label>備考</label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>

        <h3 style={{ marginBottom: 12 }}>明細行</h3>
        <table className="data-table" style={{ marginBottom: 16 }}>
          <thead>
            <tr>
              <th>商品選択</th>
              <th>商品名</th>
              <th>数量</th>
              <th>単価</th>
              <th>重量(kg)</th>
              <th>小計</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr key={i}>
                <td>
                  <select value={item.product_id || ""} onChange={(e) => selectProduct(i, e.target.value)} style={{ minWidth: 120 }}>
                    <option value="">手入力</option>
                    {products.map((p) => <option key={p.id} value={p.id}>{p.name_ja} (在庫:{p.quantity})</option>)}
                  </select>
                </td>
                <td>
                  <input value={item.product_name} onChange={(e) => updateItem(i, "product_name", e.target.value)} style={{ minWidth: 150 }} />
                </td>
                <td>
                  <input type="number" min="1" value={item.quantity} onChange={(e) => updateItem(i, "quantity", Number(e.target.value))} style={{ width: 70 }} />
                </td>
                <td>
                  <input type="number" min="0" step="0.01" value={item.unit_price} onChange={(e) => updateItem(i, "unit_price", Number(e.target.value))} style={{ width: 100 }} />
                </td>
                <td>
                  <input type="number" min="0" step="0.001" value={item.weight || ""} onChange={(e) => updateItem(i, "weight", e.target.value ? Number(e.target.value) : null)} style={{ width: 80 }} />
                </td>
                <td style={{ fontWeight: 600 }}>{(item.quantity * item.unit_price).toLocaleString()}</td>
                <td>
                  {items.length > 1 && (
                    <button type="button" className="btn-sm btn-danger" onClick={() => removeItem(i)}>-</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="btn-secondary" onClick={addItem} style={{ marginBottom: 24 }}>+ 行追加</button>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
          <div className="form-group"><label>送料</label>
            <input type="number" min="0" step="1" value={shippingFee} onChange={(e) => setShippingFee(e.target.value)} />
          </div>
          <div className="form-group"><label>税額</label>
            <input type="number" min="0" step="1" value={taxAmount} onChange={(e) => setTaxAmount(e.target.value)} />
          </div>
          <div className="form-group"><label>合計</label>
            <div style={{ padding: "8px 12px", fontWeight: 700, fontSize: "1.1rem" }}>{total.toLocaleString()} {currency}</div>
          </div>
        </div>

        <div className="form-actions">
          <button type="button" className="btn-secondary" onClick={() => navigate("/quotes")}>キャンセル</button>
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? "保存中..." : "下書き保存"}</button>
        </div>
      </form>
    </div>
  );
}

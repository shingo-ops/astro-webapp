/**
 * 商品・在庫管理ページ。
 * 商品マスタのCRUD + 在庫数表示。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

interface Product {
  id: number;
  product_code: string | null;
  name_ja: string;
  name_en: string | null;
  category: string | null;
  mark: string | null;
  status: string;
  condition: string | null;
  unit_price: number | null;
  quantity: number;
  weight: number | null;
  notes: string | null;
  release_date: string | null;
  created_at: string;
  updated_at: string;
}

type FormState = {
  name_ja: string;
  name_en: string;
  category: string;
  mark: string;
  status: string;
  condition: string;
  unit_price: string;
  quantity: string;
  weight: string;
  notes: string;
};

const emptyForm: FormState = {
  name_ja: "", name_en: "", category: "", mark: "",
  status: "active", condition: "", unit_price: "", quantity: "0",
  weight: "", notes: "",
};

export default function ProductsPage() {
  const { hasPermission } = usePermissions();
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);

  const load = async () => {
    try {
      const params = search ? `?search=${encodeURIComponent(search)}` : "";
      const data = await api.get<Product[]>(`/products${params}`);
      setProducts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [search]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const toNull = (v: string) => (v ? v : null);
    const payload = {
      name_ja: form.name_ja,
      name_en: toNull(form.name_en),
      category: toNull(form.category),
      mark: toNull(form.mark),
      status: form.status,
      condition: toNull(form.condition),
      unit_price: form.unit_price ? Number(form.unit_price) : null,
      quantity: Number(form.quantity),
      weight: form.weight ? Number(form.weight) : null,
      notes: toNull(form.notes),
    };
    try {
      if (editId) {
        await api.patch(`/products/${editId}`, payload);
      } else {
        await api.post("/products", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (p: Product) => {
    setEditId(p.id);
    setForm({
      name_ja: p.name_ja,
      name_en: p.name_en || "",
      category: p.category || "",
      mark: p.mark || "",
      status: p.status,
      condition: p.condition || "",
      unit_price: p.unit_price != null ? String(p.unit_price) : "",
      quantity: String(p.quantity),
      weight: p.weight != null ? String(p.weight) : "",
      notes: p.notes || "",
    });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/products/${id}`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>在庫管理</h2>
        {hasPermission("products.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>商品登録</button>
        )}
      </div>

      <div className="search-bar">
        <input type="text" placeholder="商品名・コード・マークで検索..." value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "商品編集" : "商品登録"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>商品名（日本語） *</label>
                <input required value={form.name_ja} onChange={(e) => setForm({ ...form, name_ja: e.target.value })} />
              </div>
              <div className="form-group"><label>商品名（英語）</label>
                <input value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
              </div>
              <div className="form-group"><label>カテゴリ</label>
                <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
              </div>
              <div className="form-group"><label>マーク / SKU</label>
                <input value={form.mark} onChange={(e) => setForm({ ...form, mark: e.target.value })} />
              </div>
              <div className="form-group"><label>状態</label>
                <input placeholder="例: 新品、中古" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })} />
              </div>
              <div className="form-group"><label>単価</label>
                <input type="number" min="0" step="0.01" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
              </div>
              <div className="form-group"><label>在庫数量</label>
                <input type="number" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
              </div>
              <div className="form-group"><label>重量 (kg)</label>
                <input type="number" min="0" step="0.001" value={form.weight} onChange={(e) => setForm({ ...form, weight: e.target.value })} />
              </div>
              <div className="form-group"><label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="active">有効</option>
                  <option value="discontinued">廃盤</option>
                </select>
              </div>
              <div className="form-group"><label>備考</label>
                <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">{editId ? "更新" : "登録"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>コード</th>
              <th>商品名</th>
              <th>カテゴリ</th>
              <th>マーク</th>
              <th>単価</th>
              <th>在庫</th>
              <th>ステータス</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td className="mono">{p.product_code || "-"}</td>
                <td>{p.name_ja}</td>
                <td>{p.category || "-"}</td>
                <td>{p.mark || "-"}</td>
                <td>{p.unit_price != null ? `¥${p.unit_price.toLocaleString()}` : "-"}</td>
                <td>
                  <span style={{ color: p.quantity <= 0 ? "var(--danger)" : "inherit", fontWeight: p.quantity <= 0 ? 600 : 400 }}>
                    {p.quantity}
                  </span>
                </td>
                <td><span className={`badge badge-${p.status === "active" ? "won" : "lost"}`}>{p.status === "active" ? "有効" : "廃盤"}</span></td>
                <td className="actions">
                  {hasPermission("products.update") && <button className="btn-sm" onClick={() => handleEdit(p)}>編集</button>}
                  {hasPermission("products.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(p)}>削除</button>}
                </td>
              </tr>
            ))}
            {products.length === 0 && <tr><td colSpan={8} className="empty">商品が登録されていません</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="商品を削除"
        message={<><strong>{deleteTarget?.name_ja}</strong> を削除します。<br />見積もり・請求書で参照されている場合は削除できません。</>}
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

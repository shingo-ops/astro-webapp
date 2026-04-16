/**
 * 顧客管理ページ。
 *
 * 変更履歴:
 *   2026-04-16: Phase 1拡張（請求先/配送先、顧客コード、ステータス表示）
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

const PHONE_RE = /^(\+?\d{10,15}|0\d{9,10})$/;
const validatePhoneClient = (raw: string): string | null => {
  if (!raw) return null;
  const cleaned = raw.replace(/[\s\-()]/g, "");
  return PHONE_RE.test(cleaned) ? null : "電話番号の形式が正しくありません（例: 03-1234-5678, 090-1234-5678）";
};

interface Customer {
  id: number;
  customer_code: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  registration_source: string | null;
  status: string | null;
  billing_name: string | null;
  billing_phone: string | null;
  billing_email: string | null;
  billing_address: string | null;
  delivery_name: string | null;
  delivery_phone: string | null;
  delivery_email: string | null;
  delivery_address: string | null;
  delivery_country: string | null;
  business_id: string | null;
  transaction_count: number | null;
  last_transaction_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

type FormState = {
  name: string;
  email: string;
  phone: string;
  company: string;
  registration_source: string;
  status: string;
  billing_name: string;
  billing_phone: string;
  billing_email: string;
  billing_address: string;
  delivery_name: string;
  delivery_phone: string;
  delivery_email: string;
  delivery_address: string;
  delivery_country: string;
  business_id: string;
  notes: string;
};

const emptyForm: FormState = {
  name: "", email: "", phone: "", company: "",
  registration_source: "", status: "active",
  billing_name: "", billing_phone: "", billing_email: "", billing_address: "",
  delivery_name: "", delivery_phone: "", delivery_email: "", delivery_address: "", delivery_country: "",
  business_id: "", notes: "",
};

type Tab = "basic" | "billing" | "delivery";

export default function CustomersPage() {
  const { hasPermission } = usePermissions();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [activeTab, setActiveTab] = useState<Tab>("basic");
  const [error, setError] = useState("");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);

  const loadCustomers = async () => {
    try {
      const params = search ? `?search=${encodeURIComponent(search)}` : "";
      const data = await api.get<Customer[]>(`/customers${params}`);
      setCustomers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadCustomers(); }, [search]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const phoneErr = validatePhoneClient(form.phone);
    if (phoneErr) {
      setPhoneError(phoneErr);
      return;
    }
    setPhoneError(null);
    const toNull = (v: string) => (v ? v : null);
    const payload: Record<string, unknown> = {
      name: form.name,
      email: toNull(form.email),
      phone: toNull(form.phone),
      company: toNull(form.company),
      registration_source: toNull(form.registration_source),
      status: form.status || "active",
      billing_name: toNull(form.billing_name),
      billing_phone: toNull(form.billing_phone),
      billing_email: toNull(form.billing_email),
      billing_address: toNull(form.billing_address),
      delivery_name: toNull(form.delivery_name),
      delivery_phone: toNull(form.delivery_phone),
      delivery_email: toNull(form.delivery_email),
      delivery_address: toNull(form.delivery_address),
      delivery_country: toNull(form.delivery_country),
      business_id: toNull(form.business_id),
      notes: toNull(form.notes),
    };
    try {
      if (editId) {
        await api.patch(`/customers/${editId}`, payload);
      } else {
        await api.post("/customers", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      setActiveTab("basic");
      loadCustomers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (c: Customer) => {
    setEditId(c.id);
    setForm({
      name: c.name,
      email: c.email || "",
      phone: c.phone || "",
      company: c.company || "",
      registration_source: c.registration_source || "",
      status: c.status || "active",
      billing_name: c.billing_name || "",
      billing_phone: c.billing_phone || "",
      billing_email: c.billing_email || "",
      billing_address: c.billing_address || "",
      delivery_name: c.delivery_name || "",
      delivery_phone: c.delivery_phone || "",
      delivery_email: c.delivery_email || "",
      delivery_address: c.delivery_address || "",
      delivery_country: c.delivery_country || "",
      business_id: c.business_id || "",
      notes: c.notes || "",
    });
    setPhoneError(null);
    setActiveTab("basic");
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/customers/${id}`);
      loadCustomers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>顧客管理</h2>
        {hasPermission("customers.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); setPhoneError(null); setActiveTab("basic"); }}>
            新規登録
          </button>
        )}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="名前・メール・会社名・顧客コードで検索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "顧客編集" : "新規顧客登録"}</h3>
            <div className="tab-nav">
              <button type="button" className={activeTab === "basic" ? "tab-active" : ""} onClick={() => setActiveTab("basic")}>基本情報</button>
              <button type="button" className={activeTab === "billing" ? "tab-active" : ""} onClick={() => setActiveTab("billing")}>請求先</button>
              <button type="button" className={activeTab === "delivery" ? "tab-active" : ""} onClick={() => setActiveTab("delivery")}>配送先</button>
            </div>
            <form onSubmit={handleSubmit}>
              {activeTab === "basic" && (
                <>
                  <div className="form-group">
                    <label>名前 *</label>
                    <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>メール</label>
                    <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>電話番号</label>
                    <input
                      value={form.phone}
                      placeholder="例: 03-1234-5678 または 090-1234-5678"
                      onChange={(e) => { setForm({ ...form, phone: e.target.value }); if (phoneError) setPhoneError(null); }}
                      onBlur={(e) => setPhoneError(validatePhoneClient(e.target.value))}
                    />
                    {phoneError && <div className="error-message" style={{ marginTop: 4 }}>{phoneError}</div>}
                  </div>
                  <div className="form-group">
                    <label>会社名</label>
                    <input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>事業者ID / 法人番号</label>
                    <input value={form.business_id} onChange={(e) => setForm({ ...form, business_id: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>登録元</label>
                    <input placeholder="例: Web問い合わせ、紹介" value={form.registration_source} onChange={(e) => setForm({ ...form, registration_source: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>ステータス</label>
                    <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                      <option value="active">有効</option>
                      <option value="inactive">無効</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>備考</label>
                    <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                  </div>
                </>
              )}
              {activeTab === "billing" && (
                <>
                  <div className="form-group"><label>請求先名</label>
                    <input value={form.billing_name} onChange={(e) => setForm({ ...form, billing_name: e.target.value })} />
                  </div>
                  <div className="form-group"><label>請求先電話</label>
                    <input value={form.billing_phone} onChange={(e) => setForm({ ...form, billing_phone: e.target.value })} />
                  </div>
                  <div className="form-group"><label>請求先メール</label>
                    <input type="email" value={form.billing_email} onChange={(e) => setForm({ ...form, billing_email: e.target.value })} />
                  </div>
                  <div className="form-group"><label>請求先住所</label>
                    <textarea value={form.billing_address} onChange={(e) => setForm({ ...form, billing_address: e.target.value })} />
                  </div>
                </>
              )}
              {activeTab === "delivery" && (
                <>
                  <div className="form-group"><label>配送先名</label>
                    <input value={form.delivery_name} onChange={(e) => setForm({ ...form, delivery_name: e.target.value })} />
                  </div>
                  <div className="form-group"><label>配送先電話</label>
                    <input value={form.delivery_phone} onChange={(e) => setForm({ ...form, delivery_phone: e.target.value })} />
                  </div>
                  <div className="form-group"><label>配送先メール</label>
                    <input type="email" value={form.delivery_email} onChange={(e) => setForm({ ...form, delivery_email: e.target.value })} />
                  </div>
                  <div className="form-group"><label>配送先住所</label>
                    <textarea value={form.delivery_address} onChange={(e) => setForm({ ...form, delivery_address: e.target.value })} />
                  </div>
                  <div className="form-group"><label>配送先国</label>
                    <input value={form.delivery_country} onChange={(e) => setForm({ ...form, delivery_country: e.target.value })} />
                  </div>
                </>
              )}
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
              <th>名前</th>
              <th>会社名</th>
              <th>メール</th>
              <th>電話番号</th>
              <th>ステータス</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.id}>
                <td className="mono">{c.customer_code || "-"}</td>
                <td>{c.name}</td>
                <td>{c.company || "-"}</td>
                <td>{c.email || "-"}</td>
                <td>{c.phone || "-"}</td>
                <td>
                  <span className={`badge badge-${c.status === "active" ? "won" : "lost"}`}>
                    {c.status === "active" ? "有効" : c.status === "inactive" ? "無効" : "-"}
                  </span>
                </td>
                <td className="actions">
                  {hasPermission("customers.update") && <button className="btn-sm" onClick={() => handleEdit(c)}>編集</button>}
                  {hasPermission("customers.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(c)}>削除</button>}
                </td>
              </tr>
            ))}
            {customers.length === 0 && (
              <tr><td colSpan={7} className="empty">顧客が登録されていません</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="顧客を削除"
        message={
          <>
            <strong>{deleteTarget?.name}</strong> を削除します。<br />
            関連する商談・注文がある場合は削除できません（先にそれらを削除してください）。<br />
            この操作は取り消せません。
          </>
        }
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

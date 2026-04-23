/**
 * リード管理ページ。
 * ステータスフィルター、見込度ランク表示、案件化機能を含む。
 *
 * 変更履歴:
 *   2026-04-16: 初版作成（Phase 1）
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

const LEAD_STATUSES = ["新規", "コンタクト中", "提案中", "案件化", "失注", "保留"];

interface Lead {
  id: number;
  lead_code: string | null;
  customer_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  source: string | null;
  type: string | null;
  status: string;
  temperature: string | null;
  estimated_scale: string | null;
  customer_type: string | null;
  response_speed: string | null;
  monthly_forecast: number | null;
  prospect_rank: string | null;
  assigned_to: number | null;
  converted_deal_id: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface Customer {
  id: number;
  customer_code: string;
  company_name: string | null;
  billing_display_name: string | null;
}
const customerLabel = (c: Customer): string =>
  c.billing_display_name || c.company_name || c.customer_code;

type FormState = {
  customer_name: string;
  company_name: string;
  email: string;
  phone: string;
  source: string;
  type: string;
  status: string;
  temperature: string;
  estimated_scale: string;
  customer_type: string;
  response_speed: string;
  monthly_forecast: string;
  notes: string;
};

const emptyForm: FormState = {
  customer_name: "", company_name: "", email: "", phone: "",
  source: "", type: "", status: "新規", temperature: "",
  estimated_scale: "", customer_type: "", response_speed: "",
  monthly_forecast: "", notes: "",
};

export default function LeadsPage() {
  const { hasPermission } = usePermissions();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Lead | null>(null);
  const [convertTarget, setConvertTarget] = useState<Lead | null>(null);
  const [convertForm, setConvertForm] = useState({ customer_id: "", title: "", amount: "" });

  const loadLeads = async () => {
    try {
      const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
      const data = await api.get<Lead[]>(`/leads${params}`);
      setLeads(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadCustomers = async () => {
    try {
      const data = await api.get<Customer[]>("/customers?per_page=100");
      setCustomers(data);
    } catch {
      // 顧客取得失敗は致命的ではない
    }
  };

  useEffect(() => { loadLeads(); }, [statusFilter]);
  useEffect(() => { loadCustomers(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const toNull = (v: string) => (v ? v : null);
    const payload = {
      customer_name: form.customer_name,
      company_name: toNull(form.company_name),
      email: toNull(form.email),
      phone: toNull(form.phone),
      source: toNull(form.source),
      type: toNull(form.type),
      status: form.status,
      temperature: toNull(form.temperature),
      estimated_scale: toNull(form.estimated_scale),
      customer_type: toNull(form.customer_type),
      response_speed: toNull(form.response_speed),
      monthly_forecast: form.monthly_forecast ? Number(form.monthly_forecast) : null,
      notes: toNull(form.notes),
    };
    try {
      if (editId) {
        await api.patch(`/leads/${editId}`, payload);
      } else {
        await api.post("/leads", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadLeads();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (l: Lead) => {
    setEditId(l.id);
    setForm({
      customer_name: l.customer_name,
      company_name: l.company_name || "",
      email: l.email || "",
      phone: l.phone || "",
      source: l.source || "",
      type: l.type || "",
      status: l.status,
      temperature: l.temperature || "",
      estimated_scale: l.estimated_scale || "",
      customer_type: l.customer_type || "",
      response_speed: l.response_speed || "",
      monthly_forecast: l.monthly_forecast != null ? String(l.monthly_forecast) : "",
      notes: l.notes || "",
    });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/leads/${id}`);
      loadLeads();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const performConvert = async (e: FormEvent) => {
    e.preventDefault();
    if (!convertTarget) return;
    try {
      await api.post(`/leads/${convertTarget.id}/convert`, {
        customer_id: Number(convertForm.customer_id),
        title: convertForm.title,
        amount: convertForm.amount ? Number(convertForm.amount) : null,
      });
      setConvertTarget(null);
      setConvertForm({ customer_id: "", title: "", amount: "" });
      loadLeads();
    } catch (e) {
      setError(e instanceof Error ? e.message : "案件化に失敗しました");
    }
  };

  const rankBadge = (rank: string | null) => {
    if (!rank) return "-";
    const colorMap: Record<string, string> = {
      "A": "badge-won",
      "B+": "badge-confirmed",
      "B": "badge-negotiating",
      "B-": "badge-on_hold",
      "仮C": "badge-pending",
      "確定C": "badge-lost",
    };
    return <span className={`badge ${colorMap[rank] || ""}`}>{rank}</span>;
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>リード管理</h2>
        {hasPermission("leads.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>新規登録</button>
        )}
      </div>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">全ステータス</option>
          {LEAD_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "リード編集" : "新規リード登録"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>顧客名 *</label>
                <input required value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} />
              </div>
              <div className="form-group"><label>会社名</label>
                <input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
              </div>
              <div className="form-group"><label>メール</label>
                <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="form-group"><label>電話番号</label>
                <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div className="form-group"><label>流入元</label>
                <input placeholder="例: Web問い合わせ、展示会、紹介" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
              </div>
              <div className="form-group"><label>タイプ</label>
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                  <option value="">未設定</option>
                  <option value="Inbound">Inbound</option>
                  <option value="Outbound">Outbound</option>
                </select>
              </div>
              <div className="form-group"><label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {LEAD_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="form-group"><label>温度感</label>
                <select value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })}>
                  <option value="">未設定</option>
                  <option value="Hot">Hot</option>
                  <option value="Warm">Warm</option>
                  <option value="Cold">Cold</option>
                </select>
              </div>
              <div className="form-group"><label>想定規模</label>
                <select value={form.estimated_scale} onChange={(e) => setForm({ ...form, estimated_scale: e.target.value })}>
                  <option value="">未設定</option>
                  <option value="Small">Small</option>
                  <option value="Medium">Medium</option>
                  <option value="Large">Large</option>
                </select>
              </div>
              <div className="form-group"><label>顧客タイプ</label>
                <select value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
                  <option value="">未設定</option>
                  <option value="信頼重視">信頼重視</option>
                  <option value="価格重視">価格重視</option>
                </select>
              </div>
              <div className="form-group"><label>返信速度</label>
                <select value={form.response_speed} onChange={(e) => setForm({ ...form, response_speed: e.target.value })}>
                  <option value="">未設定</option>
                  <option value="24h以内">24h以内</option>
                  <option value="3日以内">3日以内</option>
                  <option value="3日超">3日超</option>
                </select>
              </div>
              <div className="form-group"><label>月間見込み金額（円）</label>
                <input type="number" min="0" step="1" value={form.monthly_forecast} onChange={(e) => setForm({ ...form, monthly_forecast: e.target.value })} />
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

      {convertTarget && (
        <div className="modal-overlay" onClick={() => setConvertTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>リードを案件化</h3>
            <p>リード <strong>{convertTarget.customer_name}</strong> を案件に変換します。</p>
            <form onSubmit={performConvert}>
              <div className="form-group"><label>紐付け顧客 *</label>
                <select required value={convertForm.customer_id} onChange={(e) => setConvertForm({ ...convertForm, customer_id: e.target.value })}>
                  <option value="">選択してください</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{customerLabel(c)}</option>)}
                </select>
              </div>
              <div className="form-group"><label>案件タイトル *</label>
                <input required value={convertForm.title} onChange={(e) => setConvertForm({ ...convertForm, title: e.target.value })} />
              </div>
              <div className="form-group"><label>金額（円）</label>
                <input type="number" min="0" step="1" value={convertForm.amount} onChange={(e) => setConvertForm({ ...convertForm, amount: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setConvertTarget(null)}>キャンセル</button>
                <button type="submit" className="btn-primary">案件化する</button>
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
              <th>顧客名</th>
              <th>会社名</th>
              <th>ステータス</th>
              <th>温度感</th>
              <th>見込度</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((l) => (
              <tr key={l.id}>
                <td className="mono">{l.lead_code || "-"}</td>
                <td>{l.customer_name}</td>
                <td>{l.company_name || "-"}</td>
                <td><span className={`badge lead-badge-${l.status}`}>{l.status}</span></td>
                <td>{l.temperature || "-"}</td>
                <td>{rankBadge(l.prospect_rank)}</td>
                <td className="actions">
                  {hasPermission("leads.update") && <button className="btn-sm" onClick={() => handleEdit(l)}>編集</button>}
                  {hasPermission("leads.convert") && l.status !== "案件化" && (
                    <button className="btn-sm btn-primary" onClick={() => setConvertTarget(l)}>案件化</button>
                  )}
                  {hasPermission("leads.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(l)}>削除</button>}
                </td>
              </tr>
            ))}
            {leads.length === 0 && <tr><td colSpan={7} className="empty">リードが登録されていません</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="リードを削除"
        message={<><strong>{deleteTarget?.customer_name}</strong> を削除します。<br />この操作は取り消せません。</>}
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

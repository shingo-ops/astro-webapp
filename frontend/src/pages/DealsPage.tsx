/**
 * 案件管理ページ。
 *
 * 変更履歴:
 *   2026-04-16: Phase 1拡張（deal_code/stage/probability/currency/assigned_to 追加、
 *     権限チェック連動）
 *   2026-04-25: Phase 1-B-2 Step 5c-3 — 顧客セレクタを CompanyContactSelector
 *     （company + contact）に置換。一覧表示は company_id ベースに変更。
 *   2026-04-27: PR #147 review follow-up
 *     - F2: レガシー deal（company_id NULL）編集時の UX 改善
 *       - 既存 contact_id がある場合はその contact の company を初期値表示
 *       - レガシー deal を編集中である旨を注記
 *     - F6: companies 一覧をセレクタに props で渡し API 重複コールを解消
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import CompanyContactSelector from "../components/CompanyContactSelector";
import { usePermissions } from "../hooks/usePermissions";

interface Deal {
  id: number;
  deal_code: string | null;
  customer_id: number | null;
  company_id: number | null;
  contact_id: number | null;
  lead_id: number | null;
  title: string;
  amount: number | null;
  currency: string | null;
  status: string;
  stage: string | null;
  probability: number | null;
  lost_reason: string | null;
  assigned_to: number | null;
  expected_close_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface CompanyMini {
  id: number;
  company_code: string;
  name: string;
}

const STATUSES = ["open", "negotiating", "won", "lost", "on_hold"];
const STATUS_LABELS: Record<string, string> = {
  open: "オープン", negotiating: "交渉中", won: "成約", lost: "失注", on_hold: "保留",
};
const STAGES = ["open", "negotiating", "proposal", "won", "lost", "on_hold"];
const STAGE_LABELS: Record<string, string> = {
  open: "初回接触", negotiating: "ヒアリング中", proposal: "提案済", won: "成約", lost: "失注", on_hold: "保留",
};

const emptyForm = {
  title: "", amount: "", currency: "JPY",
  status: "open", stage: "open", probability: "10", lost_reason: "",
  assigned_to: "", expected_close_date: "", notes: "",
};

export default function DealsPage() {
  const { hasPermission } = usePermissions();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [companies, setCompanies] = useState<CompanyMini[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  // Step 5c-3: 顧客は (companyId, contactId) で管理。submit 時 backend が customer_id を逆引き
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [contactId, setContactId] = useState<number | null>(null);
  const [selectorError, setSelectorError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Deal | null>(null);
  // PR #147 F2: レガシー deal（company_id NULL）編集中フラグ。注記表示に使用。
  const [editingLegacyDeal, setEditingLegacyDeal] = useState(false);

  const loadDeals = async () => {
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const data = await api.get<Deal[]>(`/deals${params}`);
      setDeals(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  // 一覧の「会社」列表示用（company_id → 会社名）
  const loadCompanies = async () => {
    try {
      const data = await api.get<CompanyMini[]>("/companies?per_page=200");
      setCompanies(data.map((c) => ({ id: c.id, company_code: c.company_code, name: c.name })));
    } catch { /* ignore */ }
  };

  useEffect(() => { loadDeals(); }, [statusFilter]);
  useEffect(() => { loadCompanies(); }, []);

  const resetSelector = () => {
    setCompanyId(null);
    setContactId(null);
    setSelectorError("");
    setEditingLegacyDeal(false);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSelectorError("");
    if (contactId === null) {
      setSelectorError("会社と担当者を選択してください");
      return;
    }
    const payload: Record<string, unknown> = {
      company_id: companyId,
      contact_id: contactId,
      title: form.title,
      amount: form.amount ? Number(form.amount) : null,
      currency: form.currency,
      status: form.status,
      stage: form.stage,
      probability: form.probability ? Number(form.probability) : null,
      lost_reason: form.lost_reason || null,
      assigned_to: form.assigned_to ? Number(form.assigned_to) : null,
      expected_close_date: form.expected_close_date || null,
      notes: form.notes || null,
    };
    try {
      if (editId) {
        await api.patch(`/deals/${editId}`, payload);
      } else {
        await api.post("/deals", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      resetSelector();
      loadDeals();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = async (d: Deal) => {
    setEditId(d.id);
    setForm({
      title: d.title,
      amount: d.amount != null ? String(d.amount) : "",
      currency: d.currency || "JPY",
      status: d.status,
      stage: d.stage || "open",
      probability: d.probability != null ? String(d.probability) : "10",
      lost_reason: d.lost_reason || "",
      assigned_to: d.assigned_to != null ? String(d.assigned_to) : "",
      expected_close_date: d.expected_close_date || "",
      notes: d.notes || "",
    });
    // PR #147 F2: レガシー deal（company_id NULL）の編集 UX 改善。
    // - company_id NULL かつ contact_id 有りの場合は、その contact から company を逆引きし
    //   初期値として埋める（backend 側でも自動補完する保険があるが、UI 上で見える方が安全）。
    // - company/contact 共に NULL の場合はユーザーに「会社と担当者を選んでください」を促す。
    const isLegacy = d.company_id == null;
    setEditingLegacyDeal(isLegacy);
    if (isLegacy && d.contact_id != null) {
      try {
        const contact = await api.get<{ company_id: number | null }>(
          `/contacts/${d.contact_id}`,
        );
        setCompanyId(contact.company_id);
        setContactId(d.contact_id);
      } catch {
        // 取得失敗時はそのまま空で表示（ユーザーに再選択させる）
        setCompanyId(null);
        setContactId(null);
      }
    } else {
      setCompanyId(d.company_id);
      setContactId(d.contact_id);
    }
    setSelectorError("");
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/deals/${id}`);
      loadDeals();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const fmt = (n: number, ccy: string | null) => {
    const cur = ccy || "JPY";
    try {
      return n.toLocaleString("ja-JP", { style: "currency", currency: cur });
    } catch {
      return `${cur} ${n.toLocaleString()}`;
    }
  };
  const companyName = (id: number | null) => {
    if (!id) return "-";
    const c = companies.find((c) => c.id === id);
    return c ? `${c.name}（${c.company_code}）` : `#${id}`;
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>案件管理</h2>
        {hasPermission("deals.create") && (
          <button
            className="btn-primary"
            onClick={() => {
              setShowForm(true);
              setEditId(null);
              setForm(emptyForm);
              resetSelector();
            }}
          >
            新規登録
          </button>
        )}
      </div>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">全ステータス</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "商談編集" : "新規商談登録"}</h3>
            <form onSubmit={handleSubmit}>
              <CompanyContactSelector
                value={{ companyId, contactId }}
                onChange={({ companyId: c, contactId: ct }) => {
                  setCompanyId(c);
                  setContactId(ct);
                }}
                required
                error={selectorError}
                companies={companies}
              />
              {editingLegacyDeal && (
                <p
                  style={{
                    fontSize: "0.85rem",
                    color: "var(--text-secondary)",
                    marginTop: -8,
                  }}
                >
                  ※ この商談は旧モデル（会社未設定）で作成されています。会社・担当者を確認してから保存してください。
                </p>
              )}
              <div className="form-group"><label>タイトル *</label>
                <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </div>
              <div className="form-group"><label>金額</label>
                <input type="number" min="0" step="1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              </div>
              <div className="form-group"><label>通貨</label>
                <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                  <option value="JPY">JPY</option>
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                </select>
              </div>
              <div className="form-group"><label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                </select>
              </div>
              <div className="form-group"><label>ステージ</label>
                <select value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                  {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
                </select>
              </div>
              <div className="form-group"><label>成約確率 (%)</label>
                <input type="number" min="0" max="100" value={form.probability} onChange={(e) => setForm({ ...form, probability: e.target.value })} />
              </div>
              <div className="form-group"><label>担当者ユーザーID</label>
                <input type="number" min="1" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} />
              </div>
              <div className="form-group"><label>成約予定日</label>
                <input type="date" value={form.expected_close_date} onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} />
              </div>
              {form.status === "lost" && (
                <div className="form-group"><label>失注理由</label>
                  <input value={form.lost_reason} onChange={(e) => setForm({ ...form, lost_reason: e.target.value })} />
                </div>
              )}
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
              <th>タイトル</th>
              <th>会社</th>
              <th>金額</th>
              <th>ステージ</th>
              <th>確率</th>
              <th>ステータス</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.deal_code || "-"}</td>
                <td>{d.title}</td>
                <td>{companyName(d.company_id)}</td>
                <td>{d.amount ? fmt(d.amount, d.currency) : "-"}</td>
                <td>{d.stage ? (STAGE_LABELS[d.stage] || d.stage) : "-"}</td>
                <td>{d.probability != null ? `${d.probability}%` : "-"}</td>
                <td><span className={`badge badge-${d.status}`}>{STATUS_LABELS[d.status] || d.status}</span></td>
                <td className="actions">
                  {hasPermission("deals.update") && <button className="btn-sm" onClick={() => handleEdit(d)}>編集</button>}
                  {hasPermission("deals.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(d)}>削除</button>}
                </td>
              </tr>
            ))}
            {deals.length === 0 && (
              <tr><td colSpan={8} className="empty">商談が登録されていません</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="商談を削除"
        message={
          <>
            <strong>{deleteTarget?.title}</strong> を削除します。<br />
            関連する注文がある場合は削除できません（先に注文を削除してください）。<br />
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

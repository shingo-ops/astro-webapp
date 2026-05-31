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
 *   2026-04-27: Phase 1-B-2 Step 5d — 旧 customer_id 経路を完全撤去。
 *     interface Deal から customer_id 削除、company_id を必須化、
 *     PR #147 F2 のレガシー deal 編集 UX も廃止（本番に該当 deal は存在しないため）。
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import ConfirmModal from "../../components/ConfirmModal";
import CompanyContactSelector from "../../components/CompanyContactSelector";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";

interface Deal {
  id: number;
  deal_code: string | null;
  company_id: number;
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
const STAGES = ["open", "negotiating", "proposal", "won", "lost", "on_hold"];

const emptyForm = {
  title: "", amount: "", currency: "JPY",
  status: "open", stage: "open", probability: "10", lost_reason: "",
  assigned_to: "", expected_close_date: "", notes: "",
};

export default function DealsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [companies, setCompanies] = useState<CompanyMini[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  // Step 5d: 顧客は (companyId, contactId) で管理（旧 customer_id 経路は撤去済）。
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [contactId, setContactId] = useState<number | null>(null);
  const [selectorError, setSelectorError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Deal | null>(null);

  const loadDeals = async () => {
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const data = await api.get<Deal[]>(`/deals${params}`);
      setDeals(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  // 一覧の「会社」列表示用（company_id → 会社名）
  const loadCompanies = async () => {
    try {
      // backend `/companies` は per_page le=100 制約のため 100 を上限に揃える
      const data = await api.get<CompanyMini[]>("/companies?per_page=100");
      setCompanies(data.map((c) => ({ id: c.id, company_code: c.company_code, name: c.name })));
    } catch { /* ignore */ }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadDeals(); }, [statusFilter]);
  useEffect(() => { loadCompanies(); }, []);

  const resetSelector = () => {
    setCompanyId(null);
    setContactId(null);
    setSelectorError("");
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSelectorError("");
    if (contactId === null) {
      setSelectorError(t("companyContactSelector.contactRequired"));
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
      setError(e instanceof Error ? e.message : t("common.saveError"));
    }
  };

  const handleEdit = (d: Deal) => {
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
    // Step 5d: 旧 customer_id 経路は撤去済。company_id は backend で必須なので必ず存在する。
    setCompanyId(d.company_id);
    setContactId(d.contact_id);
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
      setError(e instanceof Error ? e.message : t("common.deleteError"));
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
    <PageLayout
      navKey="nav.deals"
      subtitleKey="deals.subtitle"
      headerAction={hasPermission("deals.create") ? (
        <div className="page-header-actions">
          <button
            className="btn-primary"
            onClick={() => {
              setShowForm(true);
              setEditId(null);
              setForm(emptyForm);
              resetSelector();
            }}
          >
            {t("deals.newDeal")}
          </button>
        </div>
      ) : undefined}
    >
      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">{t("deals.allStatuses")}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`deals.status_${s}`)}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("deals.editDeal") : t("deals.newDeal")}</h3>
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
              <div className="form-group"><label>{t("deals.dealTitle")} *</label>
                <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("deals.amount")}</label>
                <input type="number" min="0" step="1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("common.currency")}</label>
                <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                  <option value="JPY">JPY</option>
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                </select>
              </div>
              <div className="form-group"><label>{t("common.status")}</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{t(`deals.status_${s}`)}</option>)}
                </select>
              </div>
              <div className="form-group"><label>{t("dashboard.stage")}</label>
                <select value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                  {STAGES.map((s) => <option key={s} value={s}>{t(`deals.stage_${s}`)}</option>)}
                </select>
              </div>
              <div className="form-group"><label>{t("deals.probability")}</label>
                <input type="number" min="0" max="100" value={form.probability} onChange={(e) => setForm({ ...form, probability: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("deals.assignedTo")}</label>
                <input type="number" min="1" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("deals.expectedCloseDate")}</label>
                <input type="date" value={form.expected_close_date} onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} />
              </div>
              {form.status === "lost" && (
                <div className="form-group"><label>{t("deals.lostReason")}</label>
                  <input value={form.lost_reason} onChange={(e) => setForm({ ...form, lost_reason: e.target.value })} />
                </div>
              )}
              <div className="form-group"><label>{t("common.notes")}</label>
                <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{editId ? t("common.update") : t("common.register")}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("deals.dealTitle")}</th>
              <th>{t("common.company")}</th>
              <th>{t("deals.amount")}</th>
              <th>{t("dashboard.stage")}</th>
              <th>{t("deals.probability")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr key={d.id}>
                <td>{d.title}</td>
                <td>{companyName(d.company_id)}</td>
                <td>{d.amount ? fmt(d.amount, d.currency) : "-"}</td>
                <td>{d.stage ? (t(`deals.stage_${d.stage}`) || d.stage) : "-"}</td>
                <td>{d.probability != null ? `${d.probability}%` : "-"}</td>
                <td><span className={`badge badge-${d.status}`}>{t(`deals.status_${d.status}`) || d.status}</span></td>
                <td className="actions">
                  {hasPermission("deals.update") && <button className="btn-sm" onClick={() => handleEdit(d)}>{t("common.edit")}</button>}
                  {hasPermission("deals.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(d)}>{t("common.delete")}</button>}
                </td>
              </tr>
            ))}
            {deals.length === 0 && (
              <tr><td colSpan={8} className="empty">{t("deals.noDeals")}</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("deals.deleteDeal")}
        message={
          <>
            <strong>{deleteTarget?.title}</strong> {t("deals.deleteConfirmSuffix")}<br />
            {t("deals.deleteConstraint")}<br />
            {t("common.irreversible")}
          </>
        }
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </PageLayout>
  );
}

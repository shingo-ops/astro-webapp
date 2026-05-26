/**
 * リード管理ページ。
 * ステータスフィルター、見込度ランク表示、案件化機能を含む。
 *
 * 変更履歴:
 *   2026-04-16: 初版作成（Phase 1）
 *   2026-04-25: Phase 1-B-2 Step 5c-3 — 案件化モーダルの顧客セレクタを
 *     CompanyContactSelector（company + contact）に置換。
 */

import { useCallback, useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import ConfirmModal from "../../components/ConfirmModal";
import CompanyContactSelector from "../../components/CompanyContactSelector";
import { usePermissions } from "../../hooks/usePermissions";
import { useSSE } from "../../hooks/useSSE";
import { PageLayout } from "../../components/PageLayout";

/* ------------------------------------------------------------------ */
/* Lead types                                                           */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/* Main LeadsPage                                                       */
/* ------------------------------------------------------------------ */

export default function LeadsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();

  const [leads, setLeads] = useState<Lead[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Lead | null>(null);
  const [convertTarget, setConvertTarget] = useState<Lead | null>(null);
  const [convertForm, setConvertForm] = useState({ title: "", amount: "" });
  const [convertCompanyId, setConvertCompanyId] = useState<number | null>(null);
  const [convertContactId, setConvertContactId] = useState<number | null>(null);
  const [convertSelectorError, setConvertSelectorError] = useState("");

  const LEAD_STATUSES = [
    t("leads.status_new"),
    t("leads.status_contact"),
    t("leads.status_proposal"),
    t("leads.status_won"),
    t("leads.status_lost"),
    t("leads.status_hold"),
  ];

  // backend が返す日本語の lead.status 値を i18n key にマッピング (UI 表示専用、API 送信値はそのまま)
  const LEAD_STATUS_I18N_KEY: Record<string, string> = {
    "新規": "leads.status_new",
    "コンタクト中": "leads.status_contact",
    "提案中": "leads.status_proposal",
    "案件化": "leads.status_won",
    "失注": "leads.status_lost",
    "保留": "leads.status_hold",
  };
  const translateLeadStatus = (status: string) => {
    const key = LEAD_STATUS_I18N_KEY[status];
    return key ? t(key) : status;
  };

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
      const data = await api.get<Lead[]>(`/leads${params}`);
      setLeads(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, t]);

  useEffect(() => {
    loadLeads();
  }, [loadLeads]);

  // Phase 3 SSE: 他スタッフのリード作成・更新・削除を即時反映
  useSSE({
    endpoint: "/api/v1/leads/stream",
    onUpdate: useCallback(() => { loadLeads(); }, [loadLeads]),
  });

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
      setError(e instanceof Error ? e.message : t("common.saveError"));
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
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const closeConvert = () => {
    setConvertTarget(null);
    setConvertForm({ title: "", amount: "" });
    setConvertCompanyId(null);
    setConvertContactId(null);
    setConvertSelectorError("");
  };

  const performConvert = async (e: FormEvent) => {
    e.preventDefault();
    if (!convertTarget) return;
    setConvertSelectorError("");
    if (convertContactId === null) {
      setConvertSelectorError(t("companyContactSelector.contactRequired"));
      return;
    }
    try {
      await api.post(`/leads/${convertTarget.id}/convert`, {
        company_id: convertCompanyId,
        contact_id: convertContactId,
        title: convertForm.title,
        amount: convertForm.amount ? Number(convertForm.amount) : null,
      });
      closeConvert();
      loadLeads();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
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
    <PageLayout
      navKey="nav.leads"
      subtitleKey="leads.subtitle"
      headerAction={hasPermission("leads.create") ? (
        <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>{t("leads.newLead")}</button>
      ) : undefined}
    >
      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">{t("leads.allStatuses")}</option>
          {LEAD_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("leads.editLead") : t("leads.newLeadTitle")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("leads.customerName")} *</label>
                <input required value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.companyName")}</label>
                <input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.email")}</label>
                <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.phone")}</label>
                <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.source")}</label>
                <input placeholder={t("leads.sourcePlaceholder")} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.type")}</label>
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                  <option value="">{t("common.notSet")}</option>
                  <option value="Inbound">{t("leads.type_inbound")}</option>
                  <option value="Outbound">{t("leads.type_outbound")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("leads.status")}</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {LEAD_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="form-group"><label>{t("leads.temperature")}</label>
                <select value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })}>
                  <option value="">{t("common.notSet")}</option>
                  <option value="Hot">{t("leads.temp_hot")}</option>
                  <option value="Warm">{t("leads.temp_warm")}</option>
                  <option value="Cold">{t("leads.temp_cold")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("leads.estimatedScale")}</label>
                <select value={form.estimated_scale} onChange={(e) => setForm({ ...form, estimated_scale: e.target.value })}>
                  <option value="">{t("common.notSet")}</option>
                  <option value="Small">{t("leads.scale_small")}</option>
                  <option value="Medium">{t("leads.scale_medium")}</option>
                  <option value="Large">{t("leads.scale_large")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("leads.customerType")}</label>
                <select value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
                  <option value="">{t("common.notSet")}</option>
                  <option value="信頼重視">{t("leads.customerType_trust")}</option>
                  <option value="価格重視">{t("leads.customerType_price")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("leads.responseSpeed")}</label>
                <select value={form.response_speed} onChange={(e) => setForm({ ...form, response_speed: e.target.value })}>
                  <option value="">{t("common.notSet")}</option>
                  <option value="24h以内">{t("leads.responseSpeed_24h")}</option>
                  <option value="3日以内">{t("leads.responseSpeed_3days")}</option>
                  <option value="3日超">{t("leads.responseSpeed_over3days")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("leads.monthlyForecast")}</label>
                <input type="number" min="0" step="1" value={form.monthly_forecast} onChange={(e) => setForm({ ...form, monthly_forecast: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.notes")}</label>
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

      {convertTarget && (
        <div className="modal-overlay" onClick={closeConvert}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("leads.convertLead")}</h3>
            <p>{t("leads.title")} <strong>{convertTarget.customer_name}</strong> {t("leads.convertConfirm")}</p>
            <form onSubmit={performConvert}>
              <CompanyContactSelector
                value={{ companyId: convertCompanyId, contactId: convertContactId }}
                onChange={({ companyId, contactId }) => {
                  setConvertCompanyId(companyId);
                  setConvertContactId(contactId);
                }}
                required
                error={convertSelectorError}
              />
              <div className="form-group"><label>{t("leads.dealTitle")} *</label>
                <input required value={convertForm.title} onChange={(e) => setConvertForm({ ...convertForm, title: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.dealAmount")}</label>
                <input type="number" min="0" step="1" value={convertForm.amount} onChange={(e) => setConvertForm({ ...convertForm, amount: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={closeConvert}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{t("leads.convert")}</button>
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
              <th>{t("leads.customerName")}</th>
              <th>{t("leads.companyName")}</th>
              <th>{t("leads.status")}</th>
              <th>{t("leads.temperature")}</th>
              <th>{t("leads.prospectRank")}</th>
              <th>{t("leads.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((l) => (
              <tr key={l.id}>
                <td>{l.customer_name}</td>
                <td>{l.company_name || "-"}</td>
                <td><span className={`badge lead-badge-${l.status}`}>{translateLeadStatus(l.status)}</span></td>
                <td>{l.temperature || "-"}</td>
                <td>{rankBadge(l.prospect_rank)}</td>
                <td className="actions">
                  {hasPermission("leads.update") && <button className="btn-sm" onClick={() => handleEdit(l)}>{t("common.edit")}</button>}
                  {hasPermission("leads.convert") && l.status !== "案件化" && (
                    <button className="btn-sm btn-primary" onClick={() => setConvertTarget(l)}>{t("leads.convert")}</button>
                  )}
                  {hasPermission("leads.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(l)}>{t("common.delete")}</button>}
                </td>
              </tr>
            ))}
            {leads.length === 0 && <tr><td colSpan={7} className="empty">{t("leads.noLeads")}</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("leads.deleteLead")}
        message={<><strong>{deleteTarget?.customer_name}</strong> {t("leads.deleteConfirm")}<br />{t("common.irreversible")}</>}
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </PageLayout>
  );
}

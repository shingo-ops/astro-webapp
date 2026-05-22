/**
 * 担当者管理ページ。Phase 1-B-2 Step 5c-1 で新設。
 *
 * 新 B2B モデルの担当者一覧・CRUD。
 * 担当者は必ず 1 つの会社に紐付く（company_id 必須）。
 * 会社別絞り込みフィルタあり。
 * Step 5c-2 で CompanyDetailPage からネスト編集できるようになる予定。
 */

import { useEffect, useState, FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";
import { STATUS_ICONS } from "../constants/icons";
import { ICON } from "../constants/iconSizes";

interface CompanyMini {
  id: number;
  company_code: string;
  name: string;
}

interface Contact {
  id: number;
  tenant_id: number;
  company_id: number;
  contact_code: string;
  lead_id: number | null;
  surname: string | null;
  given_name: string | null;
  display_name: string | null;
  job_title: string | null;
  department: string | null;
  is_primary_contact: boolean;
  primary_email: string | null;
  primary_phone: string | null;
  status: string;
  notes: string | null;
  emails: { id: number; email: string; purpose: string | null }[];
  discord: {
    is_joined: boolean;
    channel_id: string | null;
    user_id: string | null;
    invoice_webhook: string | null;
    shipment_webhook: string | null;
  } | null;
  contact_channels: { id: number; channel: string; purpose: string | null; is_primary: boolean }[];
  created_at: string;
  updated_at: string;
}

type FormState = {
  contact_code: string;
  company_id: string;
  surname: string;
  given_name: string;
  display_name: string;
  job_title: string;
  department: string;
  is_primary_contact: boolean;
  primary_email: string;
  primary_phone: string;
  status: string;
  notes: string;
};

const emptyForm: FormState = {
  contact_code: "",
  company_id: "",
  surname: "",
  given_name: "",
  display_name: "",
  job_title: "",
  department: "",
  is_primary_contact: false,
  primary_email: "",
  primary_phone: "",
  status: "active",
  notes: "",
};

const contactDisplayName = (c: Contact): string => {
  if (c.display_name) return c.display_name;
  const combined = `${c.surname || ""} ${c.given_name || ""}`.trim();
  return combined || c.contact_code || "-";
};

export default function ContactsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  // Step 5c-2: /contacts?company_id=N の URL クエリから初期フィルタを復元
  // （CompanyDetailPage の担当者タブからの導線で会社別絞り込みを有効化）
  const [searchParams] = useSearchParams();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [companies, setCompanies] = useState<CompanyMini[]>([]);
  const [companyFilter, setCompanyFilter] = useState(searchParams.get("company_id") || "");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Contact | null>(null);
  // PR #145 Q2: pending_dedup_review 解消フロー
  const [dedupConfirmTarget, setDedupConfirmTarget] = useState<Contact | null>(null);
  const [dedupSubmitting, setDedupSubmitting] = useState(false);

  const loadContacts = async () => {
    try {
      const parts: string[] = [];
      if (search) parts.push(`search=${encodeURIComponent(search)}`);
      if (companyFilter) parts.push(`company_id=${encodeURIComponent(companyFilter)}`);
      parts.push("per_page=100");
      const qs = parts.join("&");
      const data = await api.get<Contact[]>(`/contacts?${qs}`);
      setContacts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  const loadCompanies = async () => {
    try {
      const data = await api.get<CompanyMini[]>("/companies?per_page=100");
      setCompanies(
        data.map((c: CompanyMini) => ({ id: c.id, company_code: c.company_code, name: c.name })),
      );
    } catch {
      // 静かに無視（フィルタ/セレクタが空になるだけ）
    }
  };

  useEffect(() => { loadContacts(); }, [search, companyFilter]);
  useEffect(() => { loadCompanies(); }, []);

  const companyName = (company_id: number): string => {
    const c = companies.find((x) => x.id === company_id);
    return c ? `${c.name}（${c.company_code}）` : `#${company_id}`;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!form.company_id) {
      setError(t("contacts.companyRequired"));
      return;
    }
    const toNull = (v: string) => (v ? v : null);
    const payload: Record<string, unknown> = {
      company_id: parseInt(form.company_id, 10),
      surname: toNull(form.surname),
      given_name: toNull(form.given_name),
      display_name: toNull(form.display_name),
      job_title: toNull(form.job_title),
      department: toNull(form.department),
      is_primary_contact: form.is_primary_contact,
      primary_email: toNull(form.primary_email),
      primary_phone: toNull(form.primary_phone),
      status: form.status || "active",
      notes: toNull(form.notes),
    };
    if (!editId && form.contact_code.trim()) {
      payload.contact_code = form.contact_code.trim();
    }
    // Note: edit 時に company_id 移動を行うと migration 032 の所属整合性制約に
    // 引っかかる可能性があるため、一旦そのまま送る（backend 側で 400 検出）

    if (submitting) return;
    setSubmitting(true);
    try {
      if (editId) {
        await api.patch(`/contacts/${editId}`, payload);
      } else {
        await api.post("/contacts", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadContacts();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = (c: Contact) => {
    setEditId(c.id);
    setForm({
      contact_code: c.contact_code,
      company_id: String(c.company_id),
      surname: c.surname || "",
      given_name: c.given_name || "",
      display_name: c.display_name || "",
      job_title: c.job_title || "",
      department: c.department || "",
      is_primary_contact: c.is_primary_contact,
      primary_email: c.primary_email || "",
      primary_phone: c.primary_phone || "",
      status: c.status || "active",
      notes: c.notes || "",
    });
    setShowForm(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.delete(`/contacts/${deleteTarget.id}`);
      setDeleteTarget(null);
      loadContacts();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
      setDeleteTarget(null);
    }
  };

  // PR #145 Q2: 「別人として確定」 — status を pending_dedup_review → active に戻す。
  // companies 側と同じく、A-4 のマージ機能とは別経路で独立した担当者として承認する。
  // 現状 ContactStatus enum に pending_dedup_review を追加したため backend は受領できる。
  const handleResolveAsDistinct = async () => {
    if (!dedupConfirmTarget) return;
    setError("");
    setDedupSubmitting(true);
    try {
      await api.patch(`/contacts/${dedupConfirmTarget.id}`, { status: "active" });
      setDedupConfirmTarget(null);
      // PR #163 Reviewer round 1 Minor 2: 一覧再読込を await してから
      // dedupSubmitting を解除する（companies 側 CompanyDetailPage と統一）。
      // 旧コード `loadContacts()` は floating promise になっており、再読込中に
      // 再度ボタンを押されたり画面遷移されたりするとタイミング依存で
      // 件数バッジが古いままになることがあった。
      await loadContacts();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
      setDedupConfirmTarget(null);
    } finally {
      setDedupSubmitting(false);
    }
  };

  // pending_dedup_review の件数（フィルタ済み一覧内）
  const pendingDedupCount = contacts.filter((c) => c.status === "pending_dedup_review").length;

  // PR #163 Reviewer round 1 Minor 3: 編集モーダル内の dedup 解消ボタンの dirty 検知。
  // companies 側 CompanyDetailPage:574 の `disabled={dedupSubmitting || basicDirty}` と同じく、
  // フォームに未保存の変更があるときは「別人として確定」ボタンを disabled + tooltip で
  // 明示的に防ぐ。ベースラインは「現在編集中の contact 行」の値、差分は status 以外の
  // 編集可能フィールド（解消ボタンを押すと status は別 PATCH で active になるため
  // status 自体は dirty 比較に含めない）。
  const editingContact = editId !== null ? contacts.find((c) => c.id === editId) || null : null;
  const formDirtyExceptStatus = (() => {
    if (!editingContact) return false;
    const norm = (v: string | null | undefined) => (v ?? "").trim();
    return (
      String(editingContact.company_id) !== form.company_id ||
      norm(editingContact.surname) !== norm(form.surname) ||
      norm(editingContact.given_name) !== norm(form.given_name) ||
      norm(editingContact.display_name) !== norm(form.display_name) ||
      norm(editingContact.job_title) !== norm(form.job_title) ||
      norm(editingContact.department) !== norm(form.department) ||
      Boolean(editingContact.is_primary_contact) !== form.is_primary_contact ||
      norm(editingContact.primary_email) !== norm(form.primary_email) ||
      norm(editingContact.primary_phone) !== norm(form.primary_phone) ||
      norm(editingContact.notes) !== norm(form.notes)
    );
  })();

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>
          {t("contacts.title")}
          {pendingDedupCount > 0 && (
            <span className="dedup-summary">
              {t("contacts.pendingDedupCount", { count: pendingDedupCount })}
            </span>
          )}
        </h1>
        <div className="page-header-actions">
          <select value={companyFilter} onChange={(e) => setCompanyFilter(e.target.value)} className="search-input">
            <option value="">{t("contacts.allCompanies")}</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}（{c.company_code}）</option>
            ))}
          </select>
          <input
            type="text"
            placeholder={t("contacts.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search-input"
          />
          {hasPermission("customers.create") && (
            <button
              className="btn-primary"
              onClick={() => {
                setEditId(null);
                setForm({ ...emptyForm, company_id: companyFilter });
                setShowForm(true);
              }}
            >
              + {t("contacts.newContact")}
            </button>
          )}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <p>{t("common.loading")}</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("common.code")}</th>
              <th>{t("common.name")}</th>
              <th>{t("common.company")}</th>
              <th>{t("contacts.position")}</th>
              <th>{t("common.email")}</th>
              <th>{t("common.phone")}</th>
              <th>{t("contacts.isPrimary")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {contacts.length === 0 ? (
              <tr><td colSpan={9} style={{ textAlign: "center", padding: "1rem" }}>{t("contacts.noContacts")}</td></tr>
            ) : (
              contacts.map((c) => (
                <tr
                  key={c.id}
                  className={c.status === "pending_dedup_review" ? "row-pending-dedup" : ""}
                >
                  <td>{c.contact_code}</td>
                  <td>{contactDisplayName(c)}</td>
                  <td>{companyName(c.company_id)}</td>
                  <td>{c.job_title || "-"}</td>
                  <td>{c.primary_email || "-"}</td>
                  <td>{c.primary_phone || "-"}</td>
                  <td>{c.is_primary_contact ? <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" /> : ""}</td>
                  <td><span className={`status-badge status-${c.status}`}>{c.status}</span></td>
                  <td>
                    {hasPermission("customers.update") && (
                      <button className="btn-sm" onClick={() => handleEdit(c)}>{t("common.edit")}</button>
                    )}
                    {/* PR #145 Q2: 一覧から直接解消できるショートカット（編集モーダル経由でも可） */}
                    {hasPermission("customers.update") && c.status === "pending_dedup_review" && (
                      <button
                        className="btn-sm"
                        onClick={() => setDedupConfirmTarget(c)}
                      >
                        {t("contacts.confirmAsDistinct")}
                      </button>
                    )}
                    {hasPermission("customers.delete") && (
                      <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(c)}>{t("common.delete")}</button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal-content-wide" onClick={(e) => e.stopPropagation()}>
            <h2>{editId ? t("contacts.editContact") : t("contacts.newContact")}</h2>
            <form onSubmit={handleSubmit} className="form-grid">
              {!editId && (
                <div className="form-row">
                  <label>{t("contacts.contactCodeLabel")}</label>
                  <input value={form.contact_code} onChange={(e) => setForm({ ...form, contact_code: e.target.value })} />
                </div>
              )}
              <div className="form-row">
                <label>{t("contacts.companyLabel")}</label>
                <select required value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })}>
                  <option value="">{t("common.pleaseSelect")}</option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}（{c.company_code}）</option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label>{t("contacts.surname")}</label>
                <input value={form.surname} onChange={(e) => setForm({ ...form, surname: e.target.value })} />
              </div>
              <div className="form-row">
                <label>{t("contacts.givenName")}</label>
                <input value={form.given_name} onChange={(e) => setForm({ ...form, given_name: e.target.value })} />
              </div>
              <div className="form-row">
                <label>{t("contacts.displayName")}</label>
                <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
              </div>
              <div className="form-row">
                <label>{t("contacts.position")}</label>
                <input value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} />
              </div>
              <div className="form-row">
                <label>{t("contacts.department")}</label>
                <input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} />
              </div>
              <div className="form-row">
                <label>
                  <input
                    type="checkbox"
                    checked={form.is_primary_contact}
                    onChange={(e) => setForm({ ...form, is_primary_contact: e.target.checked })}
                  />
                  {" "}{t("contacts.primaryContactHint")}
                </label>
              </div>
              <div className="form-row">
                <label>{t("common.email")}</label>
                <input type="email" value={form.primary_email} onChange={(e) => setForm({ ...form, primary_email: e.target.value })} />
              </div>
              <div className="form-row">
                <label>{t("common.phone")}</label>
                <input value={form.primary_phone} onChange={(e) => setForm({ ...form, primary_phone: e.target.value })} />
              </div>
              <div className="form-row">
                <label>{t("common.status")}</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                  <option value="archived">archived</option>
                  {/* PR #145 Q2: pending_dedup_review を表示・選択可能に。
                      新規付与は通常データ移行スクリプト由来だが、既存データから抜け出す道を確保 */}
                  <option value="pending_dedup_review">{t("contacts.statusPendingDedupOption")}</option>
                </select>
              </div>
              <div className="form-row">
                <label>{t("common.notes")}</label>
                <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>

              {/* PR #145 Q2: 編集中の担当者が pending_dedup_review なら解消セクションを表示 */}
              {editId && form.status === "pending_dedup_review" && (
                <div className="dedup-resolve-section">
                  <h3>{t("contacts.dedupResolveTitle")}</h3>
                  <p>{t("contacts.dedupResolveDesc")}</p>
                  <div className="dedup-resolve-actions">
                    {/* PR #163 Reviewer round 1 Minor 3: 編集モーダル内のフォームに
                        未保存変更がある状態で「別人として確定」ボタンを押すと、解消 PATCH
                        と未保存変更の関係が混乱するため、companies 側 CompanyDetailPage と
                        同じく dirty 状態のときは disabled で明示的に防ぐ。 */}
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => {
                        const target = contacts.find((c) => c.id === editId) || null;
                        if (!target) return;
                        setDedupConfirmTarget(target);
                      }}
                      disabled={dedupSubmitting || formDirtyExceptStatus}
                    >
                      {t("contacts.confirmAsDistinctFull")}
                    </button>
                    <button
                      type="button"
                      disabled
                      style={{ opacity: 0.6, cursor: "not-allowed" }}
                    >
                      {t("contacts.mergeAsDuplicate")}
                    </button>
                  </div>
                </div>
              )}

              <div className="form-actions">
                <button type="button" onClick={() => setShowForm(false)} disabled={submitting}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? t("common.saving") : editId ? t("common.update") : t("common.register")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmModal
        open={deleteTarget !== null}
        title={t("contacts.deleteContact")}
        message={
          deleteTarget
            ? t("contacts.deleteConfirmMessage", {
                name: contactDisplayName(deleteTarget),
                code: deleteTarget.contact_code,
              })
            : ""
        }
        confirmLabel={t("common.delete")}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* PR #145 Q2: 別人として確定の確認ダイアログ */}
      <ConfirmModal
        open={dedupConfirmTarget !== null}
        title={t("contacts.dedupConfirmTitle")}
        message={
          dedupConfirmTarget
            ? t("contacts.dedupConfirmMessage", {
                name: contactDisplayName(dedupConfirmTarget),
                code: dedupConfirmTarget.contact_code,
              })
            : ""
        }
        confirmLabel={t("contacts.changeToActive")}
        onConfirm={handleResolveAsDistinct}
        onCancel={() => setDedupConfirmTarget(null)}
      />
    </div>
  );
}

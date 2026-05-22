/**
 * 会社詳細ページ。Phase 1-B-2 Step 5c-2 で新設。
 *
 * 特徴:
 *   - URL: /companies/:id
 *   - 4 タブ: 基本情報 / 住所（multi_branch 対応） / 担当者 / 販売チャネル
 *   - 住所は multi_branch 対応（complete CRUD per address row、branch_name 編集可）
 *   - 担当者一覧は /contacts?company_id=N への導線のみ（編集は ContactsPage で）
 *   - 販売チャネル: カンマ区切り UI で全置換
 *
 * Step 5c-1 の CompaniesPage では billing/delivery 各 1 件ずつしか扱えず、
 * Card Galaxy LTD のような 2 支店を持つ会社を安全に編集できなかった。
 * 本ページで multi_branch 管理の UI 整備を完結させる。
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import MergeCompanyModal from "../components/MergeCompanyModal";
import { usePermissions } from "../hooks/usePermissions";
import { STATUS_ICONS } from "../constants/icons";

const PHONE_RE = /^(\+?\d{10,15}|0\d{9,10})$/;

interface CompanyAddress {
  id: number;
  address_type: "billing" | "delivery";
  branch_name: string | null;
  name: string | null;
  email: string | null;
  telephone: string | null;
  tax_id: string | null;
  address_line_1: string | null;
  address_line_2: string | null;
  address_line_3: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  country_code: string | null;
  is_default: boolean;
}

interface Company {
  id: number;
  tenant_id: number;
  company_code: string;
  lead_id: number | null;
  sales_rep_id: number | null;
  name: string;
  name_en: string | null;
  normalized_name: string | null;
  industry: string | null;
  website: string | null;
  trust_level: number | null;
  priority_focus: string | null;
  per_order_amount: string | null;
  monthly_frequency: number | null;
  monthly_forecast: string | null;
  monthly_forecast_source: string | null;
  monthly_forecast_updated_at: string | null;
  billing_display_name: string | null;
  payment_recipient_name: string | null;
  fedex_account: string | null;
  shipping_note: string | null;
  status: string;
  notes: string | null;
  addresses: CompanyAddress[];
  sales_channels: string[];
  created_at: string;
  updated_at: string;
}

interface Contact {
  id: number;
  contact_code: string;
  display_name: string | null;
  surname: string | null;
  given_name: string | null;
  job_title: string | null;
  department: string | null;
  is_primary_contact: boolean;
  primary_email: string | null;
  primary_phone: string | null;
  status: string;
}

type Tab = "basic" | "addresses" | "contacts" | "channels";

type AddressFormState = {
  // id が null なら新規、数値なら既存更新（PATCH で全置換なので区別は UI 表現だけ）
  id: number | null;
  address_type: "billing" | "delivery";
  branch_name: string;
  name: string;
  email: string;
  telephone: string;
  tax_id: string;
  address_line_1: string;
  address_line_2: string;
  address_line_3: string;
  city: string;
  state: string;
  zip: string;
  country_code: string;
  is_default: boolean;
};

const emptyAddress = (type: "billing" | "delivery"): AddressFormState => ({
  id: null,
  address_type: type,
  branch_name: "", name: "", email: "", telephone: "", tax_id: "",
  address_line_1: "", address_line_2: "", address_line_3: "",
  city: "", state: "", zip: "", country_code: "",
  is_default: false,
});

const addressFromApi = (a: CompanyAddress): AddressFormState => ({
  id: a.id,
  address_type: a.address_type,
  branch_name: a.branch_name || "",
  name: a.name || "", email: a.email || "", telephone: a.telephone || "",
  tax_id: a.tax_id || "",
  address_line_1: a.address_line_1 || "", address_line_2: a.address_line_2 || "", address_line_3: a.address_line_3 || "",
  city: a.city || "", state: a.state || "", zip: a.zip || "",
  country_code: a.country_code || "",
  is_default: a.is_default,
});

const addressDisplay = (a: CompanyAddress): string => {
  // branch_name を先頭にプレフィックスして multi_branch を一覧で区別しやすくする
  const parts = [
    a.branch_name,
    a.name,
    a.address_line_1,
    a.city,
    a.state,
    a.zip,
    a.country_code,
  ].filter(Boolean);
  return parts.join(", ") || "-";
};

const typeLabel = (tFn: (key: string) => string, type: "billing" | "delivery") =>
  type === "billing" ? tFn("companies.billing") : tFn("companies.delivery");

type BasicFormState = {
  name: string;
  name_en: string;
  industry: string;
  website: string;
  trust_level: string;
  priority_focus: string;
  per_order_amount: string;
  monthly_frequency: string;
  monthly_forecast: string;
  billing_display_name: string;
  payment_recipient_name: string;
  fedex_account: string;
  shipping_note: string;
  status: string;
  notes: string;
};

const basicFromApi = (c: Company): BasicFormState => ({
  name: c.name || "",
  name_en: c.name_en || "",
  industry: c.industry || "",
  website: c.website || "",
  trust_level: c.trust_level !== null ? String(c.trust_level) : "",
  priority_focus: c.priority_focus || "",
  per_order_amount: c.per_order_amount || "",
  monthly_frequency: c.monthly_frequency !== null ? String(c.monthly_frequency) : "",
  monthly_forecast: c.monthly_forecast || "",
  billing_display_name: c.billing_display_name || "",
  payment_recipient_name: c.payment_recipient_name || "",
  fedex_account: c.fedex_account || "",
  shipping_note: c.shipping_note || "",
  status: c.status || "active",
  notes: c.notes || "",
});

export default function CompanyDetailPage() {
  const { t } = useTranslation();

  const validatePhoneClient = (raw: string): string | null => {
    if (!raw) return null;
    const cleaned = raw.replace(/[\s\-()]/g, "");
    return PHONE_RE.test(cleaned) ? null : t("companies.phoneError");
  };

  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission("customers.update");
  // A-4: 会社マージは customers.delete 権限相当（merge 元の DELETE を含むため）
  const canMerge = hasPermission("customers.delete");

  const [company, setCompany] = useState<Company | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("basic");

  // 基本情報タブの編集ステート
  const [basicForm, setBasicForm] = useState<BasicFormState | null>(null);
  const [basicDirty, setBasicDirty] = useState(false);
  const [basicSubmitting, setBasicSubmitting] = useState(false);

  // 販売チャネルタブ
  const [channelsText, setChannelsText] = useState("");
  const [channelsDirty, setChannelsDirty] = useState(false);
  const [channelsSubmitting, setChannelsSubmitting] = useState(false);

  // 住所タブ: 編集中の 1 件をモーダルで管理
  const [addrModalOpen, setAddrModalOpen] = useState(false);
  const [addrForm, setAddrForm] = useState<AddressFormState>(emptyAddress("billing"));
  const [addrSubmitting, setAddrSubmitting] = useState(false);
  const [addrDeleteTarget, setAddrDeleteTarget] = useState<CompanyAddress | null>(null);
  const [addrPhoneError, setAddrPhoneError] = useState<string | null>(null);
  // Step 5c-2 反省: モーダル内エラーは modal header に表示しないと overlay で隠れる
  const [addrModalError, setAddrModalError] = useState<string | null>(null);

  // PR #145 Q2: pending_dedup_review 解消フロー
  const [dedupConfirmOpen, setDedupConfirmOpen] = useState(false);
  const [dedupSubmitting, setDedupSubmitting] = useState(false);
  // A-4: 重複としてマージ
  const [mergeModalOpen, setMergeModalOpen] = useState(false);

  const load = async () => {
    if (!id) return;
    try {
      const c = await api.get<Company>(`/companies/${id}`);
      setCompany(c);
      setBasicForm(basicFromApi(c));
      setChannelsText(c.sales_channels.join(", "));
      setBasicDirty(false);
      setChannelsDirty(false);
      // 会社配下の担当者も取得
      const list = await api.get<Contact[]>(`/companies/${id}/contacts`);
      setContacts(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const handleBasicSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!basicForm || !company) return;
    setError("");
    setBasicSubmitting(true);
    try {
      const toNull = (v: string) => (v ? v : null);
      const payload: Record<string, unknown> = {
        name: basicForm.name.trim(),
        name_en: toNull(basicForm.name_en),
        industry: toNull(basicForm.industry),
        website: toNull(basicForm.website),
        trust_level: basicForm.trust_level ? parseInt(basicForm.trust_level, 10) : null,
        priority_focus: toNull(basicForm.priority_focus),
        per_order_amount: basicForm.per_order_amount || null,
        monthly_frequency: basicForm.monthly_frequency ? parseInt(basicForm.monthly_frequency, 10) : null,
        monthly_forecast: basicForm.monthly_forecast || null,
        billing_display_name: toNull(basicForm.billing_display_name),
        payment_recipient_name: toNull(basicForm.payment_recipient_name),
        fedex_account: toNull(basicForm.fedex_account),
        shipping_note: toNull(basicForm.shipping_note),
        status: basicForm.status || "active",
        notes: toNull(basicForm.notes),
      };
      await api.patch(`/companies/${company.id}`, payload);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setBasicSubmitting(false);
    }
  };

  const handleChannelsSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!company) return;
    setError("");
    setChannelsSubmitting(true);
    try {
      const list = channelsText
        .split(/[,、，]/)
        .map((s) => s.trim())
        .filter(Boolean);
      await api.patch(`/companies/${company.id}`, { sales_channels: list });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setChannelsSubmitting(false);
    }
  };

  // 住所は PATCH /companies/{id} {addresses: [...]} で「全置換」になるため、
  // 1 件追加/編集/削除の際も既存住所をそのまま含めて送る必要がある。
  // 以下は「現在の company.addresses を元に、1 件を変更した新配列を送る」ヘルパ。
  const submitAddresses = async (next: AddressFormState[]) => {
    if (!company) return;
    const toNull = (v: string) => (v ? v : null);
    // address_type ごとに is_default=TRUE は最大 1 件（backend 側部分UNIQUE INDEX）
    const seen: Record<string, boolean> = { billing: false, delivery: false };
    const payload = next.map((a) => {
      const isDefault = a.is_default && !seen[a.address_type];
      if (isDefault) seen[a.address_type] = true;
      return {
        address_type: a.address_type,
        branch_name: toNull(a.branch_name),
        name: toNull(a.name),
        email: toNull(a.email),
        telephone: toNull(a.telephone),
        tax_id: toNull(a.tax_id),
        address_line_1: toNull(a.address_line_1),
        address_line_2: toNull(a.address_line_2),
        address_line_3: toNull(a.address_line_3),
        city: toNull(a.city),
        state: toNull(a.state),
        zip: toNull(a.zip),
        country_code: toNull(a.country_code),
        is_default: isDefault,
      };
    });
    await api.patch(`/companies/${company.id}`, { addresses: payload });
    await load();
  };

  // 同 type の既定住所が既に存在するかを返す（編集中の自分自身は除外）
  const hasOtherDefault = (type: "billing" | "delivery", excludeId: number | null): boolean =>
    (company?.addresses || []).some(
      (a) => a.address_type === type && a.is_default && a.id !== excludeId,
    );

  const openAddressNew = (type: "billing" | "delivery") => {
    setAddrForm({ ...emptyAddress(type), is_default: !hasOtherDefault(type, null) });
    setAddrPhoneError(null);
    setAddrModalError(null);
    setAddrModalOpen(true);
  };

  const openAddressEdit = (a: CompanyAddress) => {
    setAddrForm(addressFromApi(a));
    setAddrPhoneError(null);
    setAddrModalError(null);
    setAddrModalOpen(true);
  };

  // F2 修正: 種別切替時に is_default を再評価（billing→delivery 切替で意図しない既定化/降格を防ぐ）
  const handleAddressTypeChange = (newType: "billing" | "delivery") => {
    setAddrForm({
      ...addrForm,
      address_type: newType,
      is_default: !hasOtherDefault(newType, addrForm.id),
    });
  };

  const handleAddressSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!company) return;
    setError("");
    setAddrModalError(null);
    const phoneErr = validatePhoneClient(addrForm.telephone);
    if (phoneErr) {
      setAddrPhoneError(phoneErr);
      return;
    }
    setAddrPhoneError(null);
    // F5 修正: country_code は空 or 2 文字のみ許容（1 文字で 422 になる前にクライアント検知）
    if (addrForm.country_code && addrForm.country_code.length !== 2) {
      setAddrModalError(t("companies.countryCodeError"));
      return;
    }
    setAddrSubmitting(true);
    try {
      // 既存配列を form 版に変換し、対象 id（新規なら追加、既存なら置換）を注入
      const currentForms = (company.addresses || []).map(addressFromApi);
      let next: AddressFormState[];
      if (addrForm.id === null) {
        next = [...currentForms, addrForm];
      } else {
        next = currentForms.map((a) => (a.id === addrForm.id ? addrForm : a));
      }
      await submitAddresses(next);
      setAddrModalOpen(false);
    } catch (err) {
      // モーダル header 直下に表示（overlay で page top の error-banner が見えない問題）
      setAddrModalError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setAddrSubmitting(false);
    }
  };

  // PR #145 Q2: 「別会社として確定」 — status を pending_dedup_review → active に戻す。
  // audit_log への記録は backend の update_company が自動で行う（A-2 PR #162）。
  // マージ判断（A-4）で消す道とは別経路で、独立した会社として承認する操作。
  const handleResolveAsDistinct = async () => {
    if (!company) return;
    setError("");
    setDedupSubmitting(true);
    try {
      await api.patch(`/companies/${company.id}`, { status: "active" });
      setDedupConfirmOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.operationError"));
      setDedupConfirmOpen(false);
    } finally {
      setDedupSubmitting(false);
    }
  };

  const handleAddressDelete = async () => {
    if (!company || !addrDeleteTarget) return;
    try {
      const next = (company.addresses || [])
        .filter((a) => a.id !== addrDeleteTarget.id)
        .map(addressFromApi);
      await submitAddresses(next);
      setAddrDeleteTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
      setAddrDeleteTarget(null);
    }
  };

  if (loading) return <div className="page-container"><p>{t("common.loading")}</p></div>;
  if (!company) {
    return (
      <div className="page-container">
        <p>{t("common.noData")}</p>
        <button onClick={() => navigate("/companies")}>{t("common.back")}</button>
      </div>
    );
  }

  const billingAddresses = company.addresses.filter((a) => a.address_type === "billing");
  const deliveryAddresses = company.addresses.filter((a) => a.address_type === "delivery");

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <button className="btn-sm" onClick={() => navigate("/companies")}>&larr; {t("common.back")}</button>
          <h1>{company.name} <span style={{ color: "var(--text-muted)", fontSize: "0.7em" }}>({company.company_code})</span></h1>
        </div>
        <div className="page-header-actions">
          <span className={`status-badge status-${company.status}`}>{company.status}</span>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="tabs">
        {/* F7 対応: 未保存の変更があるタブ移動前に確認 */}
        {(() => {
          const switchTab = (tab: Tab) => {
            if ((basicDirty || channelsDirty) && tab !== activeTab) {
              if (!window.confirm(t("companies.unsavedChangesConfirm"))) return;
              // 破棄として load() で state 戻す
              if (company) {
                setBasicForm(basicFromApi(company));
                setChannelsText(company.sales_channels.join(", "));
                setBasicDirty(false);
                setChannelsDirty(false);
              }
            }
            setActiveTab(tab);
          };
          return (
            <>
              <button className={`tab ${activeTab === "basic" ? "active" : ""}`} onClick={() => switchTab("basic")}>{t("companies.basicInfo")}</button>
              <button className={`tab ${activeTab === "addresses" ? "active" : ""}`} onClick={() => switchTab("addresses")}>
                {t("companies.address")} ({company.addresses.length})
              </button>
              <button className={`tab ${activeTab === "contacts" ? "active" : ""}`} onClick={() => switchTab("contacts")}>
                {t("contacts.title")} ({contacts.length})
              </button>
              <button className={`tab ${activeTab === "channels" ? "active" : ""}`} onClick={() => switchTab("channels")}>
                {t("nav.channels")} ({company.sales_channels.length})
              </button>
            </>
          );
        })()}
      </div>

      {activeTab === "basic" && basicForm && (
        <form onSubmit={handleBasicSubmit} className="form-grid">
          <div className="form-row"><label>{t("common.name")} *</label>
            <input required disabled={!canEdit} value={basicForm.name}
              onChange={(e) => { setBasicForm({ ...basicForm, name: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.nameEn")}</label>
            <input disabled={!canEdit} value={basicForm.name_en}
              onChange={(e) => { setBasicForm({ ...basicForm, name_en: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.industry")}</label>
            <input disabled={!canEdit} value={basicForm.industry}
              onChange={(e) => { setBasicForm({ ...basicForm, industry: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.website")}</label>
            <input disabled={!canEdit} value={basicForm.website}
              onChange={(e) => { setBasicForm({ ...basicForm, website: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.trustLevel")}</label>
            <input type="number" min="1" max="5" disabled={!canEdit} value={basicForm.trust_level}
              onChange={(e) => { setBasicForm({ ...basicForm, trust_level: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.priorityFocus")}</label>
            <input disabled={!canEdit} value={basicForm.priority_focus}
              onChange={(e) => { setBasicForm({ ...basicForm, priority_focus: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.perOrderAmount")}</label>
            <input disabled={!canEdit} value={basicForm.per_order_amount}
              onChange={(e) => { setBasicForm({ ...basicForm, per_order_amount: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.monthlyFrequency")}</label>
            <input type="number" min="0" disabled={!canEdit} value={basicForm.monthly_frequency}
              onChange={(e) => { setBasicForm({ ...basicForm, monthly_frequency: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.monthlyForecast")}</label>
            <input disabled={!canEdit} value={basicForm.monthly_forecast}
              onChange={(e) => { setBasicForm({ ...basicForm, monthly_forecast: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.billingDisplayName")}</label>
            <input disabled={!canEdit} value={basicForm.billing_display_name}
              onChange={(e) => { setBasicForm({ ...basicForm, billing_display_name: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.paymentRecipientName")}</label>
            <input disabled={!canEdit} value={basicForm.payment_recipient_name}
              onChange={(e) => { setBasicForm({ ...basicForm, payment_recipient_name: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.fedexAccount")}</label>
            <input disabled={!canEdit} value={basicForm.fedex_account}
              onChange={(e) => { setBasicForm({ ...basicForm, fedex_account: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("companies.shippingNote")}</label>
            <textarea disabled={!canEdit} value={basicForm.shipping_note}
              onChange={(e) => { setBasicForm({ ...basicForm, shipping_note: e.target.value }); setBasicDirty(true); }} />
          </div>
          <div className="form-row"><label>{t("common.status")}</label>
            <select disabled={!canEdit} value={basicForm.status}
              onChange={(e) => { setBasicForm({ ...basicForm, status: e.target.value }); setBasicDirty(true); }}>
              <option value="active">active</option>
              <option value="inactive">inactive</option>
              <option value="archived">archived</option>
              <option value="pending_dedup_review">pending_dedup_review</option>
            </select>
          </div>
          <div className="form-row"><label>{t("common.notes")}</label>
            <textarea disabled={!canEdit} value={basicForm.notes}
              onChange={(e) => { setBasicForm({ ...basicForm, notes: e.target.value }); setBasicDirty(true); }} />
          </div>
          {canEdit && (
            <div className="form-actions">
              <button type="submit" className="btn-primary" disabled={!basicDirty || basicSubmitting}>
                {basicSubmitting ? t("common.saving") : t("companies.saveBasicInfo")}
              </button>
            </div>
          )}

          {/* PR #145 Q2: pending_dedup_review 解消セクション。
              status が pending_dedup_review のときのみ表示。
              「別会社として確定」(active 化) と A-4 で実装した「重複としてマージ」の 2 択を提示する。 */}
          {canEdit && company.status === "pending_dedup_review" && (
            <div className="dedup-resolve-section">
              <h3>{t("companies.dedupResolveTitle")}</h3>
              <p>{t("companies.dedupResolveDesc")}</p>
              <div className="dedup-resolve-actions">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => setDedupConfirmOpen(true)}
                  disabled={dedupSubmitting || basicDirty}
                  title={basicDirty ? t("companies.dedupUnsavedHint") : ""}
                >
                  {t("companies.dedupConfirmAsDistinct")}
                </button>
                <button
                  type="button"
                  className="btn-danger"
                  onClick={() => setMergeModalOpen(true)}
                  disabled={!canMerge || dedupSubmitting || basicDirty}
                  title={
                    !canMerge
                      ? t("companies.dedupMergeNoPermission")
                      : basicDirty
                        ? t("companies.dedupUnsavedHint")
                        : t("companies.dedupMergeHint")
                  }
                >
                  {t("companies.dedupMergeLabel")}
                </button>
              </div>
            </div>
          )}
        </form>
      )}

      {activeTab === "addresses" && (
        <div>
          <h2>{t("companies.billing")}{t("companies.address")} ({billingAddresses.length})
            {canEdit && (
              <button className="btn-sm" style={{ marginLeft: 12 }} onClick={() => openAddressNew("billing")}>+ {t("common.add")}</button>
            )}
          </h2>
          {billingAddresses.length === 0 ? <p>{t("companies.billing")}{t("companies.address")}{t("common.noData")}</p> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("companies.branchName")}</th><th>{t("companies.contactName")}</th><th>{t("common.email")}</th><th>{t("common.phone")}</th><th>{t("companies.address")}</th><th>{t("companies.isDefault")}</th><th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {billingAddresses.map((a) => (
                  <tr key={a.id}>
                    <td>{a.branch_name || "-"}</td>
                    <td>{a.name || "-"}</td>
                    <td>{a.email || "-"}</td>
                    <td>{a.telephone || "-"}</td>
                    <td>{addressDisplay(a)}</td>
                    <td>{a.is_default ? <STATUS_ICONS.check size={14} aria-hidden="true" /> : ""}</td>
                    <td>
                      {canEdit && <button className="btn-sm" onClick={() => openAddressEdit(a)}>{t("common.edit")}</button>}
                      {canEdit && <button className="btn-sm btn-danger" onClick={() => setAddrDeleteTarget(a)}>{t("common.delete")}</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2 style={{ marginTop: 24 }}>{t("companies.delivery")}{t("companies.address")} ({deliveryAddresses.length})
            {canEdit && (
              <button className="btn-sm" style={{ marginLeft: 12 }} onClick={() => openAddressNew("delivery")}>+ {t("common.add")}</button>
            )}
          </h2>
          {deliveryAddresses.length === 0 ? <p>{t("companies.delivery")}{t("companies.address")}{t("common.noData")}</p> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("companies.branchName")}</th><th>{t("companies.contactName")}</th><th>{t("common.email")}</th><th>{t("common.phone")}</th><th>{t("companies.address")}</th><th>{t("companies.isDefault")}</th><th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {deliveryAddresses.map((a) => (
                  <tr key={a.id}>
                    <td>{a.branch_name || "-"}</td>
                    <td>{a.name || "-"}</td>
                    <td>{a.email || "-"}</td>
                    <td>{a.telephone || "-"}</td>
                    <td>{addressDisplay(a)}</td>
                    <td>{a.is_default ? <STATUS_ICONS.check size={14} aria-hidden="true" /> : ""}</td>
                    <td>
                      {canEdit && <button className="btn-sm" onClick={() => openAddressEdit(a)}>{t("common.edit")}</button>}
                      {canEdit && <button className="btn-sm btn-danger" onClick={() => setAddrDeleteTarget(a)}>{t("common.delete")}</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {activeTab === "contacts" && (
        <div>
          <div style={{ marginBottom: 12 }}>
            <Link to={`/contacts?company_id=${company.id}`} className="btn-sm">{t("contacts.title")}で{t("common.edit")}</Link>
          </div>
          {contacts.length === 0 ? <p>{t("contacts.noContacts")}</p> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("contacts.position")}</th><th>{t("contacts.isPrimary")}</th><th>{t("common.email")}</th><th>{t("common.phone")}</th><th>{t("common.status")}</th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((c) => {
                  const name = c.display_name || `${c.surname || ""} ${c.given_name || ""}`.trim() || "-";
                  return (
                    <tr key={c.id}>
                      <td>{c.contact_code}</td>
                      <td>{name}</td>
                      <td>{c.job_title || "-"}</td>
                      <td>{c.is_primary_contact ? <STATUS_ICONS.check size={14} aria-hidden="true" /> : ""}</td>
                      <td>{c.primary_email || "-"}</td>
                      <td>{c.primary_phone || "-"}</td>
                      <td><span className={`status-badge status-${c.status}`}>{c.status}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {activeTab === "channels" && (
        <form onSubmit={handleChannelsSubmit} className="form-grid">
          <div className="form-row">
            <label>{t("companies.salesChannelsLabel")}</label>
            <input disabled={!canEdit} value={channelsText}
              onChange={(e) => { setChannelsText(e.target.value); setChannelsDirty(true); }} />
            <small>{t("companies.currentValue")}: {company.sales_channels.join(", ") || `（${t("common.none")}）`}</small>
          </div>
          {canEdit && (
            <div className="form-actions">
              <button type="submit" className="btn-primary" disabled={!channelsDirty || channelsSubmitting}>
                {channelsSubmitting ? t("common.saving") : t("companies.saveChannels")}
              </button>
            </div>
          )}
        </form>
      )}

      {addrModalOpen && (
        <div className="modal-overlay" onClick={() => setAddrModalOpen(false)}>
          <div className="modal-content-wide" onClick={(e) => e.stopPropagation()}>
            <h2>
              {addrForm.id === null ? `${typeLabel(t, addrForm.address_type)}${t("companies.address")}を${t("common.add")}` : `${typeLabel(t, addrForm.address_type)}${t("companies.address")}を${t("common.edit")}`}
            </h2>
            {/* F6: モーダル内エラー（page top の error-banner は overlay で隠れる） */}
            {addrModalError && <div className="error-banner">{addrModalError}</div>}
            <form onSubmit={handleAddressSave} className="form-grid">
              <div className="form-row">
                <label>{t("common.type")}</label>
                <select disabled={!canEdit || addrSubmitting} value={addrForm.address_type}
                  onChange={(e) => handleAddressTypeChange(e.target.value as "billing" | "delivery")}>
                  <option value="billing">{t("companies.billing")}</option>
                  <option value="delivery">{t("companies.delivery")}</option>
                </select>
              </div>
              <div className="form-row">
                <label>{t("companies.branchNameHint")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.branch_name}
                  onChange={(e) => setAddrForm({ ...addrForm, branch_name: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("companies.contactName")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.name}
                  onChange={(e) => setAddrForm({ ...addrForm, name: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("common.email")}</label>
                <input type="email" disabled={!canEdit || addrSubmitting} value={addrForm.email}
                  onChange={(e) => setAddrForm({ ...addrForm, email: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("common.phone")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.telephone}
                  onChange={(e) => setAddrForm({ ...addrForm, telephone: e.target.value })} />
                {addrPhoneError && <span className="field-error">{addrPhoneError}</span>}
              </div>
              <div className="form-row"><label>{t("companies.taxId")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.tax_id}
                  onChange={(e) => setAddrForm({ ...addrForm, tax_id: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.address1")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.address_line_1}
                  onChange={(e) => setAddrForm({ ...addrForm, address_line_1: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.address2")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.address_line_2}
                  onChange={(e) => setAddrForm({ ...addrForm, address_line_2: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.address3")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.address_line_3}
                  onChange={(e) => setAddrForm({ ...addrForm, address_line_3: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.city")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.city}
                  onChange={(e) => setAddrForm({ ...addrForm, city: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.stateCode")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.state}
                  onChange={(e) => setAddrForm({ ...addrForm, state: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.zipCode")}</label>
                <input disabled={!canEdit || addrSubmitting} value={addrForm.zip}
                  onChange={(e) => setAddrForm({ ...addrForm, zip: e.target.value })} />
              </div>
              <div className="form-row"><label>{t("shipping.countryCode")}{t("companies.countryCodeHint")}</label>
                <input maxLength={2} disabled={!canEdit || addrSubmitting} value={addrForm.country_code}
                  onChange={(e) => setAddrForm({ ...addrForm, country_code: e.target.value.toUpperCase() })} />
              </div>
              <div className="form-row">
                <label>
                  <input type="checkbox" disabled={!canEdit || addrSubmitting} checked={addrForm.is_default}
                    onChange={(e) => setAddrForm({ ...addrForm, is_default: e.target.checked })} />
                  {" "}{t("companies.setAsDefault")}
                </label>
              </div>
              <div className="form-actions">
                <button type="button" onClick={() => setAddrModalOpen(false)} disabled={addrSubmitting}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary" disabled={!canEdit || addrSubmitting}>
                  {addrSubmitting ? t("common.saving") : t("common.save")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmModal
        open={addrDeleteTarget !== null}
        title={t("companies.deleteAddressTitle")}
        message={
          addrDeleteTarget
            ? `${typeLabel(t, addrDeleteTarget.address_type)}${t("companies.address")}「${addrDeleteTarget.branch_name || addrDeleteTarget.name || "(無名)"}」を${t("common.delete")}しますか？`
            : ""
        }
        confirmLabel={t("common.delete")}
        onConfirm={handleAddressDelete}
        onCancel={() => setAddrDeleteTarget(null)}
      />

      {/* PR #145 Q2: 別会社として確定の確認ダイアログ */}
      <ConfirmModal
        open={dedupConfirmOpen}
        title={t("companies.dedupResolveTitle")}
        message={t("companies.dedupResolveConfirmMessage", { name: company.name })}
        confirmLabel={t("companies.dedupResolveConfirmLabel")}
        onConfirm={handleResolveAsDistinct}
        onCancel={() => setDedupConfirmOpen(false)}
      />

      {/* A-4: 重複マージモーダル。本会社を merge 元として、master を選んで吸収させる */}
      <MergeCompanyModal
        open={mergeModalOpen}
        source={{ id: company.id, name: company.name, company_code: company.company_code }}
        onMerged={(masterId) => {
          setMergeModalOpen(false);
          // 本会社は削除済みなので master の詳細ページに遷移する
          navigate(`/companies/${masterId}`);
        }}
        onCancel={() => setMergeModalOpen(false)}
      />
    </div>
  );
}

/**
 * 顧客管理ページ。Phase 1 再設計版。
 *
 * 変更履歴:
 *   2026-04-16: Phase 1拡張（請求先/配送先、顧客コード、ステータス表示）
 *   2026-04-23: Phase 1 再設計（副テーブル化、ネスト構造対応）
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

const PHONE_RE = /^(\+?\d{10,15}|0\d{9,10})$/;
const validatePhoneClient = (raw: string): string | null => {
  if (!raw) return null;
  const cleaned = raw.replace(/[\s\-()]/g, "");
  return PHONE_RE.test(cleaned) ? null : "電話番号の形式が正しくありません（例: 03-1234-5678, 090-1234-5678）";
};

interface CustomerAddress {
  id: number;
  address_type: "billing" | "delivery";
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
}

interface CustomerDiscord {
  is_joined: boolean;
  channel_id: string | null;
  user_id: string | null;
  invoice_webhook: string | null;
  shipment_webhook: string | null;
}

interface CustomerContactChannel {
  id: number;
  channel: string;
  purpose: string | null;
  is_primary: boolean;
}

interface Customer {
  id: number;
  tenant_id: number;
  customer_code: string;
  lead_id: number | null;
  sales_rep_id: number | null;
  company_name: string | null;
  trust_level: number | null;
  priority_focus: string | null;
  per_order_amount: string | null;
  monthly_frequency: number | null;
  monthly_forecast: string | null;
  monthly_forecast_source: "manual" | "ai_analysis" | null;
  monthly_forecast_updated_at: string | null;
  meeting_requested: boolean;
  billing_display_name: string | null;
  payment_recipient_name: string | null;
  fedex_account: string | null;
  shipping_note: string | null;
  primary_contact_channel: string | null;
  status: string;
  addresses: CustomerAddress[];
  sales_channels: string[];
  discord: CustomerDiscord | null;
  contact_channels: CustomerContactChannel[];
  created_at: string;
  updated_at: string;
}

// ネスト構造に対応したフォーム状態
type AddressFormState = {
  address_type: "billing" | "delivery";
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
};

const emptyBilling: AddressFormState = {
  address_type: "billing",
  name: "", email: "", telephone: "", tax_id: "",
  address_line_1: "", address_line_2: "", address_line_3: "",
  city: "", state: "", zip: "", country_code: "",
};
const emptyDelivery: AddressFormState = { ...emptyBilling, address_type: "delivery" };

type ContactChannelFormState = {
  channel: string;
  purpose: string;
  is_primary: boolean;
};

type FormState = {
  customer_code: string;
  company_name: string;
  trust_level: string;   // UI input として string
  priority_focus: string;
  per_order_amount: string;
  monthly_frequency: string;
  monthly_forecast: string;
  meeting_requested: boolean;
  billing_display_name: string;
  payment_recipient_name: string;
  fedex_account: string;
  shipping_note: string;
  primary_contact_channel: string;
  status: string;
  billing: AddressFormState;
  delivery: AddressFormState;
  sales_channels: string;   // カンマ区切り UI 入力
  contact_channels: ContactChannelFormState[];  // Phase 1-B-1
  discord_enabled: boolean;
  discord_channel_id: string;
  discord_user_id: string;
  discord_invoice_webhook: string;
  discord_shipment_webhook: string;
};

const emptyForm: FormState = {
  customer_code: "",
  company_name: "",
  trust_level: "",
  priority_focus: "",
  per_order_amount: "",
  monthly_frequency: "",
  monthly_forecast: "",
  meeting_requested: false,
  billing_display_name: "",
  payment_recipient_name: "",
  fedex_account: "",
  shipping_note: "",
  primary_contact_channel: "",
  status: "active",
  billing: { ...emptyBilling },
  delivery: { ...emptyDelivery },
  sales_channels: "",
  contact_channels: [],
  discord_enabled: false,
  discord_channel_id: "",
  discord_user_id: "",
  discord_invoice_webhook: "",
  discord_shipment_webhook: "",
};

// Phase 1-B-1: 連絡ツール別テーブル。"channels" タブでネスト編集
type Tab = "basic" | "billing" | "delivery" | "channels" | "discord";

/** レスポンスの顧客名として表示する優先順位: billing_display_name > billing.name > company_name */
const customerDisplayName = (c: Customer): string => {
  if (c.billing_display_name) return c.billing_display_name;
  const billing = c.addresses.find((a) => a.address_type === "billing");
  if (billing?.name) return billing.name;
  return c.company_name || c.customer_code || "-";
};

const addressDisplay = (a: CustomerAddress | undefined): string => {
  if (!a) return "-";
  return a.email || a.telephone || a.city || "-";
};

export default function CustomersPage() {
  const { t } = useTranslation();
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
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);
  // Discord タブをユーザーが触ったかどうか（PATCH 時の discord フィールド送信判定）
  // 未タッチなら payload から discord を omit して既存 row の誤削除/上書きを防ぐ
  const [discordTouched, setDiscordTouched] = useState(false);

  const loadCustomers = async () => {
    try {
      const params = search ? `?search=${encodeURIComponent(search)}` : "";
      const data = await api.get<Customer[]>(`/customers${params}`);
      setCustomers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadCustomers(); }, [search]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    // 請求先電話だけクライアント検証
    const phoneErr = validatePhoneClient(form.billing.telephone);
    if (phoneErr) {
      setPhoneError(phoneErr);
      setActiveTab("billing");
      return;
    }
    setPhoneError(null);

    const toNull = (v: string) => (v ? v : null);
    const strOrNull = (v: string) => (v ? v : null);
    const addressHasAnyValue = (a: AddressFormState) =>
      a.name || a.email || a.telephone || a.tax_id ||
      a.address_line_1 || a.address_line_2 || a.address_line_3 ||
      a.city || a.state || a.zip || a.country_code;

    const addresses: Record<string, unknown>[] = [];
    if (addressHasAnyValue(form.billing)) {
      addresses.push({
        address_type: "billing",
        name: strOrNull(form.billing.name),
        email: strOrNull(form.billing.email),
        telephone: strOrNull(form.billing.telephone),
        tax_id: strOrNull(form.billing.tax_id),
        address_line_1: strOrNull(form.billing.address_line_1),
        address_line_2: strOrNull(form.billing.address_line_2),
        address_line_3: strOrNull(form.billing.address_line_3),
        city: strOrNull(form.billing.city),
        state: strOrNull(form.billing.state),
        zip: strOrNull(form.billing.zip),
        country_code: strOrNull(form.billing.country_code),
      });
    }
    if (addressHasAnyValue(form.delivery)) {
      addresses.push({
        address_type: "delivery",
        name: strOrNull(form.delivery.name),
        email: strOrNull(form.delivery.email),
        telephone: strOrNull(form.delivery.telephone),
        tax_id: strOrNull(form.delivery.tax_id),
        address_line_1: strOrNull(form.delivery.address_line_1),
        address_line_2: strOrNull(form.delivery.address_line_2),
        address_line_3: strOrNull(form.delivery.address_line_3),
        city: strOrNull(form.delivery.city),
        state: strOrNull(form.delivery.state),
        zip: strOrNull(form.delivery.zip),
        country_code: strOrNull(form.delivery.country_code),
      });
    }

    const salesChannels = form.sales_channels
      .split(/[,、，]/)   // 全角カンマも許容
      .map((s) => s.trim())
      .filter(Boolean);

    // Phase 1-B-1: 複数連絡ツール。channel 空白行は filter で除外
    const contactChannels = form.contact_channels
      .map((c) => ({
        channel: c.channel.trim(),
        purpose: c.purpose.trim() || null,
        is_primary: c.is_primary,
      }))
      .filter((c) => c.channel);

    const discord = form.discord_enabled
      ? {
          is_joined: true,
          channel_id: toNull(form.discord_channel_id),
          user_id: toNull(form.discord_user_id),
          invoice_webhook: toNull(form.discord_invoice_webhook),
          shipment_webhook: toNull(form.discord_shipment_webhook),
        }
      : null;

    const payload: Record<string, unknown> = {
      company_name: toNull(form.company_name),
      trust_level: form.trust_level ? parseInt(form.trust_level, 10) : null,
      priority_focus: toNull(form.priority_focus),
      per_order_amount: form.per_order_amount || null,
      monthly_frequency: form.monthly_frequency ? parseInt(form.monthly_frequency, 10) : null,
      monthly_forecast: form.monthly_forecast || null,
      meeting_requested: form.meeting_requested,
      billing_display_name: toNull(form.billing_display_name),
      payment_recipient_name: toNull(form.payment_recipient_name),
      fedex_account: toNull(form.fedex_account),
      shipping_note: toNull(form.shipping_note),
      primary_contact_channel: toNull(form.primary_contact_channel),
      status: form.status || "active",
      addresses,
      sales_channels: salesChannels,
      contact_channels: contactChannels,
    };
    // discord: 新規時は常に送る。編集時は「Discord タブを触った場合のみ」送信する
    // （未タッチで discord=null を送ると既存 customer_discord 行が削除されるため、reviewer F1）
    if (!editId || discordTouched) {
      payload.discord = discord;
    }
    // 新規時のみ customer_code を送る（明示指定可）
    if (!editId && form.customer_code.trim()) {
      payload.customer_code = form.customer_code.trim();
    }

    if (submitting) return;  // 二重送信ガード
    setSubmitting(true);
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
      setDiscordTouched(false);
      loadCustomers();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = (c: Customer) => {
    const b = c.addresses.find((a) => a.address_type === "billing");
    const d = c.addresses.find((a) => a.address_type === "delivery");
    const mk = (a: CustomerAddress | undefined, def: AddressFormState): AddressFormState =>
      a ? {
        address_type: a.address_type,
        name: a.name || "", email: a.email || "", telephone: a.telephone || "",
        tax_id: a.tax_id || "",
        address_line_1: a.address_line_1 || "", address_line_2: a.address_line_2 || "", address_line_3: a.address_line_3 || "",
        city: a.city || "", state: a.state || "", zip: a.zip || "",
        country_code: a.country_code || "",
      } : def;

    setEditId(c.id);
    setForm({
      customer_code: c.customer_code,
      company_name: c.company_name || "",
      trust_level: c.trust_level !== null ? String(c.trust_level) : "",
      priority_focus: c.priority_focus || "",
      per_order_amount: c.per_order_amount || "",
      monthly_frequency: c.monthly_frequency !== null ? String(c.monthly_frequency) : "",
      monthly_forecast: c.monthly_forecast || "",
      meeting_requested: c.meeting_requested,
      billing_display_name: c.billing_display_name || "",
      payment_recipient_name: c.payment_recipient_name || "",
      fedex_account: c.fedex_account || "",
      shipping_note: c.shipping_note || "",
      primary_contact_channel: c.primary_contact_channel || "",
      status: c.status || "active",
      billing: mk(b, { ...emptyBilling }),
      delivery: mk(d, { ...emptyDelivery }),
      sales_channels: c.sales_channels.join(", "),
      contact_channels: c.contact_channels.map((ch) => ({
        channel: ch.channel,
        purpose: ch.purpose || "",
        is_primary: ch.is_primary,
      })),
      discord_enabled: c.discord?.is_joined || false,
      discord_channel_id: c.discord?.channel_id || "",
      discord_user_id: c.discord?.user_id || "",
      discord_invoice_webhook: c.discord?.invoice_webhook || "",
      discord_shipment_webhook: c.discord?.shipment_webhook || "",
    });
    setPhoneError(null);
    setActiveTab("basic");
    setDiscordTouched(false);  // 編集開始時はタッチされていない状態に
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
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const statusLabel = (s: string): string => {
    switch (s) {
      case "active": return t("customers.status_active");
      case "inactive": return t("customers.status_inactive");
      case "archived": return t("customers.status_archived");
      case "pending_dedup_review": return "重複確認待ち";
      default: return s;
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("customers.title")}</h2>
        {hasPermission("customers.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); setPhoneError(null); setActiveTab("basic"); setDiscordTouched(false); }}>
            {t("customers.newCustomer")}
          </button>
        )}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder={t("customers.searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("customers.editCustomer") : t("customers.newCustomer")}</h3>
            <div className="tab-nav">
              <button type="button" className={activeTab === "basic" ? "tab-active" : ""} onClick={() => setActiveTab("basic")}>{t("customers.tab_basic")}</button>
              <button type="button" className={activeTab === "billing" ? "tab-active" : ""} onClick={() => setActiveTab("billing")}>{t("customers.tab_billing")}</button>
              <button type="button" className={activeTab === "delivery" ? "tab-active" : ""} onClick={() => setActiveTab("delivery")}>{t("customers.tab_delivery")}</button>
              <button type="button" className={activeTab === "channels" ? "tab-active" : ""} onClick={() => setActiveTab("channels")}>{t("customers.tab_channels")}</button>
              <button type="button" className={activeTab === "discord" ? "tab-active" : ""} onClick={() => setActiveTab("discord")}>{t("customers.tab_discord")}</button>
            </div>
            <form onSubmit={handleSubmit}>
              {activeTab === "basic" && (
                <>
                  <div className="form-group">
                    <label>{t("customers.field_companyName")}</label>
                    <input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
                  </div>
                  {!editId && (
                    <div className="form-group">
                      <label>{t("customers.field_customerCodeFull")}</label>
                      <input value={form.customer_code} placeholder="例: CT-00001" onChange={(e) => setForm({ ...form, customer_code: e.target.value })} />
                    </div>
                  )}
                  <div className="form-group">
                    <label>{t("customers.field_billingName")}</label>
                    <input value={form.billing_display_name} onChange={(e) => setForm({ ...form, billing_display_name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_paymentRecipient")}</label>
                    <input value={form.payment_recipient_name} onChange={(e) => setForm({ ...form, payment_recipient_name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_primaryChannel")}</label>
                    <select value={form.primary_contact_channel} onChange={(e) => setForm({ ...form, primary_contact_channel: e.target.value })}>
                      <option value="">{t("customers.option_unselected")}</option>
                      <option value="whatsapp">WhatsApp</option>
                      <option value="instagram">Instagram</option>
                      <option value="facebook_messenger">Facebook Messenger</option>
                      <option value="discord">Discord</option>
                      <option value="line_id">LINE</option>
                      <option value="telegram">Telegram</option>
                      <option value="email">{t("customers.option_email")}</option>
                      <option value="phone">{t("customers.option_phone")}</option>
                      <option value="referral">{t("customers.option_referral")}</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_salesChannels")}</label>
                    <input value={form.sales_channels} onChange={(e) => setForm({ ...form, sales_channels: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_trustLevelFull")}</label>
                    <select value={form.trust_level} onChange={(e) => setForm({ ...form, trust_level: e.target.value })}>
                      <option value="">{t("customers.option_unset")}</option>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_priorityFocus")}</label>
                    <input value={form.priority_focus} placeholder="例: 価格重視 / 信頼重視 / 品質重視" onChange={(e) => setForm({ ...form, priority_focus: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_perOrderAmount")}</label>
                    <input type="number" min="0" step="0.01" value={form.per_order_amount} onChange={(e) => setForm({ ...form, per_order_amount: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_monthlyFrequency")}</label>
                    <input type="number" min="0" value={form.monthly_frequency} onChange={(e) => setForm({ ...form, monthly_frequency: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_monthlyForecast")}</label>
                    <input type="number" min="0" step="0.01" value={form.monthly_forecast} onChange={(e) => setForm({ ...form, monthly_forecast: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>
                      <input type="checkbox" checked={form.meeting_requested} onChange={(e) => setForm({ ...form, meeting_requested: e.target.checked })} />
                      {" "}{t("customers.field_meetingRequested")}
                    </label>
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_fedexAccount")}</label>
                    <input value={form.fedex_account} onChange={(e) => setForm({ ...form, fedex_account: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.field_shippingNote")}</label>
                    <textarea value={form.shipping_note} onChange={(e) => setForm({ ...form, shipping_note: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>{t("customers.status")}</label>
                    <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                      <option value="active">{t("customers.status_active")}</option>
                      <option value="inactive">{t("customers.status_inactive")}</option>
                      <option value="archived">{t("customers.status_archived")}</option>
                      <option value="pending_dedup_review">{t("customers.status_pending_dedup")}</option>
                    </select>
                  </div>
                </>
              )}
              {(activeTab === "billing" || activeTab === "delivery") && (
                (() => {
                  const key = activeTab;  // "billing" | "delivery"
                  const addr = form[key];
                  const updateAddr = (patch: Partial<AddressFormState>) =>
                    setForm({ ...form, [key]: { ...addr, ...patch } });
                  return (
                    <>
                      <div className="form-group"><label>{t("customers.addr_name")}</label>
                        <input value={addr.name} onChange={(e) => updateAddr({ name: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_email")}</label>
                        <input type="email" value={addr.email} onChange={(e) => updateAddr({ email: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_phone")}</label>
                        <input
                          value={addr.telephone}
                          placeholder="例: +81-90-1234-5678 / 03-1234-5678"
                          onChange={(e) => { updateAddr({ telephone: e.target.value }); if (phoneError && key === "billing") setPhoneError(null); }}
                          onBlur={(e) => { if (key === "billing") setPhoneError(validatePhoneClient(e.target.value)); }}
                        />
                        {key === "billing" && phoneError && <div className="error-message" style={{ marginTop: "var(--space-1)" }}>{t("customers.phoneError")}</div>}
                      </div>
                      <div className="form-group"><label>{t("customers.addr_taxId")}</label>
                        <input value={addr.tax_id} onChange={(e) => updateAddr({ tax_id: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_line1")}</label>
                        <input value={addr.address_line_1} onChange={(e) => updateAddr({ address_line_1: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_line2")}</label>
                        <input value={addr.address_line_2} onChange={(e) => updateAddr({ address_line_2: e.target.value })} />
                      </div>
                      {key === "delivery" && (
                        <div className="form-group"><label>{t("customers.addr_line3")}</label>
                          <input value={addr.address_line_3} onChange={(e) => updateAddr({ address_line_3: e.target.value })} />
                        </div>
                      )}
                      <div className="form-group"><label>{t("customers.addr_city")}</label>
                        <input value={addr.city} onChange={(e) => updateAddr({ city: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_state")}</label>
                        <input value={addr.state} onChange={(e) => updateAddr({ state: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_zip")}</label>
                        <input value={addr.zip} onChange={(e) => updateAddr({ zip: e.target.value })} />
                      </div>
                      <div className="form-group"><label>{t("customers.addr_country")}</label>
                        <input maxLength={2} style={{ textTransform: "uppercase" }} value={addr.country_code} onChange={(e) => updateAddr({ country_code: e.target.value.toUpperCase() })} />
                      </div>
                    </>
                  );
                })()
              )}
              {activeTab === "channels" && (
                <>
                  <div style={{ fontSize: "0.9em", color: "var(--text-muted)", marginBottom: "var(--space-3)" }}>
                    {t("customers.channels_desc")}
                  </div>
                  {form.contact_channels.map((ch, idx) => (
                    <div key={idx} className="form-group" style={{ border: "1px solid var(--border-light)", padding: "var(--space-2)", borderRadius: 4, marginBottom: "var(--space-2)" }}>
                      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}>
                        <div style={{ flex: 1 }}>
                          <label>{t("customers.channel_label")}</label>
                          <select value={ch.channel} onChange={(e) => {
                            const next = [...form.contact_channels];
                            next[idx] = { ...ch, channel: e.target.value };
                            setForm({ ...form, contact_channels: next });
                          }}>
                            <option value="">{t("customers.channel_select")}</option>
                            <option value="whatsapp">WhatsApp</option>
                            <option value="instagram">Instagram</option>
                            <option value="facebook_messenger">Facebook Messenger</option>
                            <option value="discord">Discord</option>
                            <option value="line_id">LINE</option>
                            <option value="telegram">Telegram</option>
                            <option value="email">{t("customers.option_email")}</option>
                            <option value="phone">{t("customers.option_phone")}</option>
                            <option value="referral">{t("customers.option_referral")}</option>
                          </select>
                        </div>
                        <div style={{ flex: 2 }}>
                          <label>{t("customers.channel_purpose")}</label>
                          <input value={ch.purpose} placeholder="例: 商談用 / 発送通知用" onChange={(e) => {
                            const next = [...form.contact_channels];
                            next[idx] = { ...ch, purpose: e.target.value };
                            setForm({ ...form, contact_channels: next });
                          }} />
                        </div>
                        <div style={{ flex: "0 0 auto" }}>
                          <label style={{ display: "block" }}>
                            <input type="checkbox" checked={ch.is_primary} onChange={(e) => {
                              // 主連絡ツールは1つだけ ON にする
                              const next = form.contact_channels.map((c, i) => ({
                                ...c, is_primary: i === idx ? e.target.checked : false,
                              }));
                              setForm({ ...form, contact_channels: next });
                            }} />
                            {" "}{t("customers.channel_primary")}
                          </label>
                        </div>
                        <button type="button" className="btn-sm btn-danger" onClick={() => {
                          const next = form.contact_channels.filter((_, i) => i !== idx);
                          setForm({ ...form, contact_channels: next });
                        }}>{t("common.delete")}</button>
                      </div>
                    </div>
                  ))}
                  <button type="button" className="btn-secondary" onClick={() => {
                    setForm({
                      ...form,
                      contact_channels: [...form.contact_channels, { channel: "", purpose: "", is_primary: false }],
                    });
                  }}>{t("customers.channel_add")}</button>
                </>
              )}
              {activeTab === "discord" && (
                <>
                  <div className="form-group">
                    <label>
                      <input type="checkbox" checked={form.discord_enabled} onChange={(e) => { setForm({ ...form, discord_enabled: e.target.checked }); setDiscordTouched(true); }} />
                      {" "}{t("customers.discord_enable")}
                    </label>
                  </div>
                  {form.discord_enabled && (
                    <>
                      <div className="form-group"><label>{t("customers.discord_channelId")}</label>
                        <input value={form.discord_channel_id} onChange={(e) => { setForm({ ...form, discord_channel_id: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                      <div className="form-group"><label>{t("customers.discord_userId")}</label>
                        <input value={form.discord_user_id} onChange={(e) => { setForm({ ...form, discord_user_id: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                      <div className="form-group"><label>{t("customers.discord_invoiceWebhook")}</label>
                        <input value={form.discord_invoice_webhook} onChange={(e) => { setForm({ ...form, discord_invoice_webhook: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                      <div className="form-group"><label>{t("customers.discord_shipmentWebhook")}</label>
                        <input value={form.discord_shipment_webhook} onChange={(e) => { setForm({ ...form, discord_shipment_webhook: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                    </>
                  )}
                  {editId && !discordTouched && (
                    <div style={{ fontSize: "0.85em", color: "var(--text-muted)", marginTop: "var(--space-2)" }}>
                      {t("customers.discord_unchanged")}
                    </div>
                  )}
                </>
              )}
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)} disabled={submitting}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? t("common.saving") : editId ? t("common.update") : t("common.register")}
                </button>
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
              <th>{t("common.code")}</th>
              <th>{t("customers.title")}</th>
              <th>{t("customers.companyName")}</th>
              <th>{t("companies.billing")}</th>
              <th>{t("companies.delivery")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => {
              const billing = c.addresses.find((a) => a.address_type === "billing");
              const delivery = c.addresses.find((a) => a.address_type === "delivery");
              return (
                <tr key={c.id}>
                  <td className="mono">{c.customer_code}</td>
                  <td>{customerDisplayName(c)}</td>
                  <td>{c.company_name || "-"}</td>
                  <td>{addressDisplay(billing)}</td>
                  <td>{addressDisplay(delivery)}</td>
                  <td>
                    <span className={`badge badge-${c.status === "active" ? "won" : c.status === "pending_dedup_review" ? "pending" : "lost"}`}>
                      {statusLabel(c.status)}
                    </span>
                  </td>
                  <td className="actions">
                    {hasPermission("customers.update") && <button className="btn-sm" onClick={() => handleEdit(c)}>{t("common.edit")}</button>}
                    {hasPermission("customers.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(c)}>{t("common.delete")}</button>}
                  </td>
                </tr>
              );
            })}
            {customers.length === 0 && (
              <tr><td colSpan={7} className="empty">{t("customers.noCustomers")}</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("customers.deleteCustomer")}
        message={
          <>
            <strong>{deleteTarget && customerDisplayName(deleteTarget)}</strong> {t("customers.deleteConfirmSuffix")}<br />
            {t("customers.deleteConstraint")}<br />
            {t("common.irreversible")}
          </>
        }
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

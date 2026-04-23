/**
 * 顧客管理ページ。Phase 1 再設計版。
 *
 * 変更履歴:
 *   2026-04-16: Phase 1拡張（請求先/配送先、顧客コード、ステータス表示）
 *   2026-04-23: Phase 1 再設計（副テーブル化、ネスト構造対応）
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
  discord_enabled: false,
  discord_channel_id: "",
  discord_user_id: "",
  discord_invoice_webhook: "",
  discord_shipment_webhook: "",
};

type Tab = "basic" | "billing" | "delivery" | "discord";

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
      setError(e instanceof Error ? e.message : "取得に失敗しました");
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
      setError(e instanceof Error ? e.message : "保存に失敗しました");
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
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const statusLabel = (s: string): string => {
    switch (s) {
      case "active": return "有効";
      case "inactive": return "無効";
      case "archived": return "アーカイブ";
      case "pending_dedup_review": return "重複確認待ち";
      default: return s;
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>顧客管理</h2>
        {hasPermission("customers.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); setPhoneError(null); setActiveTab("basic"); setDiscordTouched(false); }}>
            新規登録
          </button>
        )}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="会社名・顧客コード・請求名義で検索..."
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
              <button type="button" className={activeTab === "discord" ? "tab-active" : ""} onClick={() => setActiveTab("discord")}>Discord</button>
            </div>
            <form onSubmit={handleSubmit}>
              {activeTab === "basic" && (
                <>
                  <div className="form-group">
                    <label>会社名 / 顧客名</label>
                    <input value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
                  </div>
                  {!editId && (
                    <div className="form-group">
                      <label>顧客コード（空欄なら自動採番 CT-00001 形式）</label>
                      <input value={form.customer_code} placeholder="例: CT-00001" onChange={(e) => setForm({ ...form, customer_code: e.target.value })} />
                    </div>
                  )}
                  <div className="form-group">
                    <label>請求書宛名（会社名と別にする場合のみ）</label>
                    <input value={form.billing_display_name} onChange={(e) => setForm({ ...form, billing_display_name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>支払い名義（WISE/PayPal 送金時の名義が違う場合）</label>
                    <input value={form.payment_recipient_name} onChange={(e) => setForm({ ...form, payment_recipient_name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>主連絡ツール</label>
                    <select value={form.primary_contact_channel} onChange={(e) => setForm({ ...form, primary_contact_channel: e.target.value })}>
                      <option value="">（未選択）</option>
                      <option value="whatsapp">WhatsApp</option>
                      <option value="instagram">Instagram</option>
                      <option value="facebook_messenger">Facebook Messenger</option>
                      <option value="discord">Discord</option>
                      <option value="line_id">LINE</option>
                      <option value="telegram">Telegram</option>
                      <option value="email">メール</option>
                      <option value="phone">電話</option>
                      <option value="referral">紹介</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>販売チャネル（カンマ区切り。例: EC, 実店舗, 配信）</label>
                    <input value={form.sales_channels} onChange={(e) => setForm({ ...form, sales_channels: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>信頼度（1〜5）</label>
                    <select value={form.trust_level} onChange={(e) => setForm({ ...form, trust_level: e.target.value })}>
                      <option value="">（未設定）</option>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>重視ポイント</label>
                    <input value={form.priority_focus} placeholder="例: 価格重視 / 信頼重視 / 品質重視" onChange={(e) => setForm({ ...form, priority_focus: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>1回発注額</label>
                    <input type="number" min="0" step="0.01" value={form.per_order_amount} onChange={(e) => setForm({ ...form, per_order_amount: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>月間頻度</label>
                    <input type="number" min="0" value={form.monthly_frequency} onChange={(e) => setForm({ ...form, monthly_frequency: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>月間売上見込額</label>
                    <input type="number" min="0" step="0.01" value={form.monthly_forecast} onChange={(e) => setForm({ ...form, monthly_forecast: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>
                      <input type="checkbox" checked={form.meeting_requested} onChange={(e) => setForm({ ...form, meeting_requested: e.target.checked })} />
                      {" "}面談希望
                    </label>
                  </div>
                  <div className="form-group">
                    <label>FedEx アカウント</label>
                    <input value={form.fedex_account} onChange={(e) => setForm({ ...form, fedex_account: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>発送時メモ</label>
                    <textarea value={form.shipping_note} onChange={(e) => setForm({ ...form, shipping_note: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>ステータス</label>
                    <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                      <option value="active">有効</option>
                      <option value="inactive">無効</option>
                      <option value="archived">アーカイブ</option>
                      <option value="pending_dedup_review">重複確認待ち</option>
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
                      <div className="form-group"><label>宛名</label>
                        <input value={addr.name} onChange={(e) => updateAddr({ name: e.target.value })} />
                      </div>
                      <div className="form-group"><label>メール</label>
                        <input type="email" value={addr.email} onChange={(e) => updateAddr({ email: e.target.value })} />
                      </div>
                      <div className="form-group"><label>電話番号</label>
                        <input
                          value={addr.telephone}
                          placeholder="例: +81-90-1234-5678 / 03-1234-5678"
                          onChange={(e) => { updateAddr({ telephone: e.target.value }); if (phoneError && key === "billing") setPhoneError(null); }}
                          onBlur={(e) => { if (key === "billing") setPhoneError(validatePhoneClient(e.target.value)); }}
                        />
                        {key === "billing" && phoneError && <div className="error-message" style={{ marginTop: 4 }}>{phoneError}</div>}
                      </div>
                      <div className="form-group"><label>税番号（VAT / EIN 等）</label>
                        <input value={addr.tax_id} onChange={(e) => updateAddr({ tax_id: e.target.value })} />
                      </div>
                      <div className="form-group"><label>住所行1</label>
                        <input value={addr.address_line_1} onChange={(e) => updateAddr({ address_line_1: e.target.value })} />
                      </div>
                      <div className="form-group"><label>住所行2</label>
                        <input value={addr.address_line_2} onChange={(e) => updateAddr({ address_line_2: e.target.value })} />
                      </div>
                      {key === "delivery" && (
                        <div className="form-group"><label>住所行3</label>
                          <input value={addr.address_line_3} onChange={(e) => updateAddr({ address_line_3: e.target.value })} />
                        </div>
                      )}
                      <div className="form-group"><label>市区町村</label>
                        <input value={addr.city} onChange={(e) => updateAddr({ city: e.target.value })} />
                      </div>
                      <div className="form-group"><label>州・県</label>
                        <input value={addr.state} onChange={(e) => updateAddr({ state: e.target.value })} />
                      </div>
                      <div className="form-group"><label>郵便番号</label>
                        <input value={addr.zip} onChange={(e) => updateAddr({ zip: e.target.value })} />
                      </div>
                      <div className="form-group"><label>国コード（ISO 3166-1 alpha-2、例: JP, US, GB）</label>
                        <input maxLength={2} style={{ textTransform: "uppercase" }} value={addr.country_code} onChange={(e) => updateAddr({ country_code: e.target.value.toUpperCase() })} />
                      </div>
                    </>
                  );
                })()
              )}
              {activeTab === "discord" && (
                <>
                  <div className="form-group">
                    <label>
                      <input type="checkbox" checked={form.discord_enabled} onChange={(e) => { setForm({ ...form, discord_enabled: e.target.checked }); setDiscordTouched(true); }} />
                      {" "}Discord 連携を有効にする
                    </label>
                  </div>
                  {form.discord_enabled && (
                    <>
                      <div className="form-group"><label>チャンネル ID</label>
                        <input value={form.discord_channel_id} onChange={(e) => { setForm({ ...form, discord_channel_id: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                      <div className="form-group"><label>ユーザー ID</label>
                        <input value={form.discord_user_id} onChange={(e) => { setForm({ ...form, discord_user_id: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                      <div className="form-group"><label>請求書 Webhook URL</label>
                        <input value={form.discord_invoice_webhook} onChange={(e) => { setForm({ ...form, discord_invoice_webhook: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                      <div className="form-group"><label>発送通知 Webhook URL</label>
                        <input value={form.discord_shipment_webhook} onChange={(e) => { setForm({ ...form, discord_shipment_webhook: e.target.value }); setDiscordTouched(true); }} />
                      </div>
                    </>
                  )}
                  {editId && !discordTouched && (
                    <div style={{ fontSize: "0.85em", color: "#666", marginTop: 8 }}>
                      ※ 何も変更しなければ Discord 情報は既存のまま保持されます
                    </div>
                  )}
                </>
              )}
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)} disabled={submitting}>キャンセル</button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? "送信中..." : editId ? "更新" : "登録"}
                </button>
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
              <th>請求先連絡</th>
              <th>配送先連絡</th>
              <th>ステータス</th>
              <th>操作</th>
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
                    {hasPermission("customers.update") && <button className="btn-sm" onClick={() => handleEdit(c)}>編集</button>}
                    {hasPermission("customers.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(c)}>削除</button>}
                  </td>
                </tr>
              );
            })}
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
            <strong>{deleteTarget && customerDisplayName(deleteTarget)}</strong> を削除します。<br />
            関連する商談・注文・見積・請求書がある場合は削除できません（先にそれらを削除してください）。<br />
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

/**
 * 会社管理ページ。Phase 1-B-2 Step 5c-1 で新設。
 *
 * 新 B2B モデルの会社一覧・CRUD。既存 CustomersPage と並存する（Step 5d まで）。
 * 担当者は ContactsPage で別管理、複数支店対応や詳細編集は将来の CompanyDetailPage で。
 * 本ページは一覧 + 基本属性 + billing/delivery 1 件ずつの住所を管理する最小構成。
 */

import { useEffect, useState, FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

const PHONE_RE = /^(\+?\d{10,15}|0\d{9,10})$/;
const validatePhoneClient = (raw: string): string | null => {
  if (!raw) return null;
  const cleaned = raw.replace(/[\s\-()]/g, "");
  return PHONE_RE.test(cleaned) ? null : "電話番号の形式が正しくありません（例: 03-1234-5678）";
};

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

type AddressFormState = {
  address_type: "billing" | "delivery";
  branch_name: string;
  name: string;
  email: string;
  telephone: string;
  tax_id: string;
  address_line_1: string;
  address_line_2: string;
  city: string;
  state: string;
  zip: string;
  country_code: string;
};

const emptyBilling: AddressFormState = {
  address_type: "billing",
  branch_name: "", name: "", email: "", telephone: "", tax_id: "",
  address_line_1: "", address_line_2: "",
  city: "", state: "", zip: "", country_code: "",
};
const emptyDelivery: AddressFormState = { ...emptyBilling, address_type: "delivery" };

type FormState = {
  company_code: string;
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
  billing: AddressFormState;
  delivery: AddressFormState;
  sales_channels: string;
};

const emptyForm: FormState = {
  company_code: "",
  name: "",
  name_en: "",
  industry: "",
  website: "",
  trust_level: "",
  priority_focus: "",
  per_order_amount: "",
  monthly_frequency: "",
  monthly_forecast: "",
  billing_display_name: "",
  payment_recipient_name: "",
  fedex_account: "",
  shipping_note: "",
  status: "active",
  notes: "",
  billing: { ...emptyBilling },
  delivery: { ...emptyDelivery },
  sales_channels: "",
};

type Tab = "basic" | "billing" | "delivery";

const companyDisplayName = (c: Company): string => {
  return c.billing_display_name || c.name || c.company_code || "-";
};

const defaultAddress = (c: Company, t: "billing" | "delivery"): CompanyAddress | undefined => {
  const list = c.addresses.filter((a) => a.address_type === t);
  return list.find((a) => a.is_default) || list[0];
};

const addressDisplay = (a: CompanyAddress | undefined): string => {
  if (!a) return "-";
  return a.email || a.telephone || a.city || "-";
};

export default function CompaniesPage() {
  const { hasPermission } = usePermissions();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [activeTab, setActiveTab] = useState<Tab>("basic");
  const [error, setError] = useState("");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Company | null>(null);
  // billing/delivery タブを触ったかどうか。編集時に触っていない場合 payload から
  // addresses を omit することで、本ページ非対応の multi_branch 住所を保護する
  // （backend の _replace_addresses は配列受取時に DELETE+INSERT で全置換するため）
  const [addressesDirty, setAddressesDirty] = useState(false);

  const loadCompanies = async () => {
    try {
      // per_page=100 で全件を一画面に表示（highlife-jpn: 49 社、将来の増加余地あり）
      const parts: string[] = ["per_page=100"];
      if (search) parts.push(`search=${encodeURIComponent(search)}`);
      const data = await api.get<Company[]>(`/companies?${parts.join("&")}`);
      setCompanies(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadCompanies(); }, [search]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const phoneErr = validatePhoneClient(form.billing.telephone);
    if (phoneErr) {
      setPhoneError(phoneErr);
      setActiveTab("billing");
      return;
    }
    setPhoneError(null);

    const toNull = (v: string) => (v ? v : null);
    const addressHasAnyValue = (a: AddressFormState) =>
      a.branch_name || a.name || a.email || a.telephone || a.tax_id ||
      a.address_line_1 || a.address_line_2 ||
      a.city || a.state || a.zip || a.country_code;

    const addresses: Record<string, unknown>[] = [];
    if (addressHasAnyValue(form.billing)) {
      addresses.push({
        address_type: "billing",
        branch_name: toNull(form.billing.branch_name),
        name: toNull(form.billing.name),
        email: toNull(form.billing.email),
        telephone: toNull(form.billing.telephone),
        tax_id: toNull(form.billing.tax_id),
        address_line_1: toNull(form.billing.address_line_1),
        address_line_2: toNull(form.billing.address_line_2),
        city: toNull(form.billing.city),
        state: toNull(form.billing.state),
        zip: toNull(form.billing.zip),
        country_code: toNull(form.billing.country_code),
        is_default: true,
      });
    }
    if (addressHasAnyValue(form.delivery)) {
      addresses.push({
        address_type: "delivery",
        branch_name: toNull(form.delivery.branch_name),
        name: toNull(form.delivery.name),
        email: toNull(form.delivery.email),
        telephone: toNull(form.delivery.telephone),
        tax_id: toNull(form.delivery.tax_id),
        address_line_1: toNull(form.delivery.address_line_1),
        address_line_2: toNull(form.delivery.address_line_2),
        city: toNull(form.delivery.city),
        state: toNull(form.delivery.state),
        zip: toNull(form.delivery.zip),
        country_code: toNull(form.delivery.country_code),
        is_default: true,
      });
    }

    const salesChannels = form.sales_channels
      .split(/[,、，]/)
      .map((s) => s.trim())
      .filter(Boolean);

    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      name_en: toNull(form.name_en),
      industry: toNull(form.industry),
      website: toNull(form.website),
      trust_level: form.trust_level ? parseInt(form.trust_level, 10) : null,
      priority_focus: toNull(form.priority_focus),
      per_order_amount: form.per_order_amount || null,
      monthly_frequency: form.monthly_frequency ? parseInt(form.monthly_frequency, 10) : null,
      monthly_forecast: form.monthly_forecast || null,
      billing_display_name: toNull(form.billing_display_name),
      payment_recipient_name: toNull(form.payment_recipient_name),
      fedex_account: toNull(form.fedex_account),
      shipping_note: toNull(form.shipping_note),
      status: form.status || "active",
      notes: toNull(form.notes),
      sales_channels: salesChannels,
    };
    // 新規作成時は addresses を常に送る。編集時は billing/delivery タブを
    // 実際に触った時のみ送る（multi_branch で管理されている住所の誤削除を防ぐ）
    if (!editId || addressesDirty) {
      payload.addresses = addresses;
    }
    if (!editId && form.company_code.trim()) {
      payload.company_code = form.company_code.trim();
    }

    if (submitting) return;
    setSubmitting(true);
    try {
      if (editId) {
        await api.patch(`/companies/${editId}`, payload);
      } else {
        await api.post("/companies", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      setActiveTab("basic");
      setAddressesDirty(false);
      loadCompanies();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = (c: Company) => {
    const b = defaultAddress(c, "billing");
    const d = defaultAddress(c, "delivery");
    const mk = (a: CompanyAddress | undefined, def: AddressFormState): AddressFormState =>
      a ? {
        address_type: a.address_type,
        branch_name: a.branch_name || "",
        name: a.name || "", email: a.email || "", telephone: a.telephone || "",
        tax_id: a.tax_id || "",
        address_line_1: a.address_line_1 || "", address_line_2: a.address_line_2 || "",
        city: a.city || "", state: a.state || "", zip: a.zip || "",
        country_code: a.country_code || "",
      } : def;

    setEditId(c.id);
    setForm({
      company_code: c.company_code,
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
      billing: mk(b, { ...emptyBilling }),
      delivery: mk(d, { ...emptyDelivery }),
      sales_channels: c.sales_channels.join(", "),
    });
    setPhoneError(null);
    setActiveTab("basic");
    setAddressesDirty(false); // 編集開始時は clean、タブで編集したら dirty に
    setShowForm(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.delete(`/companies/${deleteTarget.id}`);
      setDeleteTarget(null);
      loadCompanies();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
      setDeleteTarget(null);
    }
  };

  // PR #145 Q2: pending_dedup_review の件数を一覧サマリで提示し、解消フローへの導線を強める
  const pendingDedupCount = companies.filter((c) => c.status === "pending_dedup_review").length;

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>
          会社管理（新 B2B モデル）
          {pendingDedupCount > 0 && (
            <span className="dedup-summary" title="status が pending_dedup_review の会社の数">
              重複確認待ち: {pendingDedupCount} 件
            </span>
          )}
        </h1>
        <div className="page-header-actions">
          <input
            type="text"
            placeholder="会社名・コードで検索..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search-input"
          />
          {hasPermission("customers.create") && (
            <button
              className="btn-primary"
              onClick={() => {
                setEditId(null);
                setForm(emptyForm);
                setActiveTab("basic");
                setPhoneError(null);
                setAddressesDirty(false);
                setShowForm(true);
              }}
            >
              + 新規会社
            </button>
          )}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <p>読み込み中...</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>会社コード</th>
              <th>会社名</th>
              <th>業界</th>
              <th>ステータス</th>
              <th>請求先</th>
              <th>配送先</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {companies.length === 0 ? (
              <tr><td colSpan={7} style={{ textAlign: "center", padding: "1rem" }}>会社が登録されていません</td></tr>
            ) : (
              companies.map((c) => (
                <tr
                  key={c.id}
                  className={c.status === "pending_dedup_review" ? "row-pending-dedup" : ""}
                  title={c.status === "pending_dedup_review" ? "重複確認待ち。詳細ページから解消できます" : ""}
                >
                  <td>{c.company_code}</td>
                  <td>
                    {/* 詳細ページへ: multi_branch 住所編集 / 担当者タブ / 販売チャネル */}
                    <Link to={`/companies/${c.id}`}>{companyDisplayName(c)}</Link>
                  </td>
                  <td>{c.industry || "-"}</td>
                  <td><span className={`status-badge status-${c.status}`}>{c.status}</span></td>
                  <td>{addressDisplay(defaultAddress(c, "billing"))}</td>
                  <td>{addressDisplay(defaultAddress(c, "delivery"))}</td>
                  <td>
                    <Link to={`/companies/${c.id}`} className="btn-sm">詳細</Link>
                    {hasPermission("customers.update") && (
                      <button className="btn-sm" onClick={() => handleEdit(c)}>基本編集</button>
                    )}
                    {hasPermission("customers.delete") && (
                      <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(c)}>削除</button>
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
            <h2>{editId ? "会社編集" : "新規会社登録"}</h2>

            <div className="tabs">
              <button className={`tab ${activeTab === "basic" ? "active" : ""}`} onClick={() => setActiveTab("basic")}>基本情報</button>
              <button className={`tab ${activeTab === "billing" ? "active" : ""}`} onClick={() => setActiveTab("billing")}>請求先</button>
              <button className={`tab ${activeTab === "delivery" ? "active" : ""}`} onClick={() => setActiveTab("delivery")}>配送先</button>
            </div>

            <form onSubmit={handleSubmit} className="form-grid">
              {activeTab === "basic" && (
                <>
                  {!editId && (
                    <div className="form-row">
                      <label>会社コード（CO-00001、未指定で自動採番）</label>
                      <input value={form.company_code} onChange={(e) => setForm({ ...form, company_code: e.target.value })} />
                    </div>
                  )}
                  <div className="form-row">
                    <label>会社名 *</label>
                    <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>英語名</label>
                    <input value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>業界</label>
                    <input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>Webサイト</label>
                    <input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>信頼度（1-5）</label>
                    <input type="number" min="1" max="5" value={form.trust_level} onChange={(e) => setForm({ ...form, trust_level: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>重視ポイント</label>
                    <input value={form.priority_focus} onChange={(e) => setForm({ ...form, priority_focus: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>1回発注額</label>
                    <input value={form.per_order_amount} onChange={(e) => setForm({ ...form, per_order_amount: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>月間頻度</label>
                    <input type="number" min="0" value={form.monthly_frequency} onChange={(e) => setForm({ ...form, monthly_frequency: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>月間売上見込額</label>
                    <input value={form.monthly_forecast} onChange={(e) => setForm({ ...form, monthly_forecast: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>請求書表示名</label>
                    <input value={form.billing_display_name} onChange={(e) => setForm({ ...form, billing_display_name: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>支払い名義</label>
                    <input value={form.payment_recipient_name} onChange={(e) => setForm({ ...form, payment_recipient_name: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>FedEx ID</label>
                    <input value={form.fedex_account} onChange={(e) => setForm({ ...form, fedex_account: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>発送時メモ</label>
                    <textarea value={form.shipping_note} onChange={(e) => setForm({ ...form, shipping_note: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>販売チャネル（カンマ区切り）</label>
                    <input value={form.sales_channels} onChange={(e) => setForm({ ...form, sales_channels: e.target.value })} />
                  </div>
                  <div className="form-row">
                    <label>ステータス</label>
                    <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                      <option value="active">active</option>
                      <option value="inactive">inactive</option>
                      <option value="archived">archived</option>
                      <option value="pending_dedup_review">pending_dedup_review</option>
                    </select>
                  </div>
                  <div className="form-row">
                    <label>メモ</label>
                    <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                  </div>
                </>
              )}

              {(activeTab === "billing" || activeTab === "delivery") && (() => {
                const key = activeTab;
                const addr = form[key];
                const setAddr = (patch: Partial<AddressFormState>) => {
                  // 住所タブを触った瞬間に dirty フラグを立てて PATCH に含める
                  setAddressesDirty(true);
                  setForm({ ...form, [key]: { ...addr, ...patch } });
                };
                return (
                  <>
                    <div className="form-row">
                      <label>支店名（複数拠点がある場合）</label>
                      <input value={addr.branch_name} onChange={(e) => setAddr({ branch_name: e.target.value })} />
                    </div>
                    <div className="form-row"><label>担当者名</label><input value={addr.name} onChange={(e) => setAddr({ name: e.target.value })} /></div>
                    <div className="form-row"><label>メール</label><input type="email" value={addr.email} onChange={(e) => setAddr({ email: e.target.value })} /></div>
                    <div className="form-row">
                      <label>電話</label>
                      <input value={addr.telephone} onChange={(e) => setAddr({ telephone: e.target.value })} />
                      {key === "billing" && phoneError && <span className="field-error">{phoneError}</span>}
                    </div>
                    <div className="form-row"><label>税番号</label><input value={addr.tax_id} onChange={(e) => setAddr({ tax_id: e.target.value })} /></div>
                    <div className="form-row"><label>住所1</label><input value={addr.address_line_1} onChange={(e) => setAddr({ address_line_1: e.target.value })} /></div>
                    <div className="form-row"><label>住所2</label><input value={addr.address_line_2} onChange={(e) => setAddr({ address_line_2: e.target.value })} /></div>
                    <div className="form-row"><label>市</label><input value={addr.city} onChange={(e) => setAddr({ city: e.target.value })} /></div>
                    <div className="form-row"><label>州/県</label><input value={addr.state} onChange={(e) => setAddr({ state: e.target.value })} /></div>
                    <div className="form-row"><label>郵便番号</label><input value={addr.zip} onChange={(e) => setAddr({ zip: e.target.value })} /></div>
                    <div className="form-row"><label>国コード（ISO 2文字）</label><input value={addr.country_code} onChange={(e) => setAddr({ country_code: e.target.value })} maxLength={2} /></div>
                  </>
                );
              })()}

              <div className="form-actions">
                <button type="button" onClick={() => setShowForm(false)} disabled={submitting}>キャンセル</button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? "保存中..." : editId ? "更新" : "登録"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmModal
        open={deleteTarget !== null}
        title="会社削除の確認"
        message={
          deleteTarget
            ? `「${companyDisplayName(deleteTarget)}」(${deleteTarget.company_code}) を削除しますか？ 関連する商談・注文・見積・請求書・担当者がある場合は削除できません。`
            : ""
        }
        confirmLabel="削除"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

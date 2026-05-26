/**
 * 会社詳細ページの型定義・定数・ヘルパー関数。
 */

export const PHONE_RE = /^(\+?\d{10,15}|0\d{9,10})$/;

export interface CompanyAddress {
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

export interface Company {
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

export interface Contact {
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

export type Tab = "basic" | "addresses" | "contacts" | "channels";

export type AddressFormState = {
  /** null = 新規、数値 = 既存更新 */
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

export type BasicFormState = {
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

export const emptyAddress = (type: "billing" | "delivery"): AddressFormState => ({
  id: null,
  address_type: type,
  branch_name: "", name: "", email: "", telephone: "", tax_id: "",
  address_line_1: "", address_line_2: "", address_line_3: "",
  city: "", state: "", zip: "", country_code: "",
  is_default: false,
});

export const addressFromApi = (a: CompanyAddress): AddressFormState => ({
  id: a.id,
  address_type: a.address_type,
  branch_name: a.branch_name || "",
  name: a.name || "", email: a.email || "", telephone: a.telephone || "",
  tax_id: a.tax_id || "",
  address_line_1: a.address_line_1 || "", address_line_2: a.address_line_2 || "",
  address_line_3: a.address_line_3 || "",
  city: a.city || "", state: a.state || "", zip: a.zip || "",
  country_code: a.country_code || "",
  is_default: a.is_default,
});

export const addressDisplay = (a: CompanyAddress): string => {
  const parts = [
    a.branch_name, a.name, a.address_line_1, a.city, a.state, a.zip, a.country_code,
  ].filter(Boolean);
  return parts.join(", ") || "-";
};

export const typeLabel = (tFn: (key: string) => string, type: "billing" | "delivery") =>
  type === "billing" ? tFn("companies.billing") : tFn("companies.delivery");

export const basicFromApi = (c: Company): BasicFormState => ({
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

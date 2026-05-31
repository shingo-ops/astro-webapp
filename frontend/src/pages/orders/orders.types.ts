/**
 * 受注管理ページの型定義・定数。
 */

export interface OrderListItem {
  id: number;
  company_id: number;
  contact_id: number | null;
  deal_id: number | null;
  order_number: string;
  total_amount: number | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  company_name: string | null;
  contact_display_name: string | null;
}

export interface CompanyMini {
  id: number;
  company_code: string;
  name: string;
}

export interface GroupCountsResponse {
  counts: Record<string, number>;
  total: number;
}

/**
 * 受注ステータス 6 値（migration 090 で旧値から改名）。
 */
export const STATUSES = [
  "awaiting_payment",
  "sourcing",
  "awaiting_shipping",
  "completed",
  "trouble",
  "cancelled",
] as const;

export const emptyForm = {
  deal_id: "",
  order_number: "",
  total_amount: "",
  status: "awaiting_payment",
  notes: "",
};

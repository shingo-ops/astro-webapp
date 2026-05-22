/**
 * PurchaseDetailPanel — ADR-021 Phase 4 / Sprint 4: 仕入情報フォーム。
 *
 * 単一の受注に紐づく order_purchase_details を取得・編集するモーダル。
 * 既存仕入情報があれば PATCH、なければ POST で新規登録する。
 *
 * カテゴリ別セクション:
 *   - 仕入担当・取引: purchase_staff / purchase_date / transaction_no
 *   - 仕入元: supplier_name / supplier_url
 *   - 金額・数量: purchase_amount / purchase_quantity / purchase_total / purchase_shipping
 *   - 配送: carrier_name / waybill_no
 *   - メモ: purchase_note
 *   - ステータス: purchase_status (select: 確認中 / 確定済み)
 *
 * 「確定」ボタンは `PATCH /orders/{id}/purchase/status` を呼び出し、
 * 業務頻出操作のショートカットとして用意する（既存仕入情報がある場合のみ活性化）。
 *
 * 親 (`OrdersPage`) は `orderId` を渡すだけ。`onClose` / `onSaved` で
 * 一覧側の再取得を引き起こす。
 */

import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../lib/api";

export interface PurchaseDetailDto {
  id: number;
  order_id: number;
  tenant_id: number;
  // 仕入担当・取引
  purchase_staff: string | null;
  purchase_date: string | null;
  transaction_no: string | null;
  // 仕入元
  supplier_name: string | null;
  supplier_url: string | null;
  // 金額・数量
  purchase_amount: number | null;
  purchase_quantity: number | null;
  purchase_total: number | null;
  purchase_shipping: number | null;
  // 配送
  carrier_name: string | null;
  waybill_no: string | null;
  // メモ
  purchase_note: string | null;
  // ステータス
  purchase_status: string | null;
  // 導出（バックエンドから返る）
  total_with_shipping: number | null;
  created_at: string;
  updated_at: string;
}

interface Props {
  orderId: number;
  orderNumber: string;
  onClose: () => void;
  onSaved?: (purchase: PurchaseDetailDto) => void;
}

const STATUS_OPTION_KEYS: { value: string; labelKey: string }[] = [
  { value: "", labelKey: "purchase.status_pending" },
  { value: "confirmed", labelKey: "purchase.status_confirmed" },
];

// 文字列フィールドのキー定義
const TEXT_FIELDS = {
  staffTx: [
    { key: "purchase_staff", labelKey: "purchase.purchaseStaff" },
    { key: "transaction_no", labelKey: "purchase.transactionNo" },
  ],
  supplier: [
    { key: "supplier_name", labelKey: "purchase.supplierName" },
    { key: "supplier_url", labelKey: "purchase.supplierUrl" },
  ],
  shipping: [
    { key: "carrier_name", labelKey: "purchase.carrierName" },
    { key: "waybill_no", labelKey: "purchase.waybillNo" },
  ],
} as const;

const NUMBER_FIELDS = {
  amounts: [
    { key: "purchase_amount", labelKey: "purchase.purchaseAmount", step: "0.01" },
    { key: "purchase_quantity", labelKey: "purchase.purchaseQuantity", step: "1" },
    { key: "purchase_total", labelKey: "purchase.purchaseTotal", step: "0.01" },
    { key: "purchase_shipping", labelKey: "purchase.purchaseShipping", step: "0.01" },
  ],
} as const;

type TextKey =
  | (typeof TEXT_FIELDS.staffTx)[number]["key"]
  | (typeof TEXT_FIELDS.supplier)[number]["key"]
  | (typeof TEXT_FIELDS.shipping)[number]["key"]
  | "purchase_date"
  | "purchase_note"
  | "purchase_status";

type NumberKey = (typeof NUMBER_FIELDS.amounts)[number]["key"];

type FormState = Record<TextKey, string> & Record<NumberKey, string>;

const ALL_TEXT_KEYS: TextKey[] = [
  ...TEXT_FIELDS.staffTx.map((f) => f.key),
  ...TEXT_FIELDS.supplier.map((f) => f.key),
  ...TEXT_FIELDS.shipping.map((f) => f.key),
  "purchase_date",
  "purchase_note",
  "purchase_status",
] as TextKey[];

const ALL_NUMBER_KEYS: NumberKey[] = [
  ...NUMBER_FIELDS.amounts.map((f) => f.key),
] as NumberKey[];

const buildEmptyForm = (): FormState => {
  const out: Record<string, string> = {};
  for (const k of ALL_TEXT_KEYS) out[k] = "";
  for (const k of ALL_NUMBER_KEYS) out[k] = "";
  return out as FormState;
};

const dtoToForm = (data: PurchaseDetailDto): FormState => {
  const out: Record<string, string> = {};
  for (const k of ALL_TEXT_KEYS) {
    const v = (data as unknown as Record<string, unknown>)[k];
    out[k] = v === null || v === undefined ? "" : String(v);
  }
  for (const k of ALL_NUMBER_KEYS) {
    const v = (data as unknown as Record<string, unknown>)[k];
    // 0 は 0 と表示する（金額・数量 0 を空欄表示すると誤認しやすい）
    out[k] = v === null || v === undefined ? "" : String(v);
  }
  return out as FormState;
};

export default function PurchaseDetailPanel({
  orderId,
  orderNumber,
  onClose,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const [existing, setExisting] = useState<PurchaseDetailDto | null>(null);
  const [form, setForm] = useState<FormState>(buildEmptyForm());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await api.get<PurchaseDetailDto>(
          `/orders/${orderId}/purchase`,
        );
        if (cancelled) return;
        setExisting(data);
        setForm(dtoToForm(data));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          if (!cancelled) {
            setExisting(null);
            setForm(buildEmptyForm());
          }
        } else {
          if (!cancelled) {
            setError(
              e instanceof Error ? e.message : t("purchase.fetchError"),
            );
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  const setField = (key: TextKey | NumberKey, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const buildPayload = (): Record<string, unknown> => {
    const payload: Record<string, unknown> = {};
    for (const k of ALL_TEXT_KEYS) {
      const raw = form[k].trim();
      payload[k] = raw === "" ? null : raw;
    }
    for (const k of ALL_NUMBER_KEYS) {
      const raw = form[k].trim();
      if (raw === "") {
        payload[k] = null;
      } else {
        const n = Number(raw);
        payload[k] = Number.isFinite(n) ? n : null;
      }
    }
    return payload;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const payload = buildPayload();
      let saved: PurchaseDetailDto;
      if (existing) {
        saved = await api.patch<PurchaseDetailDto>(
          `/orders/${orderId}/purchase`,
          payload,
        );
      } else {
        saved = await api.post<PurchaseDetailDto>(
          `/orders/${orderId}/purchase`,
          payload,
        );
      }
      onSaved?.(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSaving(false);
    }
  };

  /**
   * 確定ショートカット。`PATCH /orders/{id}/purchase/status` を呼び出して
   * `purchase_status='confirmed'` に切り替える。
   * 既存仕入情報がある場合のみ活性化する（404 防止）。
   */
  const handleConfirm = async () => {
    setError("");
    setConfirming(true);
    try {
      const saved = await api.patch<PurchaseDetailDto>(
        `/orders/${orderId}/purchase/status`,
        {},
      );
      onSaved?.(saved);
      // モーダル内表示も同期させる
      setExisting(saved);
      setForm((prev) => ({ ...prev, purchase_status: saved.purchase_status ?? "" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("purchase.confirmError"));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 880, maxHeight: "90vh", overflowY: "auto" }}
        role="dialog"
        aria-label={t("purchase.modalAriaLabel")}
      >
        <h3>{t("purchase.sectionStaffTx")} — {orderNumber}</h3>
        {loading ? (
          <div className="loading">{t("common.loading")}</div>
        ) : (
          <form onSubmit={handleSubmit}>
            {error && <div className="error-message">{error}</div>}

            {/* セクション: 仕入担当・取引 */}
            <fieldset>
              <legend>{t("purchase.sectionStaffTx")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "0.5rem 1rem",
                }}
              >
                {TEXT_FIELDS.staffTx.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="text"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`pur-input-${f.key}`}
                    />
                  </div>
                ))}
                <div className="form-group">
                  <label>{t("purchase.purchaseDate")}</label>
                  <input
                    type="date"
                    value={form.purchase_date}
                    onChange={(ev) => setField("purchase_date", ev.target.value)}
                    data-testid="pur-input-purchase_date"
                  />
                </div>
              </div>
            </fieldset>

            {/* セクション: 仕入元 */}
            <fieldset>
              <legend>{t("purchase.sectionSupplier")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "0.5rem 1rem",
                }}
              >
                {TEXT_FIELDS.supplier.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type={f.key === "supplier_url" ? "url" : "text"}
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`pur-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: 金額・数量 */}
            <fieldset>
              <legend>{t("purchase.sectionAmounts")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "0.5rem 1rem",
                }}
              >
                {NUMBER_FIELDS.amounts.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="number"
                      min="0"
                      step={f.step}
                      inputMode="decimal"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`pur-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: 配送 */}
            <fieldset>
              <legend>{t("purchase.sectionShipping")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "0.5rem 1rem",
                }}
              >
                {TEXT_FIELDS.shipping.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="text"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`pur-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: ステータス */}
            <div
              className="form-group"
              style={{
                display: "grid",
                gridTemplateColumns: "1fr",
                gap: "0.5rem",
              }}
            >
              <label>{t("common.status")}</label>
              <select
                value={form.purchase_status}
                onChange={(ev) => setField("purchase_status", ev.target.value)}
                data-testid="pur-input-purchase_status"
              >
                {STATUS_OPTION_KEYS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </option>
                ))}
              </select>
            </div>

            {/* メモ */}
            <div className="form-group">
              <label>{t("purchase.purchaseNote")}</label>
              <textarea
                value={form.purchase_note}
                onChange={(ev) => setField("purchase_note", ev.target.value)}
                data-testid="pur-input-purchase_note"
              />
            </div>

            <div
              className="form-actions"
              style={{
                marginTop: "1rem",
                display: "flex",
                justifyContent: "space-between",
                gap: "0.5rem",
                flexWrap: "wrap",
              }}
            >
              <button
                type="button"
                className="btn-secondary"
                onClick={handleConfirm}
                disabled={!existing || confirming}
                data-testid="pur-confirm"
                title={
                  existing
                    ? t("purchase.confirmTitle")
                    : t("purchase.confirmTitleDisabled")
                }
              >
                {confirming ? t("purchase.confirming") : t("purchase.confirm")}
              </button>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={onClose}
                  disabled={saving}
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={saving}
                  data-testid="pur-save"
                >
                  {saving ? t("common.saving") : existing ? t("common.update") : t("common.register")}
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

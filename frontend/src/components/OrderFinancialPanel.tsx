/**
 * OrderFinancialPanel — ADR-021 Phase 2 / Sprint 2: 売上情報フォーム。
 *
 * 単一の受注に紐づく order_financials を取得・編集するモーダル。
 * 既存売上情報があれば PATCH、なければ POST で新規登録する。
 *
 * 親 (`OrdersPage`) は `orderId` を渡すだけ。`onClose` / `onSaved` で
 * 一覧側の再取得を引き起こす。
 */

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../lib/api";

export interface OrderFinancialDto {
  id: number;
  order_id: number;
  tenant_id: number;
  revenue_amount: number;
  purchase_cost: number;
  purchase_shipping: number;
  paypal_fee: number;
  wise_fee: number;
  exchange_fee: number;
  outsource_fee: number;
  packing_fee: number;
  ad_cost: number;
  return_fee: number;
  refund_amount: number;
  commission_base_amount: number;
  tax_refund: number;
  notes: string | null;
  cost_total: number;
  gross_profit: number;
  gross_profit_rate: number | null;
  operating_profit_with_tax_refund: number;
}

interface Props {
  orderId: number;
  orderNumber: string;
  onClose: () => void;
  onSaved?: (financial: OrderFinancialDto) => void;
}

// 入力対象カラムをラベルキー付きで定義（OrderFlow Manager 順）
const INPUT_FIELDS: { key: keyof OrderFinancialDto; labelKey: string }[] = [
  { key: "revenue_amount", labelKey: "financial.revenue_amount" },
  { key: "purchase_cost", labelKey: "financial.purchase_cost" },
  { key: "purchase_shipping", labelKey: "financial.purchase_shipping" },
  { key: "paypal_fee", labelKey: "financial.paypal_fee" },
  { key: "wise_fee", labelKey: "financial.wise_fee" },
  { key: "exchange_fee", labelKey: "financial.exchange_fee" },
  { key: "outsource_fee", labelKey: "financial.outsource_fee" },
  { key: "packing_fee", labelKey: "financial.packing_fee" },
  { key: "ad_cost", labelKey: "financial.ad_cost" },
  { key: "return_fee", labelKey: "financial.return_fee" },
  { key: "refund_amount", labelKey: "financial.refund_amount" },
  { key: "commission_base_amount", labelKey: "financial.commission_base_amount" },
  { key: "tax_refund", labelKey: "financial.tax_refund" },
];

type FormState = Record<(typeof INPUT_FIELDS)[number]["key"], string>;

const emptyForm: FormState = INPUT_FIELDS.reduce(
  (acc, f) => ({ ...acc, [f.key]: "" }),
  {} as FormState,
);

const fmtJPY = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return "-";
  return Number(n).toLocaleString("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  });
};

const fmtRate = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return "-";
  return `${(Number(n) * 100).toFixed(1)}%`;
};

export default function OrderFinancialPanel({
  orderId,
  orderNumber,
  onClose,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const [existing, setExisting] = useState<OrderFinancialDto | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await api.get<OrderFinancialDto>(
          `/orders/${orderId}/financial`,
        );
        if (cancelled) return;
        setExisting(data);
        setForm(
          INPUT_FIELDS.reduce((acc, f) => {
            const v = data[f.key];
            // 数値 0 は空欄表示（読みやすさ、spec の UI 要件）
            const display = v === 0 || v === null ? "" : String(v);
            return { ...acc, [f.key]: display };
          }, {} as FormState),
        );
        setNotes(data.notes ?? "");
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          // 新規登録モード
          if (!cancelled) {
            setExisting(null);
            setForm(emptyForm);
            setNotes("");
          }
        } else {
          if (!cancelled) {
            setError(e instanceof Error ? e.message : t("common.fetchError"));
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

  const buildPayload = (): Record<string, number | string | null> => {
    const payload: Record<string, number | string | null> = {};
    for (const f of INPUT_FIELDS) {
      const raw = form[f.key].trim();
      payload[f.key] = raw === "" ? 0 : Number(raw);
    }
    payload.notes = notes.trim() === "" ? null : notes;
    return payload;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const payload = buildPayload();
      let saved: OrderFinancialDto;
      if (existing) {
        saved = await api.patch<OrderFinancialDto>(
          `/orders/${orderId}/financial`,
          payload,
        );
      } else {
        saved = await api.post<OrderFinancialDto>(
          `/orders/${orderId}/financial`,
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

  // プレビュー: 入力中の値で導出列を即時計算（保存前に粗利を見せる）
  const preview = useMemo(() => {
    const num = (s: string) => {
      const n = Number(s);
      return Number.isFinite(n) ? n : 0;
    };
    const revenue = num(form.revenue_amount);
    const cost =
      num(form.purchase_cost) +
      num(form.purchase_shipping) +
      num(form.paypal_fee) +
      num(form.wise_fee) +
      num(form.exchange_fee) +
      num(form.outsource_fee) +
      num(form.packing_fee) +
      num(form.ad_cost) +
      num(form.return_fee) +
      num(form.refund_amount);
    const gross = revenue - cost;
    const rate = revenue === 0 ? null : gross / revenue;
    const op = gross + num(form.tax_refund);
    return { cost, gross, rate, op };
  }, [form]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 720 }}
        role="dialog"
        aria-label={t("financial.revenue_amount")}
      >
        <h3>{t("orders.financial")} — {orderNumber}</h3>
        {loading ? (
          <div className="loading">{t("common.loading")}</div>
        ) : (
          <form onSubmit={handleSubmit}>
            {error && <div className="error-message">{error}</div>}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, 1fr)",
                gap: "0.5rem 1rem",
              }}
            >
              {INPUT_FIELDS.map((f) => (
                <div className="form-group" key={f.key}>
                  <label>{t(f.labelKey)}</label>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    inputMode="numeric"
                    value={form[f.key]}
                    onChange={(ev) =>
                      setForm({ ...form, [f.key]: ev.target.value })
                    }
                    aria-label={t(f.labelKey)}
                    data-testid={`fin-input-${f.key}`}
                  />
                </div>
              ))}
            </div>
            <div className="form-group">
              <label>{t("common.notes")}</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                aria-label={t("financial.notesAriaLabel")}
              />
            </div>
            <div
              className="financial-summary"
              style={{
                marginTop: "0.75rem",
                padding: "0.75rem",
                background: "var(--bg-subtle)",
                borderRadius: 6,
                display: "grid",
                gridTemplateColumns: "repeat(2, 1fr)",
                rowGap: "0.25rem",
                columnGap: "1rem",
              }}
              data-testid="fin-preview"
            >
              <span>{t("financial.costTotal")}</span>
              <span data-testid="fin-cost-total">{fmtJPY(preview.cost)}</span>
              <span>
                <strong>{t("financial.grossProfit")}</strong>
              </span>
              <span data-testid="fin-gross-profit">
                <strong>{fmtJPY(preview.gross)}</strong>
              </span>
              <span>{t("financial.grossProfitRate")}</span>
              <span data-testid="fin-gross-profit-rate">
                {fmtRate(preview.rate)}
              </span>
              <span>{t("financial.operatingProfit")}</span>
              <span data-testid="fin-operating-profit">
                {fmtJPY(preview.op)}
              </span>
            </div>
            <div className="form-actions" style={{ marginTop: "1rem" }}>
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
                data-testid="fin-save"
              >
                {saving ? t("common.saving") : existing ? t("common.update") : t("common.register")}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

/**
 * ShippingDetailPanel — ADR-021 Phase 3 / Sprint 3: 発送情報フォーム。
 *
 * 単一の受注に紐づく order_shipping_details を取得・編集するモーダル。
 * 既存発送情報があれば PATCH、なければ POST で新規登録する。
 *
 * カテゴリ別セクション:
 *   - 受取人: recipient_name / phone / email / tax_number
 *   - 住所: address1〜3 / city / state_code / zip_code / country_code
 *   - 寸法・重量: length_cm / width_cm / height_cm / weight_kg / volume_g / box_count
 *   - 梱包・品目: packing_memo / packing_type / inspection_status /
 *     item_description / item_price_usd / exchange_rate / hs_code / tax_id / fedex_id
 *   - 配送: carrier (select) / ship_method / ship_date / tracking_number / est_shipping_fee
 *
 * 親 (`OrdersPage`) は `orderId` を渡すだけ。`onClose` / `onSaved` で
 * 一覧側の再取得を引き起こす。
 *
 * eLogi CSV ダウンロードボタンは「既存発送情報があれば押せる」状態で出す。
 * 押下時は `/orders/{id}/shipping/elogi-csv` を fetch し Blob としてダウンロードする。
 */

import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../lib/api";
import { auth } from "../lib/firebase";

export interface ShippingDetailDto {
  id: number;
  order_id: number;
  tenant_id: number;
  // 受取人
  recipient_name: string | null;
  phone: string | null;
  email: string | null;
  tax_number: string | null;
  // 住所
  address1: string | null;
  address2: string | null;
  address3: string | null;
  city: string | null;
  state_code: string | null;
  zip_code: string | null;
  country_code: string | null;
  // 寸法・重量
  length_cm: number | null;
  width_cm: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  volume_g: number | null;
  box_count: number | null;
  // 梱包
  packing_memo: string | null;
  packing_type: string | null;
  inspection_status: string | null;
  // 品目
  item_description: string | null;
  item_price_usd: number | null;
  exchange_rate: number | null;
  hs_code: string | null;
  tax_id: string | null;
  fedex_id: string | null;
  // 配送
  carrier: string | null;
  ship_method: string | null;
  ship_date: string | null;
  tracking_number: string | null;
  est_shipping_fee: number | null;
  // ステータス
  label_issued_at: string | null;
  pickup_requested_at: string | null;
  shipped_at: string | null;
  notified_at: string | null;
  // メモ
  ship_memo: string | null;
}

interface Props {
  orderId: number;
  orderNumber: string;
  onClose: () => void;
  onSaved?: (shipping: ShippingDetailDto) => void;
}

const CARRIER_OPTIONS: { value: string; labelKey: string }[] = [
  { value: "", labelKey: "shipping.carrierUnspecified" },
  { value: "elogi", labelKey: "shipping.carrierElogi" },
  { value: "fedex", labelKey: "shipping.carrierFedex" },
  { value: "dhl", labelKey: "shipping.carrierDhl" },
  { value: "yamato", labelKey: "shipping.carrierYamato" },
  { value: "other", labelKey: "shipping.carrierOther" },
];

// 文字列フィールドのキー定義
const TEXT_FIELDS = {
  recipient: [
    { key: "recipient_name", labelKey: "shipping.recipientName" },
    { key: "phone", labelKey: "common.phone" },
    { key: "email", labelKey: "common.email" },
    { key: "tax_number", labelKey: "shipping.taxNumber" },
  ],
  address: [
    { key: "address1", labelKey: "shipping.address1" },
    { key: "address2", labelKey: "shipping.address2" },
    { key: "address3", labelKey: "shipping.address3" },
    { key: "city", labelKey: "shipping.city" },
    { key: "state_code", labelKey: "shipping.stateCode" },
    { key: "zip_code", labelKey: "shipping.zipCode" },
    { key: "country_code", labelKey: "shipping.countryCode" },
  ],
  packingItem: [
    { key: "packing_memo", labelKey: "shipping.packingMemo" },
    { key: "packing_type", labelKey: "shipping.packingType" },
    { key: "inspection_status", labelKey: "shipping.inspectionStatus" },
    { key: "item_description", labelKey: "shipping.itemDescription" },
    { key: "hs_code", labelKey: "shipping.hsCode" },
    { key: "tax_id", labelKey: "shipping.taxId" },
    { key: "fedex_id", labelKey: "shipping.fedexId" },
  ],
  shippingExtras: [
    { key: "ship_method", labelKey: "shipping.shipMethod" },
    { key: "tracking_number", labelKey: "shipping.trackingNumber" },
  ],
} as const;

const NUMBER_FIELDS = {
  dimensions: [
    { key: "length_cm", labelKey: "shipping.lengthCm", step: "0.01" },
    { key: "width_cm", labelKey: "shipping.widthCm", step: "0.01" },
    { key: "height_cm", labelKey: "shipping.heightCm", step: "0.01" },
    { key: "weight_kg", labelKey: "shipping.weightKg", step: "0.001" },
    { key: "volume_g", labelKey: "shipping.volumeG", step: "0.01" },
    { key: "box_count", labelKey: "shipping.boxCount", step: "1" },
  ],
  itemPrice: [
    { key: "item_price_usd", labelKey: "shipping.itemPriceUsd", step: "0.01" },
    { key: "exchange_rate", labelKey: "shipping.exchangeRate", step: "0.000001" },
    { key: "est_shipping_fee", labelKey: "shipping.estShippingFee", step: "0.01" },
  ],
} as const;

type TextKey =
  | (typeof TEXT_FIELDS.recipient)[number]["key"]
  | (typeof TEXT_FIELDS.address)[number]["key"]
  | (typeof TEXT_FIELDS.packingItem)[number]["key"]
  | (typeof TEXT_FIELDS.shippingExtras)[number]["key"]
  | "carrier"
  | "ship_date"
  | "ship_memo";

type NumberKey =
  | (typeof NUMBER_FIELDS.dimensions)[number]["key"]
  | (typeof NUMBER_FIELDS.itemPrice)[number]["key"];

type FormState = Record<TextKey, string> & Record<NumberKey, string>;

const ALL_TEXT_KEYS: TextKey[] = [
  ...TEXT_FIELDS.recipient.map((f) => f.key),
  ...TEXT_FIELDS.address.map((f) => f.key),
  ...TEXT_FIELDS.packingItem.map((f) => f.key),
  ...TEXT_FIELDS.shippingExtras.map((f) => f.key),
  "carrier",
  "ship_date",
  "ship_memo",
] as TextKey[];

const ALL_NUMBER_KEYS: NumberKey[] = [
  ...NUMBER_FIELDS.dimensions.map((f) => f.key),
  ...NUMBER_FIELDS.itemPrice.map((f) => f.key),
] as NumberKey[];

const buildEmptyForm = (): FormState => {
  const out: Record<string, string> = {};
  for (const k of ALL_TEXT_KEYS) out[k] = "";
  for (const k of ALL_NUMBER_KEYS) out[k] = "";
  return out as FormState;
};

const dtoToForm = (data: ShippingDetailDto): FormState => {
  const out: Record<string, string> = {};
  for (const k of ALL_TEXT_KEYS) {
    const v = (data as unknown as Record<string, unknown>)[k];
    out[k] = v === null || v === undefined ? "" : String(v);
  }
  for (const k of ALL_NUMBER_KEYS) {
    const v = (data as unknown as Record<string, unknown>)[k];
    // 0 は 0 と表示する（売上情報パネルとは違い、寸法 0 を空欄表示すると誤認しやすい）
    out[k] = v === null || v === undefined ? "" : String(v);
  }
  return out as FormState;
};

export default function ShippingDetailPanel({
  orderId,
  orderNumber,
  onClose,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const [existing, setExisting] = useState<ShippingDetailDto | null>(null);
  const [form, setForm] = useState<FormState>(buildEmptyForm());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await api.get<ShippingDetailDto>(
          `/orders/${orderId}/shipping`,
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
              e instanceof Error ? e.message : t("common.fetchError"),
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  const setField = (key: TextKey | NumberKey, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const buildPayload = (): Record<string, unknown> => {
    const payload: Record<string, unknown> = {};
    for (const k of ALL_TEXT_KEYS) {
      const raw = form[k].trim();
      // carrier の空文字は API では null（enum 制約のため）
      if (k === "carrier") {
        payload[k] = raw === "" ? null : raw;
      } else if (k === "ship_date") {
        payload[k] = raw === "" ? null : raw;
      } else {
        payload[k] = raw === "" ? null : raw;
      }
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
      let saved: ShippingDetailDto;
      if (existing) {
        saved = await api.patch<ShippingDetailDto>(
          `/orders/${orderId}/shipping`,
          payload,
        );
      } else {
        saved = await api.post<ShippingDetailDto>(
          `/orders/${orderId}/shipping`,
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
   * eLogi CSV ダウンロード。
   *
   * `api.ts` は JSON 専用なので、ここでは fetch を直接使い text/csv を Blob として
   * 受け取り、a タグでダウンロードする（既存パターン: 別 PR で導入済の同様処理に倣う）。
   */
  const handleDownloadCsv = async () => {
    setError("");
    setDownloading(true);
    try {
      const user = auth.currentUser;
      if (!user) throw new Error(t("common.notAuthenticated"));
      const token = await user.getIdToken();
      const res = await fetch(
        `/api/v1/orders/${orderId}/shipping/elogi-csv`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok) {
        throw new Error(t("common.downloadFailed"));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `elogi-${orderNumber}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 'var(--modal-wide-w)', maxHeight: "90vh", overflowY: "auto" }}
        role="dialog"
        aria-label={t("shipping.sectionShipping")}
      >
        <h3>{t("shipping.sectionShipping")} — {orderNumber}</h3>
        {loading ? (
          <div className="loading">{t("common.loading")}</div>
        ) : (
          <form onSubmit={handleSubmit}>
            {error && <div className="error-message">{error}</div>}

            {/* セクション: 受取人 */}
            <fieldset>
              <legend>{t("shipping.sectionRecipient")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "var(--space-2) var(--space-4)",
                }}
              >
                {TEXT_FIELDS.recipient.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type={f.key === "email" ? "email" : "text"}
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`ship-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: 住所 */}
            <fieldset>
              <legend>{t("companies.address")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "var(--space-2) var(--space-4)",
                }}
              >
                {TEXT_FIELDS.address.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="text"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`ship-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: 寸法・重量 */}
            <fieldset>
              <legend>{t("shipping.sectionDimensions")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: "var(--space-2) var(--space-4)",
                }}
              >
                {NUMBER_FIELDS.dimensions.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="number"
                      min="0"
                      step={f.step}
                      inputMode="decimal"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`ship-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: 梱包・品目 */}
            <fieldset>
              <legend>{t("shipping.sectionPackingItem")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "var(--space-2) var(--space-4)",
                }}
              >
                {TEXT_FIELDS.packingItem.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="text"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`ship-input-${f.key}`}
                    />
                  </div>
                ))}
                {NUMBER_FIELDS.itemPrice.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="number"
                      min="0"
                      step={f.step}
                      inputMode="decimal"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`ship-input-${f.key}`}
                    />
                  </div>
                ))}
              </div>
            </fieldset>

            {/* セクション: 配送 */}
            <fieldset>
              <legend>{t("shipping.sectionShipping")}</legend>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "var(--space-2) var(--space-4)",
                }}
              >
                <div className="form-group">
                  <label>{t("shipping.carrier")}</label>
                  <select
                    value={form.carrier}
                    onChange={(ev) => setField("carrier", ev.target.value)}
                    data-testid="ship-input-carrier"
                  >
                    {CARRIER_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {t(opt.labelKey)}
                      </option>
                    ))}
                  </select>
                </div>
                {TEXT_FIELDS.shippingExtras.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label>{t(f.labelKey)}</label>
                    <input
                      type="text"
                      value={form[f.key]}
                      onChange={(ev) => setField(f.key, ev.target.value)}
                      data-testid={`ship-input-${f.key}`}
                    />
                  </div>
                ))}
                <div className="form-group">
                  <label>{t("shipping.shipDate")}</label>
                  <input
                    type="date"
                    value={form.ship_date}
                    onChange={(ev) => setField("ship_date", ev.target.value)}
                    data-testid="ship-input-ship_date"
                  />
                </div>
              </div>
            </fieldset>

            {/* メモ */}
            <div className="form-group">
              <label>{t("shipping.shipMemo")}</label>
              <textarea
                value={form.ship_memo}
                onChange={(ev) => setField("ship_memo", ev.target.value)}
                data-testid="ship-input-ship_memo"
              />
            </div>

            <div
              className="form-actions"
              style={{
                marginTop: "var(--space-4)",
                display: "flex",
                justifyContent: "space-between",
                gap: "var(--space-2)",
                flexWrap: "wrap",
              }}
            >
              <button
                type="button"
                className="btn-secondary"
                onClick={handleDownloadCsv}
                disabled={!existing || downloading}
                data-testid="ship-download-csv"
                title={
                  existing
                    ? t("shipping.downloadCsvTitle")
                    : t("shipping.downloadCsvTitleDisabled")
                }
              >
                {downloading ? t("shipping.downloading") : t("shipping.downloadCsv")}
              </button>
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
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
                  data-testid="ship-save"
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

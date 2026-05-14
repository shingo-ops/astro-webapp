/**
 * 受注管理ページ。
 *
 * 変更履歴:
 *   - Step 5d: 旧 customer_id 経路撤去、CompanyContactSelector に置換
 *   - 2026-05-11: ADR-021 Phase 1 / Sprint 1 — 受注一覧 MVP
 *     検索ボックス（debounce 300ms）/ ソート UI / グループ件数バッジを追加。
 *     ステータス表示ラベルを ADR-021 第 1 節の 6 値に合わせる
 *     （DB enum は据え置き、UI ラベルのみ）。
 *     一覧テーブルは API JOIN 結果（company_name / contact_display_name）を
 *     直接表示し、別ロード（/companies）への依存を切る。
 *   - 2026-05-11: ADR-021 Phase 2 / Sprint 2 — 売上計算 MVP
 *     一覧に「売上 / 粗利 / 粗利率」列を追加し、「売上編集」ボタンから
 *     OrderFinancialPanel を開いて売上情報を CRUD できるようにした。
 *     売上情報は表示中の受注ごとに /orders/{id}/financial を並列取得し、
 *     軽量な map で保持する（受注数が多い場合は将来的に bulk endpoint 化）。
 *   - 2026-05-11: ADR-021 Phase 3 / Sprint 3 — 発送情報 MVP
 *     一覧に「追跡番号」列を追加し、「発送編集」ボタンから ShippingDetailPanel
 *     を開いて発送情報を CRUD + eLogi CSV ダウンロードができるようにした。
 *     発送情報も /orders/{id}/shipping を並列取得して列に反映する
 *     （N+1 課題は spec.md 実装メモ通り Phase 4-5 の bulk endpoint で吸収予定）。
 *   - 2026-05-11: ADR-021 Phase 4 / Sprint 4 — 仕入情報 MVP
 *     一覧に「仕入状況」列（未登録 / 確認中 / 確定済み）を追加し、
 *     「仕入編集」ボタンから PurchaseDetailPanel を開いて仕入情報を CRUD
 *     + 「確定」ショートカットで status を切替できるようにした。
 *     /orders/{id}/purchase を並列取得して列に反映する。
 */

import { useEffect, useMemo, useRef, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import CompanyContactSelector from "../components/CompanyContactSelector";
import OrderFinancialPanel, {
  OrderFinancialDto,
} from "../components/OrderFinancialPanel";
import ShippingDetailPanel, {
  ShippingDetailDto,
} from "../components/ShippingDetailPanel";
import PurchaseDetailPanel, {
  PurchaseDetailDto,
} from "../components/PurchaseDetailPanel";
import CommissionPanel, {
  OrderCommissionsBundleDto,
} from "../components/CommissionPanel";

interface OrderListItem {
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

interface CompanyMini {
  id: number;
  company_code: string;
  name: string;
}

interface GroupCountsResponse {
  counts: Record<string, number>;
  total: number;
}

// ADR-021 第 1 節の正本 6 値。
// 2026-05-13 J1 fix: 互換性のため残していた `confirmed`（確認済）を撤去し
// ADR-021 設計通りの 6 値に揃えた（pending / processing / shipped / delivered /
// returned / cancelled）。旧 confirmed 行は migration 051 で pending に統合される。
const STATUSES = [
  "pending",
  "processing",
  "shipped",
  "delivered",
  "returned",
  "cancelled",
];

const emptyForm = {
  deal_id: "",
  order_number: "",
  total_amount: "",
  status: "pending",
  notes: "",
};

export default function OrdersPage() {
  const { t } = useTranslation();

  const STATUS_LABELS: Record<string, string> = {
    pending: t("orders.status_pending"),
    processing: t("orders.status_processing"),
    shipped: t("orders.status_shipped"),
    delivered: t("orders.status_delivered"),
    returned: t("orders.status_returned"),
    cancelled: t("orders.status_cancelled"),
  };

  const SORT_OPTIONS = [
    { value: "updated_at", label: t("common.updatedAt") },
    { value: "created_at", label: t("common.createdAt") },
    { value: "total_amount", label: t("common.amount") },
    { value: "status", label: t("common.status") },
  ];

  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [groupCounts, setGroupCounts] = useState<GroupCountsResponse | null>(null);
  const [companies, setCompanies] = useState<CompanyMini[]>([]);
  const [statusFilter, setStatusFilter] = useState("");

  // ADR-021 Sprint 1: 検索 / ソート UI 状態
  const [searchInput, setSearchInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [sortBy, setSortBy] = useState("updated_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [contactId, setContactId] = useState<number | null>(null);
  const [selectorError, setSelectorError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<OrderListItem | null>(null);

  // ADR-021 Sprint 2: 売上情報パネルと表示中受注の financial map
  const [financialTarget, setFinancialTarget] = useState<OrderListItem | null>(null);
  const [financials, setFinancials] = useState<Record<number, OrderFinancialDto | null>>({});

  // ADR-021 Sprint 3: 発送情報パネルと表示中受注の shipping map
  const [shippingTarget, setShippingTarget] = useState<OrderListItem | null>(null);
  const [shippings, setShippings] = useState<Record<number, ShippingDetailDto | null>>({});

  // ADR-021 Sprint 4: 仕入情報パネルと表示中受注の purchase map
  const [purchaseTarget, setPurchaseTarget] = useState<OrderListItem | null>(null);
  const [purchases, setPurchases] = useState<Record<number, PurchaseDetailDto | null>>({});

  // ADR-021 Sprint 5: 報酬パネルと表示中受注の commission map (5 ロール合計のキャッシュ)
  const [commissionTarget, setCommissionTarget] = useState<OrderListItem | null>(null);
  const [commissionTotals, setCommissionTotals] = useState<Record<number, number>>({});

  // 検索入力の debounce（300ms）。タイピング毎に API を叩かない。
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setSearchKeyword(searchInput.trim());
    }, 300);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [searchInput]);

  const queryString = useMemo(() => {
    const p = new URLSearchParams();
    if (statusFilter) p.set("status", statusFilter);
    if (searchKeyword) p.set("search", searchKeyword);
    p.set("sort_by", sortBy);
    p.set("sort_order", sortOrder);
    return p.toString();
  }, [statusFilter, searchKeyword, sortBy, sortOrder]);

  const groupCountsQueryString = useMemo(() => {
    // 件数バッジは「ステータスフィルタを除いた」件数を返す（ステータス選択前の全体感）。
    // ただし search とは連動する（spec AC-1.6）。
    const p = new URLSearchParams();
    if (searchKeyword) p.set("search", searchKeyword);
    return p.toString();
  }, [searchKeyword]);

  const loadOrders = async () => {
    try {
      setLoading(true);
      const data = await api.get<OrderListItem[]>(
        `/orders${queryString ? `?${queryString}` : ""}`,
      );
      setOrders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  const loadGroupCounts = async () => {
    try {
      const data = await api.get<GroupCountsResponse>(
        `/orders/group-counts${groupCountsQueryString ? `?${groupCountsQueryString}` : ""}`,
      );
      setGroupCounts(data);
    } catch {
      // バッジは取得失敗してもページ全体を壊さない
      setGroupCounts(null);
    }
  };

  const loadCompanies = async () => {
    try {
      const data = await api.get<CompanyMini[]>("/companies?per_page=100");
      setCompanies(
        data.map((c) => ({ id: c.id, company_code: c.company_code, name: c.name })),
      );
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    loadOrders();
  }, [queryString]);
  useEffect(() => {
    loadGroupCounts();
  }, [groupCountsQueryString]);
  useEffect(() => {
    loadCompanies();
  }, []);

  // ADR-021 Sprint 2: 表示中受注ごとに /orders/{id}/financial を並列取得し
  // 売上 / 粗利 / 粗利率 列を埋める。404 は "未登録 = null" として扱う。
  useEffect(() => {
    if (orders.length === 0) {
      setFinancials({});
      return;
    }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<OrderFinancialDto>(
              `/orders/${o.id}/financial`,
            );
            return [o.id, data] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) {
              return [o.id, null] as const;
            }
            // 取得失敗はバッジを描かないだけで全体は壊さない
            return [o.id, null] as const;
          }
        }),
      );
      if (cancelled) return;
      const map: Record<number, OrderFinancialDto | null> = {};
      for (const [id, data] of results) map[id] = data;
      setFinancials(map);
    };
    fetchAll();
    return () => {
      cancelled = true;
    };
  }, [orders]);

  // ADR-021 Sprint 3: 表示中受注ごとに /orders/{id}/shipping を並列取得し
  // 追跡番号列を埋める。404 は "未登録 = null"。
  useEffect(() => {
    if (orders.length === 0) {
      setShippings({});
      return;
    }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<ShippingDetailDto>(
              `/orders/${o.id}/shipping`,
            );
            return [o.id, data] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) {
              return [o.id, null] as const;
            }
            return [o.id, null] as const;
          }
        }),
      );
      if (cancelled) return;
      const map: Record<number, ShippingDetailDto | null> = {};
      for (const [id, data] of results) map[id] = data;
      setShippings(map);
    };
    fetchAll();
    return () => {
      cancelled = true;
    };
  }, [orders]);

  // ADR-021 Sprint 4: 表示中受注ごとに /orders/{id}/purchase を並列取得し
  // 仕入状況列を埋める。404 は "未登録 = null"。
  useEffect(() => {
    if (orders.length === 0) {
      setPurchases({});
      return;
    }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<PurchaseDetailDto>(
              `/orders/${o.id}/purchase`,
            );
            return [o.id, data] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) {
              return [o.id, null] as const;
            }
            return [o.id, null] as const;
          }
        }),
      );
      if (cancelled) return;
      const map: Record<number, PurchaseDetailDto | null> = {};
      for (const [id, data] of results) map[id] = data;
      setPurchases(map);
    };
    fetchAll();
    return () => {
      cancelled = true;
    };
  }, [orders]);

  // ADR-021 Sprint 5: 表示中受注ごとに /orders/{id}/commissions を並列取得し
  // 「報酬合計」列を埋める。N+1 は Sprint 4 と同じ仕組み（spec.md 通り）。
  useEffect(() => {
    if (orders.length === 0) {
      setCommissionTotals({});
      return;
    }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<OrderCommissionsBundleDto>(
              `/orders/${o.id}/commissions`,
            );
            const total = Object.values(data.commissions).reduce(
              (acc, c) => acc + (c ? Number(c.calculated_amount) || 0 : 0),
              0,
            );
            return [o.id, total] as const;
          } catch {
            return [o.id, 0] as const;
          }
        }),
      );
      if (cancelled) return;
      const map: Record<number, number> = {};
      for (const [id, total] of results) map[id] = total;
      setCommissionTotals(map);
    };
    fetchAll();
    return () => {
      cancelled = true;
    };
  }, [orders]);

  const resetSelector = () => {
    setCompanyId(null);
    setContactId(null);
    setSelectorError("");
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSelectorError("");
    if (!editId && contactId === null) {
      setSelectorError(t("companyContactSelector.contactRequired"));
      return;
    }
    const basePayload = {
      deal_id: form.deal_id ? Number(form.deal_id) : null,
      order_number: form.order_number,
      total_amount: form.total_amount ? Number(form.total_amount) : null,
      status: form.status,
      notes: form.notes || null,
    };
    const payload = editId
      ? basePayload
      : { ...basePayload, company_id: companyId, contact_id: contactId };
    try {
      if (editId) {
        await api.patch(`/orders/${editId}`, payload);
      } else {
        await api.post("/orders", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      resetSelector();
      loadOrders();
      loadGroupCounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    }
  };

  const handleEdit = (o: OrderListItem) => {
    setEditId(o.id);
    setForm({
      deal_id: o.deal_id ? String(o.deal_id) : "",
      order_number: o.order_number,
      total_amount: o.total_amount ? String(o.total_amount) : "",
      status: o.status,
      notes: o.notes || "",
    });
    setCompanyId(o.company_id);
    setContactId(o.contact_id);
    setSelectorError("");
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/orders/${id}`);
      loadOrders();
      loadGroupCounts();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const fmt = (n: number) =>
    n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });

  // 粗利率の小数 1 桁 % 表示（spec UI 要件）
  const fmtRate = (n: number | null | undefined) => {
    if (n === null || n === undefined) return "-";
    return `${(n * 100).toFixed(1)}%`;
  };

  const companyDisplay = (o: OrderListItem) => {
    if (o.company_name) return o.company_name;
    // JOIN 失敗時のフォールバック（FK 切れ等）
    const c = companies.find((c) => c.id === o.company_id);
    return c ? c.name : `#${o.company_id}`;
  };

  const toggleSortOrder = () => {
    setSortOrder((prev) => (prev === "desc" ? "asc" : "desc"));
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("orders.title")}</h2>
        <button
          className="btn-primary"
          onClick={() => {
            setShowForm(true);
            setEditId(null);
            setForm(emptyForm);
            resetSelector();
          }}
        >
          {t("orders.newOrder")}
        </button>
      </div>

      {/* グループ件数バッジ（ADR-021 AC-1.6）。
          search 連動 / status fitler 非連動で全体ステータス分布を見せる。 */}
      <div
        className="orders-group-counts"
        role="group"
        aria-label={t("common.status")}
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "1rem",
        }}
      >
        <button
          type="button"
          className={`badge ${statusFilter === "" ? "badge-active" : ""}`}
          onClick={() => setStatusFilter("")}
          aria-pressed={statusFilter === ""}
          data-testid="group-count-all"
        >
          {t("common.all")} {groupCounts ? `(${groupCounts.total})` : ""}
        </button>
        {STATUSES.map((s) => {
          const count = groupCounts?.counts[s] ?? 0;
          const active = statusFilter === s;
          return (
            <button
              type="button"
              key={s}
              className={`badge badge-${s} ${active ? "badge-active" : ""}`}
              onClick={() => setStatusFilter(active ? "" : s)}
              aria-pressed={active}
              data-testid={`group-count-${s}`}
            >
              {STATUS_LABELS[s]} ({count})
            </button>
          );
        })}
      </div>

      <div
        className="filter-bar"
        style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}
      >
        <input
          type="search"
          aria-label={t("orders.title")}
          placeholder={t("common.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ flex: "1 1 240px", minWidth: 200 }}
          data-testid="orders-search-input"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label={t("common.filter")}
          data-testid="orders-status-filter"
        >
          <option value="">{t("orders.allStatuses")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          aria-label={t("common.filter")}
          data-testid="orders-sort-by"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={toggleSortOrder}
          aria-label={sortOrder === "desc" ? "↓" : "↑"}
          data-testid="orders-sort-order"
        >
          {sortOrder === "desc" ? "↓" : "↑"}
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("orders.editOrder") : t("orders.newOrder")}</h3>
            <form onSubmit={handleSubmit}>
              <CompanyContactSelector
                value={{ companyId, contactId }}
                onChange={({ companyId: c, contactId: ct }) => {
                  setCompanyId(c);
                  setContactId(ct);
                }}
                required={!editId}
                disabled={editId !== null}
                error={selectorError}
                companies={companies}
              />
              {editId && (
                <p
                  style={{
                    fontSize: "0.85rem",
                    color: "var(--text-secondary)",
                    marginTop: -8,
                  }}
                >
                  {t("common.irreversible")}
                </p>
              )}
              <div className="form-group">
                <label>{t("orders.orderNumber")} *</label>
                <input
                  required
                  value={form.order_number}
                  onChange={(e) =>
                    setForm({ ...form, order_number: e.target.value })
                  }
                />
              </div>
              <div className="form-group">
                <label>{t("common.amount")}</label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.total_amount}
                  onChange={(e) =>
                    setForm({ ...form, total_amount: e.target.value })
                  }
                />
              </div>
              <div className="form-group">
                <label>{t("common.status")}</label>
                <select
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value })}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {STATUS_LABELS[s]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>{t("common.notes")}</label>
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                />
              </div>
              <div className="form-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setShowForm(false)}
                >
                  {t("common.cancel")}
                </button>
                <button type="submit" className="btn-primary">
                  {editId ? t("common.update") : t("common.register")}
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
              <th>{t("orders.orderNumber")}</th>
              <th>{t("common.company")}</th>
              <th>{t("common.name")}</th>
              <th>{t("common.amount")}</th>
              <th>{t("orders.financial")}</th>
              <th>{t("financial.grossProfit")}</th>
              <th>{t("financial.grossProfitRate")}</th>
              <th>{t("shipping.trackingNumber")}</th>
              <th>{t("orders.purchase")}</th>
              <th>{t("orders.commission")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.createdAt")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => {
              const fin = financials[o.id] ?? null;
              const ship = shippings[o.id] ?? null;
              const pur = purchases[o.id] ?? null;
              return (
                <tr key={o.id}>
                  <td>{o.order_number}</td>
                  <td>{companyDisplay(o)}</td>
                  <td>{o.contact_display_name ?? "-"}</td>
                  <td>{o.total_amount ? fmt(o.total_amount) : "-"}</td>
                  <td data-testid={`fin-cell-revenue-${o.id}`}>
                    {fin && fin.revenue_amount > 0 ? fmt(fin.revenue_amount) : "-"}
                  </td>
                  <td data-testid={`fin-cell-gross-${o.id}`}>
                    {fin ? fmt(fin.gross_profit) : "-"}
                  </td>
                  <td data-testid={`fin-cell-rate-${o.id}`}>
                    {fin ? fmtRate(fin.gross_profit_rate) : "-"}
                  </td>
                  <td data-testid={`ship-cell-tracking-${o.id}`}>
                    {ship && ship.tracking_number ? ship.tracking_number : "-"}
                  </td>
                  <td data-testid={`pur-cell-status-${o.id}`}>
                    {(() => {
                      if (!pur) {
                        return <span className="badge">{t("common.notSet")}</span>;
                      }
                      if (pur.purchase_status === "confirmed") {
                        return (
                          <span className="badge badge-confirmed">{t("purchase.status_confirmed")}</span>
                        );
                      }
                      return <span className="badge badge-pending">{t("purchase.status_pending")}</span>;
                    })()}
                  </td>
                  <td data-testid={`com-cell-total-${o.id}`}>
                    {commissionTotals[o.id] ? fmt(commissionTotals[o.id]) : "-"}
                  </td>
                  <td>
                    <span className={`badge badge-${o.status}`}>
                      {STATUS_LABELS[o.status] || o.status}
                    </span>
                  </td>
                  <td>{new Date(o.created_at).toLocaleDateString("ja-JP")}</td>
                  <td className="actions">
                    <button className="btn-sm" onClick={() => handleEdit(o)}>
                      {t("common.edit")}
                    </button>
                    <button
                      className="btn-sm"
                      onClick={() => setFinancialTarget(o)}
                      data-testid={`open-financial-${o.id}`}
                    >
                      {t("orders.financial")}
                    </button>
                    <button
                      className="btn-sm"
                      onClick={() => setShippingTarget(o)}
                      data-testid={`open-shipping-${o.id}`}
                    >
                      {t("orders.shipping")}
                    </button>
                    <button
                      className="btn-sm"
                      onClick={() => setPurchaseTarget(o)}
                      data-testid={`open-purchase-${o.id}`}
                    >
                      {t("orders.purchase")}
                    </button>
                    <button
                      className="btn-sm"
                      onClick={() => setCommissionTarget(o)}
                      data-testid={`open-commission-${o.id}`}
                    >
                      {t("orders.commission")}
                    </button>
                    <button
                      className="btn-sm btn-danger"
                      onClick={() => setDeleteTarget(o)}
                    >
                      {t("common.delete")}
                    </button>
                  </td>
                </tr>
              );
            })}
            {orders.length === 0 && (
              <tr>
                <td colSpan={13} className="empty">
                  {t("orders.noOrders")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {financialTarget && (
        <OrderFinancialPanel
          orderId={financialTarget.id}
          orderNumber={financialTarget.order_number}
          onClose={() => setFinancialTarget(null)}
          onSaved={(saved) => {
            setFinancials((prev) => ({ ...prev, [saved.order_id]: saved }));
          }}
        />
      )}

      {shippingTarget && (
        <ShippingDetailPanel
          orderId={shippingTarget.id}
          orderNumber={shippingTarget.order_number}
          onClose={() => setShippingTarget(null)}
          onSaved={(saved) => {
            setShippings((prev) => ({ ...prev, [saved.order_id]: saved }));
          }}
        />
      )}

      {purchaseTarget && (
        <PurchaseDetailPanel
          orderId={purchaseTarget.id}
          orderNumber={purchaseTarget.order_number}
          onClose={() => setPurchaseTarget(null)}
          onSaved={(saved) => {
            setPurchases((prev) => ({ ...prev, [saved.order_id]: saved }));
          }}
        />
      )}

      {commissionTarget && (
        <CommissionPanel
          orderId={commissionTarget.id}
          orderNumber={commissionTarget.order_number}
          onClose={() => setCommissionTarget(null)}
          onSaved={(bundle) => {
            const total = Object.values(bundle.commissions).reduce(
              (acc, c) => acc + (c ? Number(c.calculated_amount) || 0 : 0),
              0,
            );
            setCommissionTotals((prev) => ({
              ...prev,
              [bundle.order_id]: total,
            }));
          }}
        />
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("orders.deleteOrder")}
        message={
          <>
            {t("orders.orderNumber")}: <strong>{deleteTarget?.order_number}</strong>
            <br />
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

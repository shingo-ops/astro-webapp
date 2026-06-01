/**
 * 受注管理ページの状態管理フック。
 * OrdersPage の全 useState / useEffect / useMemo / handler を集約する。
 */

import { useEffect, useMemo, useRef, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../lib/api";
import type {
  OrderListItem, CompanyMini, GroupCountsResponse,
} from "./orders.types";
import { emptyForm } from "./orders.types";
import type {
  OrderFinancialDto,
} from "../../components/OrderFinancialPanel";
import type {
  ShippingDetailDto,
} from "../../components/ShippingDetailPanel";
import type {
  PurchaseDetailDto,
} from "../../components/PurchaseDetailPanel";
import type {
  OrderCommissionsBundleDto,
} from "../../components/CommissionPanel";

/** 金額を日本円フォーマットで表示 */
export const fmt = (n: number) =>
  n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });

/** 粗利率を小数 1 桁 % 表示 */
export const fmtRate = (n: number | null | undefined) => {
  if (n === null || n === undefined) return "-";
  return `${(n * 100).toFixed(1)}%`;
};

export function useOrdersState() {
  const { t } = useTranslation();

  const STATUS_LABELS: Record<string, string> = {
    awaiting_payment: t("orders.status_awaiting_payment"),
    sourcing: t("orders.status_sourcing"),
    awaiting_shipping: t("orders.status_awaiting_shipping"),
    completed: t("orders.status_completed"),
    trouble: t("orders.status_trouble"),
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

  // ADR-021 Sprint 2: 売上情報
  const [financialTarget, setFinancialTarget] = useState<OrderListItem | null>(null);
  const [financials, setFinancials] = useState<Record<number, OrderFinancialDto | null>>({});

  // ADR-021 Sprint 3: 発送情報
  const [shippingTarget, setShippingTarget] = useState<OrderListItem | null>(null);
  const [shippings, setShippings] = useState<Record<number, ShippingDetailDto | null>>({});

  // ADR-021 Sprint 4: 仕入情報
  const [purchaseTarget, setPurchaseTarget] = useState<OrderListItem | null>(null);
  const [purchases, setPurchases] = useState<Record<number, PurchaseDetailDto | null>>({});

  // ADR-021 Sprint 5: 報酬情報
  const [commissionTarget, setCommissionTarget] = useState<OrderListItem | null>(null);
  const [commissionTotals, setCommissionTotals] = useState<Record<number, number>>({});

  // 検索入力の debounce（300ms）
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

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadOrders(); }, [queryString]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadGroupCounts(); }, [groupCountsQueryString]);
  useEffect(() => { loadCompanies(); }, []);

  // ADR-021 Sprint 2: 売上情報を並列取得
  useEffect(() => {
    if (orders.length === 0) { setFinancials({}); return; }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<OrderFinancialDto>(`/orders/${o.id}/financial`);
            return [o.id, data] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) return [o.id, null] as const;
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
    return () => { cancelled = true; };
  }, [orders]);

  // ADR-021 Sprint 3: 発送情報を並列取得
  useEffect(() => {
    if (orders.length === 0) { setShippings({}); return; }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<ShippingDetailDto>(`/orders/${o.id}/shipping`);
            return [o.id, data] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) return [o.id, null] as const;
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
    return () => { cancelled = true; };
  }, [orders]);

  // ADR-021 Sprint 4: 仕入情報を並列取得
  useEffect(() => {
    if (orders.length === 0) { setPurchases({}); return; }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<PurchaseDetailDto>(`/orders/${o.id}/purchase`);
            return [o.id, data] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) return [o.id, null] as const;
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
    return () => { cancelled = true; };
  }, [orders]);

  // ADR-021 Sprint 5: 報酬情報を並列取得
  useEffect(() => {
    if (orders.length === 0) { setCommissionTotals({}); return; }
    let cancelled = false;
    const fetchAll = async () => {
      const results = await Promise.all(
        orders.map(async (o) => {
          try {
            const data = await api.get<OrderCommissionsBundleDto>(`/orders/${o.id}/commissions`);
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
    return () => { cancelled = true; };
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

  const companyDisplay = (o: OrderListItem) => {
    if (o.company_name) return o.company_name;
    const c = companies.find((c) => c.id === o.company_id);
    return c ? c.name : `#${o.company_id}`;
  };

  const toggleSortOrder = () => setSortOrder((prev) => (prev === "desc" ? "asc" : "desc"));

  return {
    orders, groupCounts, companies,
    statusFilter, setStatusFilter,
    searchInput, setSearchInput,
    sortBy, setSortBy,
    sortOrder, toggleSortOrder,
    showForm, setShowForm,
    editId, setEditId,
    form, setForm,
    companyId, setCompanyId,
    contactId, setContactId,
    selectorError,
    error, loading,
    deleteTarget, setDeleteTarget,
    financialTarget, setFinancialTarget,
    financials, setFinancials,
    shippingTarget, setShippingTarget,
    shippings, setShippings,
    purchaseTarget, setPurchaseTarget,
    purchases, setPurchases,
    commissionTarget, setCommissionTarget,
    commissionTotals, setCommissionTotals,
    STATUS_LABELS, SORT_OPTIONS,
    loadOrders, loadGroupCounts,
    handleSubmit, handleEdit, performDelete,
    companyDisplay, resetSelector,
  };
}

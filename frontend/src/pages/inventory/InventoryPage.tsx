/**
 * /inventory — 在庫表（最終ユーザー向けビュー / ADR-093 Phase 2）。
 *
 * public.inventory の status='in_stock' かつ未失効のオファーを「商品×仕入元×状態」の
 * 明細行で表示する読み取り専用画面。各クライアントの営業担当ロール以上（products.view）が
 * 状態・形態・単価・在庫数・仕入元・掲載時間を見て、チェックして見積/請求を作成する起点。
 *
 * - データ源: GET /inventory（products.view 必須、18h 失効は backend がフィルタ）。
 * - 編集/削除は持たない（管理者は /super-admin/inventory-offers で編集削除、商品マスタは /admin/products）。
 * - 横スクロール回避: 関連項目を複合セルに集約（商品=カテゴリ/マーク/名前、仕入元=名前/掲載時間）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { PageLayout } from "../../components/PageLayout";

interface InventoryRow {
  id: number;
  product_id: number;
  product_name: string | null;
  name_en: string | null;
  category: string | null;
  mark: string | null;
  condition: string;
  unit: string | null;
  supplier_id: number;
  supplier_name: string | null;
  unit_price: number;
  quantity: number;
  tcg_type: string | null;
  offered_at: string;
}

interface InventoryListResponse {
  items: InventoryRow[];
  total: number;
  page: number;
  per_page: number;
}

const PER_PAGE = 50;

export default function InventoryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [items, setItems] = useState<InventoryRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchQ, setSearchQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [tcgType, setTcgType] = useState("");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const totalPages = useMemo(
    () => (total === 0 ? 1 : Math.ceil(total / PER_PAGE)),
    [total],
  );

  // TCG 種別ドロップダウン候補（返ってきた items の distinct）
  const tcgTypeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) if (it.tcg_type) set.add(it.tcg_type);
    return Array.from(set).sort();
  }, [items]);

  // 掲載時間を相対表記（例: 3時間前）。1日以上は日付。
  const fmtOfferedAt = useCallback(
    (iso: string): string => {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "-";
      const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
      if (diffMin < 1) return t("inventory.justNow");
      if (diffMin < 60) return t("inventory.minutesAgo", { count: diffMin });
      const diffH = Math.floor(diffMin / 60);
      if (diffH < 24) return t("inventory.hoursAgo", { count: diffH });
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    },
    [t],
  );

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(searchQ), 250);
    return () => clearTimeout(timer);
  }, [searchQ]);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(PER_PAGE));
      params.set("sort", "name");
      params.set("order", order);
      if (debouncedQ.trim()) params.set("q", debouncedQ.trim());
      if (tcgType) params.set("tcg_type", tcgType);
      const d = await api.get<InventoryListResponse>(`/inventory?${params.toString()}`);
      setItems(d.items);
      setTotal(d.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [page, order, debouncedQ, tcgType, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // 選択行を初期明細として見積/請求作成画面へ渡す（condition/unit/supplier も同梱・表示用）
  const goCreate = (path: string) => {
    const selectedProducts = items
      .filter((it) => selectedIds.has(it.id))
      .map((it) => ({
        product_id: it.product_id,
        product_name: it.product_name ?? "",
        unit_price: it.unit_price,
        condition: it.condition,
        unit: it.unit,
        supplier_id: it.supplier_id,
        supplier_name: it.supplier_name,
      }));
    if (selectedProducts.length === 0) return;
    navigate(path, { state: { selectedProducts } });
  };

  const toggleSort = () => {
    setOrder((o) => (o === "asc" ? "desc" : "asc"));
    setPage(1);
  };

  return (
    <PageLayout navKey="nav.inventory" subtitleKey="inventory.view.subtitle">
      {/* 18h 失効の注意（赤字バナー） */}
      <div
        className="error-message"
        role="status"
        data-testid="inventory-expiry-warning"
        style={{ marginBottom: "var(--space-3)" }}
      >
        {t("inventory.expiryWarning")}
      </div>

      {error && (
        <div className="error-message" role="alert" data-testid="inventory-error">
          {error}
        </div>
      )}

      {/* フィルタ行 */}
      <section
        className="inventory-filter"
        style={{
          display: "flex",
          gap: "var(--space-2)",
          flexWrap: "wrap",
          alignItems: "center",
          marginBottom: "var(--space-4)",
        }}
      >
        <input
          type="search"
          placeholder={t("inventory.view.searchPlaceholder")}
          data-testid="inventory-search"
          value={searchQ}
          onChange={(e) => {
            setSearchQ(e.target.value);
            setPage(1);
          }}
          style={{ minWidth: "18rem" }}
        />
        <select
          data-testid="inventory-tcg-filter"
          value={tcgType}
          onChange={(e) => {
            setTcgType(e.target.value);
            setPage(1);
          }}
          aria-label={t("inventory.filter.allTypes")}
        >
          <option value="">{t("inventory.filter.allTypes")}</option>
          {tcgTypeOptions.map((tt) => (
            <option key={tt} value={tt}>
              {tt}
            </option>
          ))}
        </select>
      </section>

      {/* 選択 → 見積/請求作成（発注書PDF は後続 PR で追加） */}
      {selectedIds.size > 0 && (
        <div
          className="selection-action-bar"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3)",
            flexWrap: "wrap",
            margin: "var(--space-2) 0",
            padding: "var(--space-2) var(--space-3)",
            background: "var(--bg-subtle)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <span style={{ fontWeight: "var(--font-weight-semi)" }}>
            {t("products.selectedCount", { count: selectedIds.size })}
          </span>
          <button
            className="btn-primary btn-sm"
            onClick={() => goCreate("/quotes/new")}
            data-testid="create-quote-from-inventory"
          >
            {t("products.createQuote")}
          </button>
          <button
            className="btn-primary btn-sm"
            onClick={() => goCreate("/invoices/new")}
            data-testid="create-invoice-from-inventory"
          >
            {t("products.createInvoice")}
          </button>
          <button className="btn-sm" onClick={() => setSelectedIds(new Set())}>
            {t("common.clear")}
          </button>
        </div>
      )}

      {/* レイアウトシフト防止: loading 中も DOM に残し visibility だけ切替 */}
      <div
        className="loading-indicator"
        data-testid="inventory-loading"
        aria-live="polite"
        aria-hidden={!loading}
        style={{ minHeight: "1.5rem", visibility: loading ? "visible" : "hidden" }}
      >
        {t("common.loading")}
      </div>

      {/* 横スクロール回避: 複合セルで実質 7 列。table-layout:fixed で幅を制御 */}
      <table
        className="data-table"
        data-testid="inventory-table"
        aria-busy={loading}
        style={{ tableLayout: "fixed", width: "100%" }}
      >
        <thead>
          <tr>
            <th
              style={{ width: "var(--col-width-checkbox)", textAlign: "center" }}
              aria-label={t("common.select")}
            ></th>
            <th>
              <button
                type="button"
                onClick={toggleSort}
                data-testid="inventory-sort-name"
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  font: "inherit",
                  fontWeight: "var(--font-weight-semi)",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "var(--space-1)",
                }}
              >
                {t("inventory.col.product")}{" "}
                <span aria-hidden="true" style={{ color: "var(--text-secondary)" }}>
                  {order === "asc" ? t("inventory.sortAsc") : t("inventory.sortDesc")}
                </span>
              </button>
            </th>
            <th style={{ width: "6rem" }}>{t("inventory.col.unit")}</th>
            <th style={{ width: "8rem" }}>{t("inventory.col.condition")}</th>
            <th style={{ width: "7rem", textAlign: "right" }}>{t("inventory.col.unitPrice")}</th>
            <th style={{ width: "5rem", textAlign: "right" }}>{t("inventory.col.quantity")}</th>
            <th style={{ width: "11rem" }}>{t("inventory.col.supplier")}</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={7} data-testid="inventory-empty">
                {t("inventory.noResults")}
              </td>
            </tr>
          ) : (
            items.map((it) => (
              <tr key={it.id} data-testid={`inventory-row-${it.id}`}>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(it.id)}
                    onChange={() => toggleSelect(it.id)}
                    aria-label={it.product_name ?? `#${it.product_id}`}
                    data-testid={`inventory-row-${it.id}-select`}
                  />
                </td>
                {/* 商品（複合）: カテゴリ/マーク バッジ + 商品名(日)/英名 */}
                <td style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  <div style={{ display: "flex", gap: "var(--space-1)", flexWrap: "wrap", marginBottom: "var(--space-1)" }}>
                    {it.category && <span className="badge">{it.category}</span>}
                    {it.mark && <span className="badge badge-muted">{it.mark}</span>}
                  </div>
                  <div style={{ fontWeight: "var(--font-weight-semi)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {it.product_name ?? `#${it.product_id}`}
                  </div>
                  {it.name_en && (
                    <div style={{ fontSize: "var(--font-xs)", color: "var(--text-secondary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {it.name_en}
                    </div>
                  )}
                </td>
                <td>{it.unit ? t(`inventory.unit.${it.unit}`, it.unit) : "-"}</td>
                <td>{t(`inventory.condition.${it.condition}`, it.condition)}</td>
                <td style={{ textAlign: "right" }}>¥{it.unit_price.toLocaleString()}</td>
                <td style={{ textAlign: "right" }}>{it.quantity}</td>
                {/* 仕入元（複合）: 仕入元名 + 掲載時間 */}
                <td style={{ overflow: "hidden" }}>
                  <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {it.supplier_name ?? `#${it.supplier_id}`}
                  </div>
                  <div style={{ fontSize: "var(--font-xs)", color: "var(--text-secondary)" }}>
                    {fmtOfferedAt(it.offered_at)}
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <section
        className="inventory-pagination"
        style={{
          marginTop: "var(--space-4)",
          marginBottom: "var(--space-6)",
          display: "flex",
          gap: "var(--space-2)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <button
          onClick={() => setPage(Math.max(1, page - 1))}
          disabled={page <= 1 || loading}
          data-testid="inventory-prev"
          className="btn-secondary"
        >
          {t("common.previous")}
        </button>
        <span data-testid="inventory-pagination-label">
          {t("inventory.pageOf", { page, total: totalPages, count: total })}
        </span>
        <button
          onClick={() => setPage(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages || loading}
          data-testid="inventory-next"
          className="btn-secondary"
        >
          {t("common.next")}
        </button>
      </section>
    </PageLayout>
  );
}

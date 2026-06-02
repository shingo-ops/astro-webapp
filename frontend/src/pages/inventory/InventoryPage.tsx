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
import { usePermissions } from "../../hooks/usePermissions";

interface InventoryRow {
  id: number;
  product_id: number;
  product_name: string | null;
  name_en: string | null;
  category: string | null;
  mark: string | null;
  condition: string;
  unit: string | null;
  offer_type: string;          // 区分 in_stock/pre_order（ADR-093 Phase 3）
  ship_timing: string | null;  // 発送日（予約品のみ）
  supplier_id: number;
  supplier_name: string | null;
  unit_price: number;
  quantity: number;
  tcg_type: string | null;
  offered_at: string;
}

interface SupplierFacet {
  id: number;
  name: string | null;
}

interface InventoryListResponse {
  items: InventoryRow[];
  total: number;
  page: number;
  per_page: number;
  suppliers?: SupplierFacet[];
}

// ADR-093 Phase 4: ユーザー別フィルタで取捨できる列（商品/仕入元の複合セルは常時表示）。
const HIDEABLE_COLUMNS = ["unit", "condition", "unitPrice", "quantity"] as const;

const PER_PAGE = 50;

export default function InventoryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();

  const [items, setItems] = useState<InventoryRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchQ, setSearchQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [tcgType, setTcgType] = useState("");
  const [offerTypeFilter, setOfferTypeFilter] = useState("");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ADR-093 Phase 4: ユーザー別フィルタ（ポップアップ・永続化）
  const [showFilterPanel, setShowFilterPanel] = useState(false);
  const [filterEnabled, setFilterEnabled] = useState(false);
  const [hiddenSupplierIds, setHiddenSupplierIds] = useState<Set<number>>(new Set());
  const [hiddenColumns, setHiddenColumns] = useState<Set<string>>(new Set());
  const [supplierFacet, setSupplierFacet] = useState<SupplierFacet[]>([]);
  const [filtersLoaded, setFiltersLoaded] = useState(false);

  // フィルタ ON 時のみ適用（OFF は全表示）。
  const colVisible = (c: string) => !filterEnabled || !hiddenColumns.has(c);
  const visibleColCount = 3 + HIDEABLE_COLUMNS.filter((c) => colVisible(c)).length;

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
      if (offerTypeFilter) params.set("offer_type", offerTypeFilter);
      // ADR-093 Phase 4: フィルタ ON 時のみ「仕入元 非表示」を適用
      if (filterEnabled && hiddenSupplierIds.size > 0) {
        params.set("hide_supplier_ids", Array.from(hiddenSupplierIds).join(","));
      }
      const d = await api.get<InventoryListResponse>(`/inventory?${params.toString()}`);
      setItems(d.items);
      setTotal(d.total);
      if (d.suppliers) setSupplierFacet(d.suppliers);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [page, order, debouncedQ, tcgType, offerTypeFilter, filterEnabled, hiddenSupplierIds, t]);

  useEffect(() => {
    void load();
  }, [load]);

  // ADR-093 Phase 4: 保存済みフィルタを初回ロード（再ログイン後も保持）
  useEffect(() => {
    let cancelled = false;
    api
      .get<{ enabled: boolean; hidden_supplier_ids: number[]; hidden_columns: string[] }>(
        "/me/inventory-filters",
      )
      .then((f) => {
        if (cancelled) return;
        setFilterEnabled(!!f.enabled);
        setHiddenSupplierIds(new Set(f.hidden_supplier_ids ?? []));
        setHiddenColumns(new Set(f.hidden_columns ?? []));
      })
      .catch(() => { /* 取得失敗時はデフォルト（全表示）のまま */ })
      .finally(() => { if (!cancelled) setFiltersLoaded(true); });
    return () => {
      cancelled = true;
    };
  }, []);

  // ADR-093 Phase 4: フィルタ変更をユーザー別に永続化（初回ロード後のみ・250ms デバウンス）
  useEffect(() => {
    if (!filtersLoaded) return;
    const timer = setTimeout(() => {
      void api
        .patch("/me/inventory-filters", {
          enabled: filterEnabled,
          hidden_supplier_ids: Array.from(hiddenSupplierIds),
          hidden_columns: Array.from(hiddenColumns),
        })
        .catch(() => { /* 保存失敗は致命でない（次回操作で再送） */ });
    }, 250);
    return () => clearTimeout(timer);
  }, [filtersLoaded, filterEnabled, hiddenSupplierIds, hiddenColumns]);

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

  // ADR-093 Phase 4: フィルタ操作（仕入元 表示/非表示・列 取捨）
  const toggleHiddenSupplier = (id: number) => {
    setHiddenSupplierIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setPage(1);
  };
  const toggleHiddenColumn = (col: string) => {
    setHiddenColumns((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else next.add(col);
      return next;
    });
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
        <select
          data-testid="inventory-offer-type-filter"
          value={offerTypeFilter}
          onChange={(e) => {
            setOfferTypeFilter(e.target.value);
            setPage(1);
          }}
          aria-label={t("inventory.filter.allOfferTypes")}
        >
          <option value="">{t("inventory.filter.allOfferTypes")}</option>
          <option value="in_stock">{t("inventory.offerType.in_stock")}</option>
          <option value="pre_order">{t("inventory.offerType.pre_order")}</option>
        </select>
        {/* ADR-093 Phase 4: ユーザー別フィルタ ポップアップ起動 */}
        <button
          type="button"
          className={filterEnabled ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
          data-testid="inventory-filter-toggle"
          aria-expanded={showFilterPanel}
          aria-pressed={filterEnabled}
          onClick={() => setShowFilterPanel((v) => !v)}
        >
          {t("inventory.filterPanel.button")}
        </button>
      </section>

      {/* ADR-093 Phase 4: フィルタ ポップアップ（ON/OFF・仕入元 表示/非表示・列 取捨。設定はユーザー別に永続化） */}
      {showFilterPanel && (
        <section
          className="inventory-filter-panel"
          data-testid="inventory-filter-panel"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-3)",
            margin: "0 0 var(--space-4)",
            padding: "var(--space-3)",
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            maxWidth: "40rem",
          }}
        >
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontWeight: "var(--font-weight-semi)" }}>
            <input
              type="checkbox"
              data-testid="inventory-filter-enabled"
              checked={filterEnabled}
              onChange={(e) => { setFilterEnabled(e.target.checked); setPage(1); }}
            />
            {t("inventory.filterPanel.enable")}
          </label>

          <div>
            <div style={{ fontSize: "var(--font-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-1)" }}>
              {t("inventory.filterPanel.suppliers")}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
              {supplierFacet.length === 0 ? (
                <span style={{ color: "var(--text-secondary)" }}>{t("inventory.noResults")}</span>
              ) : (
                supplierFacet.map((s) => (
                  <label key={s.id} style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                    <input
                      type="checkbox"
                      data-testid={`inventory-filter-supplier-${s.id}`}
                      checked={!hiddenSupplierIds.has(s.id)}
                      onChange={() => toggleHiddenSupplier(s.id)}
                    />
                    {s.name ?? `#${s.id}`}
                  </label>
                ))
              )}
            </div>
          </div>

          <div>
            <div style={{ fontSize: "var(--font-sm)", color: "var(--text-secondary)", marginBottom: "var(--space-1)" }}>
              {t("inventory.filterPanel.columns")}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
              {HIDEABLE_COLUMNS.map((c) => (
                <label key={c} style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                  <input
                    type="checkbox"
                    data-testid={`inventory-filter-col-${c}`}
                    checked={!hiddenColumns.has(c)}
                    onChange={() => toggleHiddenColumn(c)}
                  />
                  {t(`inventory.col.${c}`)}
                </label>
              ))}
            </div>
          </div>

          <div>
            <button type="button" className="btn-sm" onClick={() => setShowFilterPanel(false)}>
              {t("common.close")}
            </button>
          </div>
        </section>
      )}

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
          {hasPermission("purchase_orders.create") && (
            <button
              className="btn-primary btn-sm"
              onClick={() => goCreate("/purchase-orders")}
              data-testid="create-po-from-inventory"
            >
              {t("inventory.createPO")}
            </button>
          )}
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
            {colVisible("unit") && <th style={{ width: "6rem" }}>{t("inventory.col.unit")}</th>}
            {colVisible("condition") && <th style={{ width: "8rem" }}>{t("inventory.col.condition")}</th>}
            {colVisible("unitPrice") && <th style={{ width: "7rem", textAlign: "right" }}>{t("inventory.col.unitPrice")}</th>}
            {colVisible("quantity") && <th style={{ width: "5rem", textAlign: "right" }}>{t("inventory.col.quantity")}</th>}
            <th style={{ width: "11rem" }}>{t("inventory.col.supplier")}</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={visibleColCount} data-testid="inventory-empty">
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
                {colVisible("unit") && (
                  <td>{it.unit ? t(`inventory.unit.${it.unit}`, { defaultValue: it.unit }) : "-"}</td>
                )}
                {colVisible("condition") && (
                  <td>
                    <div>{t(`inventory.condition.${it.condition}`, { defaultValue: it.condition })}</div>
                    {it.offer_type === "pre_order" && (
                      <div style={{ marginTop: "var(--space-1)" }}>
                        <span className="badge badge-negotiating">{t("inventory.offerType.pre_order")}</span>
                        {it.ship_timing && (
                          <span style={{ fontSize: "var(--font-xs)", color: "var(--text-secondary)", marginLeft: "var(--space-1)" }}>
                            {t(`inventory.shipTiming.${it.ship_timing}`, { defaultValue: it.ship_timing })}
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                )}
                {colVisible("unitPrice") && (
                  <td style={{ textAlign: "right" }}>¥{it.unit_price.toLocaleString()}</td>
                )}
                {colVisible("quantity") && (
                  <td style={{ textAlign: "right" }}>{it.quantity}</td>
                )}
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

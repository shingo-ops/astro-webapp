/**
 * 受注管理 — グループ件数バッジ + 検索 / フィルタ / ソートコントロール。
 */

import { useTranslation } from "react-i18next";
import type { GroupCountsResponse } from "./orders.types";
import { STATUSES } from "./orders.types";

interface Props {
  statusFilter: string;
  setStatusFilter: (v: string) => void;
  searchInput: string;
  setSearchInput: (v: string) => void;
  sortBy: string;
  setSortBy: (v: string) => void;
  sortOrder: "asc" | "desc";
  toggleSortOrder: () => void;
  groupCounts: GroupCountsResponse | null;
  STATUS_LABELS: Record<string, string>;
  SORT_OPTIONS: { value: string; label: string }[];
}

export function OrdersFilterBar({
  statusFilter, setStatusFilter,
  searchInput, setSearchInput,
  sortBy, setSortBy,
  sortOrder, toggleSortOrder,
  groupCounts, STATUS_LABELS, SORT_OPTIONS,
}: Props) {
  const { t } = useTranslation();

  return (
    <>
      {/* グループ件数バッジ（ADR-021 AC-1.6） */}
      <div
        className="orders-group-counts"
        role="group"
        aria-label={t("common.status")}
        style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}
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

      {/* 検索 / ソートバー */}
      <div
        className="filter-bar"
        style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}
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
            <option key={s} value={s}>{STATUS_LABELS[s]}</option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          aria-label={t("common.filter")}
          data-testid="orders-sort-by"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
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
    </>
  );
}

/**
 * /super-admin/inventory-offers — 仕入元現在オファー一覧・編集画面 (Sprint 11 / F11 AC11.5)。
 *
 * spec.md v1.3 F11 / AC11.5:
 *   - is_super_admin=true のみアクセス可 (false なら 403 メッセージ + 二重ガード)
 *   - public.inventory の現在オファーを supplier × product × condition 単位で一覧
 *   - admin は quantity / unit_price / status / notes / expires_at を編集可能
 *   - 新規追加 + 削除 (UNIQUE 衝突は 409 で fail)
 *
 * 設計判断:
 *   - 営業フロー直結のため検索 (supplier_name / product_name / product_code 部分一致)
 *     と status / condition フィルタを優先
 *   - F6 承認時の UPSERT 結果 (source='f6_approved') と manual 編集 (source='manual')
 *     が混在するため source カラムで識別可能 (read-only 表示)
 *   - UNIQUE キー (supplier_id / product_id / condition) は PATCH 不可、
 *     変更したい場合は DELETE + POST する運用
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../../lib/api";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";
import { PageLayout } from "../../components/PageLayout";

type InventoryStatus = "in_stock" | "out_of_stock" | "reserved" | "archived";

interface InventoryOffer {
  id: number;
  supplier_id: number;
  product_id: number;
  condition: string;
  // ADR-093 Phase 3b: 区分(在庫/予約)・発送日（key 要素のため表示専用。編集は削除→再作成）
  offer_type: string;
  ship_timing: string | null;
  quantity: number;
  unit_price: number;
  status: InventoryStatus;
  notes_ja: string | null;
  notes_en: string | null;
  offered_at: string;
  expires_at: string | null;
  source: string;
  created_at: string;
  updated_at: string;
  supplier_name: string | null;
  product_code: string | null;
  product_name: string | null;
}

interface InventoryOffersListResponse {
  items: InventoryOffer[];
  total: number;
  page: number;
  per_page: number;
}

interface EditDraft {
  quantity: string;
  unit_price: string;
  status: InventoryStatus;
  notes_ja: string;
  notes_en: string;
  expires_at: string;
}

const STATUS_OPTIONS: InventoryStatus[] = [
  "in_stock",
  "out_of_stock",
  "reserved",
  "archived",
];

function offerToDraft(o: InventoryOffer): EditDraft {
  return {
    quantity: String(o.quantity),
    unit_price: String(o.unit_price),
    status: o.status,
    notes_ja: o.notes_ja ?? "",
    notes_en: o.notes_en ?? "",
    expires_at: o.expires_at ? o.expires_at.slice(0, 10) : "",
  };
}

export default function InventoryOffersPage() {
  const { t } = useTranslation();
  const { isSuperAdmin, loading: superAdminLoading } = useSuperAdmin();

  const [items, setItems] = useState<InventoryOffer[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage] = useState(50);
  const [searchQ, setSearchQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<InventoryStatus | "">("");
  const [conditionFilter, setConditionFilter] = useState("");
  // 入力値の debounce 反映先。テキスト入力は 250ms 待ってから API を叩く
  // (F7 InventorySearchBar と同じ閾値)。select の statusFilter は即時。
  const [debouncedSearchQ, setDebouncedSearchQ] = useState("");
  const [debouncedConditionFilter, setDebouncedConditionFilter] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const totalPages = useMemo(
    () => (total === 0 ? 1 : Math.ceil(total / perPage)),
    [total, perPage],
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQ(searchQ);
      setDebouncedConditionFilter(conditionFilter);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQ, conditionFilter]);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(perPage));
      if (debouncedSearchQ.trim()) params.set("q", debouncedSearchQ.trim());
      if (statusFilter) params.set("status", statusFilter);
      if (debouncedConditionFilter.trim())
        params.set("condition", debouncedConditionFilter.trim());

      const d = await api.get<InventoryOffersListResponse>(
        `/super-admin/inventory-offers?${params.toString()}`,
      );
      setItems(d.items);
      setTotal(d.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, debouncedSearchQ, statusFilter, debouncedConditionFilter, t]);

  useEffect(() => {
    if (!isSuperAdmin) return;
    void load();
  }, [isSuperAdmin, load]);

  const startEdit = (offer: InventoryOffer) => {
    setEditingId(offer.id);
    setDraft(offerToDraft(offer));
    setError("");
    setInfo("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft(null);
  };

  const submitEdit = async (offerId: number) => {
    if (!draft) return;
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const qty = draft.quantity.trim();
      const price = draft.unit_price.trim();
      const body: Record<string, unknown> = {
        quantity: qty ? Number.parseInt(qty, 10) : 0,
        unit_price: price ? Number.parseInt(price, 10) : 0,
        status: draft.status,
        notes_ja: draft.notes_ja || null,
        notes_en: draft.notes_en || null,
        expires_at: draft.expires_at ? `${draft.expires_at}T00:00:00Z` : null,
      };
      await api.patch(`/super-admin/inventory-offers/${offerId}`, body);
      setInfo(t("superAdmin.inventoryOffers.updateSuccess"));
      setEditingId(null);
      setDraft(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    } finally {
      setSubmitting(false);
    }
  };

  const deleteOffer = async (offerId: number, productName: string | null) => {
    if (
      !window.confirm(
        t("superAdmin.inventoryOffers.deleteConfirm", {
          name: productName ?? `#${offerId}`,
        }),
      )
    ) {
      return;
    }
    setError("");
    setInfo("");
    try {
      await api.delete(`/super-admin/inventory-offers/${offerId}`);
      setInfo(t("superAdmin.inventoryOffers.deleteSuccess"));
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError(t("superAdmin.inventoryOffers.notFound"));
      } else {
        setError(e instanceof Error ? e.message : t("common.operationError"));
      }
    }
  };

  if (superAdminLoading) {
    return (
      <PageLayout navKey="nav.superAdminInventoryOffers">
        <div>{t("common.loading")}</div>
      </PageLayout>
    );
  }

  if (!isSuperAdmin) {
    return (
      <PageLayout
        navKey="nav.superAdminInventoryOffers"
        subtitleKey="superAdmin.subtitle"
      >
        <div className="error-message" role="alert">
          {t("superAdmin.accessDenied")}
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      navKey="nav.superAdminInventoryOffers"
      subtitleKey="superAdmin.inventoryOffers.subtitle"
    >
      {error && (
        <div className="error-message" role="alert" data-testid="offers-error">
          {error}
        </div>
      )}
      {info && (
        <div className="info-message" role="status" data-testid="offers-info">
          {info}
        </div>
      )}

      <section
        className="offers-filter"
        style={{
          display: "flex",
          gap: "var(--space-2)",
          flexWrap: "wrap",
          marginBottom: "var(--space-4)",
          position: "sticky",
          top: 0,
          background: "var(--bg-base)",
          paddingTop: "var(--space-2)",
          paddingBottom: "var(--space-2)",
          zIndex: 1,
        }}
      >
        <input
          type="search"
          placeholder={t("superAdmin.inventoryOffers.searchPlaceholder")}
          data-testid="offers-search"
          value={searchQ}
          onChange={(e) => {
            setSearchQ(e.target.value);
            setPage(1);
          }}
          style={{ minWidth: "18rem" }}
        />
        <select
          data-testid="offers-status-filter"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as InventoryStatus | "");
            setPage(1);
          }}
        >
          <option value="">{t("superAdmin.inventoryOffers.statusAny")}</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {t(`superAdmin.inventoryOffers.status.${s}`)}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder={t("superAdmin.inventoryOffers.conditionPlaceholder")}
          data-testid="offers-condition-filter"
          value={conditionFilter}
          onChange={(e) => {
            setConditionFilter(e.target.value);
            setPage(1);
          }}
          style={{ width: "10rem" }}
        />
      </section>

      {/* レイアウトシフト防止: loading 中も DOM に残し、visibility だけ切り替える */}
      <div
        className="loading-indicator"
        data-testid="offers-loading"
        aria-live="polite"
        aria-hidden={!loading}
        style={{
          minHeight: "1.5rem",
          visibility: loading ? "visible" : "hidden",
        }}
      >
        {t("common.loading")}
      </div>

      <table
        className="data-table offers-table-styled"
        data-testid="offers-table"
        aria-busy={loading}
      >
        <thead>
          <tr>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.supplier")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.product")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.condition")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.offerType")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.shipTiming")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.quantity")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.unitPrice")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.status")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.source")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.expiresAt")}</th>
            <th style={{ textAlign: "center" }}>{t("superAdmin.inventoryOffers.col.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={11} data-testid="offers-empty">
                {t("superAdmin.inventoryOffers.noResults")}
              </td>
            </tr>
          ) : (
            items.map((o) => {
              const isEditing = editingId === o.id;
              return (
                <tr key={o.id} data-testid={`offers-row-${o.id}`}>
                  <td>{o.supplier_name ?? `#${o.supplier_id}`}</td>
                  <td>
                    <div>{o.product_name ?? `#${o.product_id}`}</div>
                    {o.product_code && (
                      <code style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
                        {o.product_code}
                      </code>
                    )}
                  </td>
                  <td>
                    <code>{o.condition}</code>
                  </td>
                  {/* ADR-093 Phase 3b: 区分/発送日（表示専用） */}
                  <td style={{ textAlign: "center" }}>
                    {t(`inventory.offerType.${o.offer_type}`, { defaultValue: o.offer_type })}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {o.ship_timing
                      ? t(`inventory.shipTiming.${o.ship_timing}`, { defaultValue: o.ship_timing })
                      : "-"}
                  </td>
                  <td>
                    {isEditing && draft ? (
                      <input
                        type="number"
                        min="0"
                        data-testid={`offers-row-${o.id}-quantity`}
                        value={draft.quantity}
                        onChange={(e) =>
                          setDraft({ ...draft, quantity: e.target.value })
                        }
                        style={{ width: "5rem" }}
                      />
                    ) : (
                      o.quantity
                    )}
                  </td>
                  <td>
                    {isEditing && draft ? (
                      <input
                        type="number"
                        min="0"
                        data-testid={`offers-row-${o.id}-unit-price`}
                        value={draft.unit_price}
                        onChange={(e) =>
                          setDraft({ ...draft, unit_price: e.target.value })
                        }
                        style={{ width: "6rem" }}
                      />
                    ) : (
                      o.unit_price.toLocaleString()
                    )}
                  </td>
                  <td>
                    {isEditing && draft ? (
                      <select
                        data-testid={`offers-row-${o.id}-status`}
                        value={draft.status}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            status: e.target.value as InventoryStatus,
                          })
                        }
                      >
                        {STATUS_OPTIONS.map((s) => (
                          <option key={s} value={s}>
                            {t(`superAdmin.inventoryOffers.status.${s}`)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      t(`superAdmin.inventoryOffers.status.${o.status}`)
                    )}
                  </td>
                  <td>
                    <span data-testid={`offers-row-${o.id}-source`}>
                      {t(
                        `superAdmin.inventoryOffers.source.${o.source}`,
                        o.source,
                      )}
                    </span>
                  </td>
                  <td>
                    {isEditing && draft ? (
                      <input
                        type="date"
                        data-testid={`offers-row-${o.id}-expires-at`}
                        value={draft.expires_at}
                        onChange={(e) =>
                          setDraft({ ...draft, expires_at: e.target.value })
                        }
                      />
                    ) : o.expires_at ? (
                      o.expires_at.slice(0, 10)
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    {isEditing ? (
                      <>
                        <button
                          onClick={() => void submitEdit(o.id)}
                          disabled={submitting}
                          data-testid={`offers-row-${o.id}-save`}
                          className="btn-primary"
                        >
                          {t("common.save")}
                        </button>
                        <button
                          onClick={cancelEdit}
                          className="btn-secondary"
                          style={{ marginLeft: "var(--space-1)" }}
                        >
                          {t("common.cancel")}
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => startEdit(o)}
                          data-testid={`offers-row-${o.id}-edit`}
                          className="btn-secondary"
                        >
                          {t("common.edit")}
                        </button>
                        <button
                          onClick={() => void deleteOffer(o.id, o.product_name)}
                          data-testid={`offers-row-${o.id}-delete`}
                          className="btn-danger"
                          style={{ marginLeft: "var(--space-1)" }}
                        >
                          {t("common.delete")}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>

      <section
        className="offers-pagination"
        style={{
          marginTop: "var(--space-4)",
          marginBottom: "var(--space-6)",
          display: "flex",
          gap: "var(--space-2)",
          alignItems: "center",
        }}
      >
        <button
          onClick={() => setPage(Math.max(1, page - 1))}
          disabled={page <= 1 || loading}
          data-testid="offers-prev"
          className="btn-secondary"
        >
          {t("common.previous")}
        </button>
        <span data-testid="offers-pagination-label">
          {t("superAdmin.inventoryOffers.pageOf", {
            page,
            total: totalPages,
            count: total,
          })}
        </span>
        <button
          onClick={() => setPage(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages || loading}
          data-testid="offers-next"
          className="btn-secondary"
        >
          {t("common.next")}
        </button>
      </section>
    </PageLayout>
  );
}

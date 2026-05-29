/**
 * 商品・在庫管理ページ。
 * 商品マスタのCRUD + 在庫数表示。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 *   2026-04-28: Phase 1-C M-MVP（Q4/Q5/Q9 確定）
 *               - TCG 列追加（jan_code, card_number, expansion_code, rarity, language）
 *               - 多通貨価格（unit_price_usd, unit_price_eur）
 *               - 画像 URL（image_url、単一列）
 *               - is_archived フィルタ + 廃番ボタン
 *               - DELETE 409（FK 参照あり）時にアーカイブ誘導モーダル
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../lib/api";
import ConfirmModal from "../../components/ConfirmModal";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";

interface Product {
  id: number;
  product_code: string | null;
  name_ja: string;
  name_en: string | null;
  category: string | null;
  mark: string | null;
  status: string;
  condition: string | null;
  unit_price: number | null;
  quantity: number;
  weight: number | null;
  notes: string | null;
  release_date: string | null;
  created_at: string;
  updated_at: string;
  // Phase 1-C M-MVP（2026-04-28）
  jan_code: string | null;
  card_number: string | null;
  expansion_code: string | null;
  rarity: string | null;
  language: string | null;
  unit_price_usd: number | null;
  unit_price_eur: number | null;
  image_url: string | null;
  is_archived: boolean;
  archived_at: string | null;
  supplier_default_id: number | null;
}

type FormState = {
  name_ja: string;
  name_en: string;
  category: string;
  mark: string;
  status: string;
  condition: string;
  unit_price: string;
  quantity: string;
  weight: string;
  notes: string;
  // Phase 1-C M-MVP
  jan_code: string;
  card_number: string;
  expansion_code: string;
  rarity: string;
  language: string;
  unit_price_usd: string;
  unit_price_eur: string;
  image_url: string;
};

const emptyForm: FormState = {
  name_ja: "", name_en: "", category: "", mark: "",
  status: "active", condition: "", unit_price: "", quantity: "0",
  weight: "", notes: "",
  jan_code: "", card_number: "", expansion_code: "", rarity: "", language: "",
  unit_price_usd: "", unit_price_eur: "", image_url: "",
};

interface ArchiveBlockedDetail {
  id: number;
  name_ja: string;
  is_archived: boolean;
  blocking_references: string[];
  detail: string;
}

export default function ProductsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  // QA r7: 190 件全件閲覧のため pagination 追加。backend per_page max=100
  const [page, setPage] = useState(1);
  const PER_PAGE = 100;
  // 100 件以上ある場合、次ページが存在することを判定するために 101 件取りに行く
  // (backend は max 100 なので、別 fetch で簡易判定する代わりに、
  //  返ってきた件数が PER_PAGE ちょうどなら「次がある可能性あり」とする)
  const [hasNext, setHasNext] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);
  const [archiveBlocked, setArchiveBlocked] = useState<ArchiveBlockedDetail | null>(null);

  const load = async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      params.set("page", String(page));
      params.set("per_page", String(PER_PAGE));
      const qs = `?${params.toString()}`;
      const data = await api.get<Product[]>(`/products${qs}`);
      setProducts(data);
      // 返ってきた件数が PER_PAGE と同じなら、次ページ存在の可能性あり
      setHasNext(data.length === PER_PAGE);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  // search 変更時は page を 1 に戻す
  useEffect(() => {
    setPage(1);
  }, [search]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [search, page]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const toNull = (v: string) => (v ? v : null);
    const payload = {
      name_ja: form.name_ja,
      name_en: toNull(form.name_en),
      category: toNull(form.category),
      mark: toNull(form.mark),
      status: form.status,
      condition: toNull(form.condition),
      unit_price: form.unit_price ? Number(form.unit_price) : null,
      quantity: Number(form.quantity),
      weight: form.weight ? Number(form.weight) : null,
      notes: toNull(form.notes),
      jan_code: toNull(form.jan_code),
      card_number: toNull(form.card_number),
      expansion_code: toNull(form.expansion_code),
      rarity: toNull(form.rarity),
      language: toNull(form.language),
      unit_price_usd: form.unit_price_usd ? Number(form.unit_price_usd) : null,
      unit_price_eur: form.unit_price_eur ? Number(form.unit_price_eur) : null,
      image_url: toNull(form.image_url),
    };
    try {
      if (editId) {
        await api.patch(`/products/${editId}`, payload);
      } else {
        await api.post("/products", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    }
  };

  const handleEdit = (p: Product) => {
    setEditId(p.id);
    setForm({
      name_ja: p.name_ja,
      name_en: p.name_en || "",
      category: p.category || "",
      mark: p.mark || "",
      status: p.status,
      condition: p.condition || "",
      unit_price: p.unit_price != null ? String(p.unit_price) : "",
      quantity: String(p.quantity),
      weight: p.weight != null ? String(p.weight) : "",
      notes: p.notes || "",
      jan_code: p.jan_code || "",
      card_number: p.card_number || "",
      expansion_code: p.expansion_code || "",
      rarity: p.rarity || "",
      language: p.language || "",
      unit_price_usd: p.unit_price_usd != null ? String(p.unit_price_usd) : "",
      unit_price_eur: p.unit_price_eur != null ? String(p.unit_price_eur) : "",
      image_url: p.image_url || "",
    });
    setShowForm(true);
  };

  const handleArchiveToggle = async (p: Product) => {
    try {
      await api.patch(`/products/${p.id}`, { is_archived: !p.is_archived });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/products/${id}`);
      load();
    } catch (e) {
      // 409 (FK 参照あり) はアーカイブ誘導モーダルへ
      if (e instanceof ApiError && e.status === 409) {
        const detail = e.responseDetail as Partial<ArchiveBlockedDetail> | undefined;
        if (detail && Array.isArray(detail.blocking_references)) {
          setArchiveBlocked(detail as ArchiveBlockedDetail);
          return;
        }
      }
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const handleArchiveFromBlocked = async () => {
    if (!archiveBlocked) return;
    const id = archiveBlocked.id;
    setArchiveBlocked(null);
    try {
      await api.patch(`/products/${id}`, { is_archived: true });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  return (
    <PageLayout
      navKey="nav.inventory"
      subtitleKey="products.subtitle"
      headerAction={hasPermission("products.create") ? (
        <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>{t("products.newProduct")}</button>
      ) : undefined}
    >
      <div className="search-bar" style={{ display: "flex", gap: "var(--space-4)", alignItems: "center" }}>
        <input type="text" placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("products.editProduct") : t("products.newProduct")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("products.nameJa")} *</label>
                <input required value={form.name_ja} onChange={(e) => setForm({ ...form, name_ja: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("products.nameEn")}</label>
                <input value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("leads.type")}</label>
                <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("common.code")}</label>
                <input value={form.mark} onChange={(e) => setForm({ ...form, mark: e.target.value })} />
              </div>

              {/* Phase 1-C M-MVP: TCG 列 */}
              <fieldset style={{ border: "1px solid var(--border)", padding: "var(--space-3)", marginBottom: "var(--space-4)" }}>
                <legend style={{ padding: "0 var(--space-2)", fontSize: "var(--font-sm)", color: "var(--text-secondary)" }}>TCG</legend>
                <div className="form-group"><label>JAN/EAN</label>
                  <input maxLength={20} value={form.jan_code} onChange={(e) => setForm({ ...form, jan_code: e.target.value })} />
                </div>
                <div className="form-group"><label>{t("common.code")}</label>
                  <input maxLength={50} value={form.card_number} onChange={(e) => setForm({ ...form, card_number: e.target.value })} />
                </div>
                <div className="form-group"><label>{t("common.code")}</label>
                  <input maxLength={20} value={form.expansion_code} onChange={(e) => setForm({ ...form, expansion_code: e.target.value })} />
                </div>
                <div className="form-group"><label>{t("common.type")}</label>
                  <input maxLength={20} value={form.rarity} onChange={(e) => setForm({ ...form, rarity: e.target.value })} />
                </div>
                <div className="form-group"><label>{t("language.label")}</label>
                  <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                    <option value="">-</option>
                    <option value="ja">{t("language.ja")}</option>
                    <option value="en">{t("language.en")}</option>
                    <option value="kr">Korean (kr)</option>
                    <option value="zh">Chinese (zh)</option>
                  </select>
                </div>
              </fieldset>

              <div className="form-group"><label>{t("common.status")}</label>
                <input value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })} />
              </div>

              {/* 価格 */}
              <fieldset style={{ border: "1px solid var(--border)", padding: "var(--space-3)", marginBottom: "var(--space-4)" }}>
                <legend style={{ padding: "0 var(--space-2)", fontSize: "var(--font-sm)", color: "var(--text-secondary)" }}>{t("products.unitPrice")}</legend>
                <div className="form-group"><label>{t("products.unitPrice")} (JPY)</label>
                  <input type="number" min="0" step="0.01" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
                </div>
                <div className="form-group"><label>{t("products.unitPrice")} (USD)</label>
                  <input type="number" min="0" step="0.01" value={form.unit_price_usd} onChange={(e) => setForm({ ...form, unit_price_usd: e.target.value })} />
                </div>
                <div className="form-group"><label>{t("products.unitPrice")} (EUR)</label>
                  <input type="number" min="0" step="0.01" value={form.unit_price_eur} onChange={(e) => setForm({ ...form, unit_price_eur: e.target.value })} />
                </div>
              </fieldset>

              <div className="form-group"><label>{t("products.stockQty")}</label>
                <input type="number" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("products.weight")}</label>
                <input type="number" min="0" step="0.001" value={form.weight} onChange={(e) => setForm({ ...form, weight: e.target.value })} />
              </div>
              <div className="form-group"><label>URL</label>
                <input type="url" maxLength={500} placeholder="https://..." value={form.image_url} onChange={(e) => setForm({ ...form, image_url: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("common.status")}</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="active">{t("products.status_active")}</option>
                  <option value="discontinued">{t("products.status_discontinued")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("common.notes")}</label>
                <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{editId ? t("common.update") : t("common.register")}</button>
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
              <th>{t("common.name")}</th>
              <th>{t("quotes.items")}</th>
              <th>{t("language.label")}</th>
              <th>{t("leads.type")}</th>
              <th>{t("products.unitPrice")}</th>
              <th>{t("products.stockQty")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => {
              const isOutOfStock = p.quantity <= 0;
              const rowStyle: React.CSSProperties = {};
              if (p.is_archived) rowStyle.opacity = "var(--opacity-archived)";
              // 在庫0行の背景は CSS (.data-table tr[data-zero-stock="true"]) で濃淡を付ける。
              // 文字の視認性を保つため opacity は下げない (QA 2026-05-29)。
              return (
              <tr key={p.id} style={rowStyle} data-zero-stock={isOutOfStock ? "true" : "false"}>
                <td>
                  {p.image_url && <img src={p.image_url} alt="" style={{ width: 'var(--icon-lg)', height: 'var(--icon-lg)', marginRight: "var(--space-1)", objectFit: "cover", verticalAlign: "middle", borderRadius: "var(--radius-xs)" }} />}
                  {isOutOfStock && !p.is_archived && (
                    <span title={t("products.outOfStockTooltip")} aria-label={t("products.outOfStockTooltip")} style={{ marginRight: "var(--space-6px)", color: "var(--color-warning)", fontWeight: "var(--font-weight-semi)" }}>
                      &#9888;
                    </span>
                  )}
                  {p.name_ja}
                  {p.is_archived && <span className="badge badge-lost" style={{ marginLeft: "var(--space-6px)" }}>{t("products.status_discontinued")}</span>}
                </td>
                <td>{p.rarity || "-"}</td>
                <td>{p.language ? t(`language.${p.language}`, { defaultValue: p.language }) : "-"}</td>
                <td>{p.category || "-"}</td>
                <td>
                  {p.unit_price != null ? `¥${Math.round(p.unit_price).toLocaleString()}` : "-"}
                  {(p.unit_price_usd != null || p.unit_price_eur != null) && (
                    <span style={{ display: "block", fontSize: "var(--font-xs)", color: "var(--text-secondary)" }}>
                      {p.unit_price_usd != null ? `$${p.unit_price_usd}` : ""}
                      {p.unit_price_usd != null && p.unit_price_eur != null ? " / " : ""}
                      {p.unit_price_eur != null ? `€${p.unit_price_eur}` : ""}
                    </span>
                  )}
                </td>
                <td>
                  <span style={{ color: p.quantity <= 0 ? "var(--danger)" : "inherit", fontWeight: p.quantity <= 0 ? "var(--font-weight-semi)" : "var(--font-weight-normal)" }}>
                    {p.quantity}
                  </span>
                </td>
                <td><span className={`badge badge-${p.status === "active" ? "won" : "lost"}`}>{p.status === "active" ? t("products.status_active") : t("products.status_discontinued")}</span></td>
                <td className="actions">
                  {hasPermission("products.update") && <button className="btn-sm" onClick={() => handleEdit(p)}>{t("common.edit")}</button>}
                  {hasPermission("products.update") && (
                    <button className="btn-sm" onClick={() => handleArchiveToggle(p)}>
                      {p.is_archived ? t("common.reload") : t("common.add")}
                    </button>
                  )}
                  {hasPermission("products.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(p)}>{t("common.delete")}</button>}
                </td>
              </tr>
              );
            })}
            {products.length === 0 && <tr><td colSpan={8} className="empty">{t("products.noProducts")}</td></tr>}
          </tbody>
        </table>
      )}

      {/* QA r7: 件数表示は常時、前/次 button は pagination 必要時のみ。
          管理センター内 (二重 PageLayout) でも見切れないよう sticky bottom。 */}
      {!loading && products.length > 0 && (
        <div
          className="pagination"
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: "var(--space-3)",
            padding: "var(--space-3) 0",
            position: "sticky",
            bottom: 0,
            background: "var(--bg-surface)",
            borderTop: "1px solid var(--border-color)",
            zIndex: 1,
          }}
          data-testid="products-pagination"
        >
          {(page > 1 || hasNext) && (
            <button
              className="btn-sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              data-testid="products-page-prev"
            >
              {t("common.prevPage")}
            </button>
          )}
          <span style={{ color: "var(--text-secondary)" }} data-testid="products-page-info">
            {t("products.pageLabel", { page, count: products.length })}
          </span>
          {(page > 1 || hasNext) && (
            <button
              className="btn-sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={!hasNext}
              data-testid="products-page-next"
            >
              {t("common.nextPage")}
            </button>
          )}
        </div>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("products.deleteProduct")}
        message={<><strong>{deleteTarget?.name_ja}</strong><br />{t("common.irreversible")}</>}
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      <ConfirmModal
        open={!!archiveBlocked}
        title={t("common.error")}
        message={
          <>
            <strong>{archiveBlocked?.name_ja}</strong>
            {archiveBlocked && archiveBlocked.blocking_references.length > 0 ? (
              <ul>{archiveBlocked.blocking_references.map((r) => <li key={r}>{r}</li>)}</ul>
            ) : (
              <p style={{ color: "var(--text-secondary)" }}>{t("common.notSet")}</p>
            )}
          </>
        }
        confirmLabel={t("common.add")}
        onConfirm={handleArchiveFromBlocked}
        onCancel={() => setArchiveBlocked(null)}
      />
    </PageLayout>
  );
}

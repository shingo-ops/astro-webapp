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
 *               - DELETE 409（FK 参照あり）時にアーカイブ誘導モーダル（廃番の唯一の導線）
 *               注: 廃番フィルタ(#1174) と行内「追加」(=廃番トグル) ボタン(QA 2026-05-30) は撤去済み
 */

import { useEffect, useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../lib/api";
import ConfirmModal from "../../components/ConfirmModal";
import { usePermissions } from "../../hooks/usePermissions";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";
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

// 受信通知 → 商品マスタ取込（プレビュー付き）の候補
interface InboundProductCandidate {
  name: string;
  occurrences: number;
  sample: string | null;
}

export default function ProductsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const { isSuperAdmin } = useSuperAdmin();
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
  // QA 2026-05-31: 在庫表からチェックして見積/請求を作成するための複数選択
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // QA 2026-05-31: 受信通知 → 商品マスタ取込（プレビュー付き）
  const [showImport, setShowImport] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importApplying, setImportApplying] = useState(false);
  const [importError, setImportError] = useState("");
  const [candidates, setCandidates] = useState<InboundProductCandidate[]>([]);
  const [importSelected, setImportSelected] = useState<Set<string>>(new Set());
  const [importCategory, setImportCategory] = useState("");
  const [importDone, setImportDone] = useState("");
  const navigate = useNavigate();

  // 受信通知から未登録の商品名候補を取得してプレビューを開く
  const openImport = async () => {
    setShowImport(true);
    setImportError("");
    setImportDone("");
    setImportLoading(true);
    setCandidates([]);
    setImportSelected(new Set());
    setImportCategory("");
    try {
      const data = await api.get<{ candidates: InboundProductCandidate[]; total: number }>(
        "/super-admin/inbound/product-candidates",
      );
      setCandidates(data.candidates);
      // デフォルトは全選択（オペレータがノイズを外す運用）
      setImportSelected(new Set(data.candidates.map((c) => c.name)));
    } catch (e) {
      setImportError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setImportLoading(false);
    }
  };

  const toggleImport = (name: string) => {
    setImportSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const allImportSelected = candidates.length > 0 && importSelected.size === candidates.length;
  const toggleImportAll = () => {
    setImportSelected(allImportSelected ? new Set() : new Set(candidates.map((c) => c.name)));
  };

  // 選択した候補を商品マスタへ一括登録
  const applyImport = async () => {
    const names = candidates.map((c) => c.name).filter((n) => importSelected.has(n));
    if (names.length === 0) return;
    setImportApplying(true);
    setImportError("");
    try {
      const res = await api.post<{ inserted: number; skipped: number }>(
        "/super-admin/inbound/product-candidates/apply",
        { names, category: importCategory.trim() || null },
      );
      setShowImport(false);
      setImportDone(t("products.importDone", { count: res.inserted }));
      load();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setImportApplying(false);
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // 選択商品を初期明細として見積/請求の作成画面へ渡す
  const goCreate = (path: string) => {
    const selectedProducts = products
      .filter((p) => selectedIds.has(p.id))
      .map((p) => ({
        product_id: p.id,
        product_name: p.name_ja,
        unit_price: p.unit_price,
      }));
    if (selectedProducts.length === 0) return;
    navigate(path, { state: { selectedProducts } });
  };

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
      headerAction={
        (hasPermission("products.create") || isSuperAdmin) ? (
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            {isSuperAdmin && (
              <button className="btn-secondary" onClick={openImport} data-testid="open-import-from-inbound">
                {t("products.importFromInbound")}
              </button>
            )}
            {hasPermission("products.create") && (
              <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>{t("products.newProduct")}</button>
            )}
          </div>
        ) : undefined
      }
    >
      <div className="search-bar" style={{ display: "flex", gap: "var(--space-4)", alignItems: "center" }}>
        <input type="text" placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {/* QA 2026-05-31: 在庫表からチェックした商品で見積/請求を作成 */}
      {selectedIds.size > 0 && (
        <div
          className="selection-action-bar"
          style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap", margin: "var(--space-2) 0", padding: "var(--space-2) var(--space-3)", background: "var(--bg-subtle)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}
        >
          <span style={{ fontWeight: "var(--font-weight-semi)" }}>
            {t("products.selectedCount", { count: selectedIds.size })}
          </span>
          <button className="btn-primary btn-sm" onClick={() => goCreate("/quotes/new")} data-testid="create-quote-from-products">
            {t("products.createQuote")}
          </button>
          <button className="btn-primary btn-sm" onClick={() => goCreate("/invoices/new")} data-testid="create-invoice-from-products">
            {t("products.createInvoice")}
          </button>
          <button className="btn-sm" onClick={() => setSelectedIds(new Set())}>
            {t("common.clear")}
          </button>
        </div>
      )}

      {error && <div className="error-message">{error}</div>}
      {importDone && <div className="success-message" data-testid="import-done">{importDone}</div>}

      {showImport && (
        <div className="modal-overlay" onClick={() => !importApplying && setShowImport(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("products.importFromInbound")}</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)", marginTop: 0 }}>
              {t("products.importFromInboundHint")}
            </p>
            {importError && <div className="error-message">{importError}</div>}
            {importLoading ? (
              <div className="loading">{t("common.loading")}</div>
            ) : candidates.length === 0 ? (
              <p className="empty">{t("products.importNoCandidates")}</p>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap", marginBottom: "var(--space-2)" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "var(--space-1)", cursor: "pointer" }}>
                    <input type="checkbox" checked={allImportSelected} onChange={toggleImportAll} data-testid="import-select-all" />
                    {t("common.selectAll")}
                  </label>
                  <span style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)" }}>
                    {t("products.importCandidateCount", { count: candidates.length })}
                  </span>
                  <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                    <label style={{ fontSize: "var(--font-sm)", color: "var(--text-secondary)" }}>{t("leads.type")}</label>
                    <input
                      style={{ width: "var(--input-width-product-name)" }}
                      placeholder={t("common.optional")}
                      value={importCategory}
                      onChange={(e) => setImportCategory(e.target.value)}
                      data-testid="import-category"
                    />
                  </span>
                </div>
                <div style={{ maxHeight: "50vh", overflowY: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th style={{ width: "var(--col-width-checkbox)", textAlign: "center" }} aria-label={t("common.select")}></th>
                        <th>{t("common.name")}</th>
                        <th style={{ width: "var(--col-width-checkbox)", textAlign: "right" }}>{t("products.importOccurrences")}</th>
                        <th>{t("products.importSample")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((c) => (
                        <tr key={c.name}>
                          <td style={{ textAlign: "center" }}>
                            <input
                              type="checkbox"
                              checked={importSelected.has(c.name)}
                              onChange={() => toggleImport(c.name)}
                              aria-label={c.name}
                            />
                          </td>
                          <td>{c.name}</td>
                          <td style={{ textAlign: "right" }}>{c.occurrences}</td>
                          <td style={{ color: "var(--text-secondary)", fontSize: "var(--font-xs)" }}>{c.sample || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowImport(false)} disabled={importApplying}>{t("common.cancel")}</button>
              <button
                type="button"
                className="btn-primary"
                onClick={applyImport}
                disabled={importApplying || importLoading || importSelected.size === 0}
                data-testid="import-apply"
              >
                {importApplying ? t("common.loading") : t("products.importApply", { count: importSelected.size })}
              </button>
            </div>
          </div>
        </div>
      )}

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
              <th style={{ width: "var(--col-width-checkbox)", textAlign: "center" }} aria-label={t("common.select")}></th>
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
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(p.id)}
                    onChange={() => toggleSelect(p.id)}
                    aria-label={t("common.select")}
                    data-testid={`product-select-${p.id}`}
                  />
                </td>
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
                  {/* QA 2026-05-30: 「追加」と誤表記された廃番(archive)トグルを撤去（誤クリックで行が消える事故防止）。
                      廃番は「削除」の FK 参照時フォールバック (handleArchiveFromBlocked) でのみ行う。 */}
                  {hasPermission("products.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(p)}>{t("common.delete")}</button>}
                </td>
              </tr>
              );
            })}
            {products.length === 0 && <tr><td colSpan={9} className="empty">{t("products.noProducts")}</td></tr>}
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
        confirmLabel={t("common.archive")}
        onConfirm={handleArchiveFromBlocked}
        onCancel={() => setArchiveBlocked(null)}
      />
    </PageLayout>
  );
}

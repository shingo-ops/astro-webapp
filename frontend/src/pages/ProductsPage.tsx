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
import { api, ApiError } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

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
  const { hasPermission } = usePermissions();
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
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
      if (showArchived) params.set("archived", "true");
      const qs = params.toString() ? `?${params.toString()}` : "";
      const data = await api.get<Product[]>(`/products${qs}`);
      setProducts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [search, showArchived]);

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
      setError(e instanceof Error ? e.message : "保存に失敗しました");
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
      setError(e instanceof Error ? e.message : "アーカイブ切替に失敗しました");
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
      setError(e instanceof Error ? e.message : "削除に失敗しました");
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
      setError(e instanceof Error ? e.message : "アーカイブに失敗しました");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>在庫管理</h2>
        {hasPermission("products.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>商品登録</button>
        )}
      </div>

      <div className="search-bar" style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
        <input type="text" placeholder="商品名・コード・JAN・カード番号で検索..." value={search} onChange={(e) => setSearch(e.target.value)} />
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", whiteSpace: "nowrap" }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          廃番を含む
        </label>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "商品編集" : "商品登録"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>商品名（日本語） *</label>
                <input required value={form.name_ja} onChange={(e) => setForm({ ...form, name_ja: e.target.value })} />
              </div>
              <div className="form-group"><label>商品名（英語）</label>
                <input value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} />
              </div>
              <div className="form-group"><label>カテゴリ</label>
                <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
              </div>
              <div className="form-group"><label>マーク / SKU</label>
                <input value={form.mark} onChange={(e) => setForm({ ...form, mark: e.target.value })} />
              </div>

              {/* Phase 1-C M-MVP: TCG 列 */}
              <fieldset style={{ border: "1px solid var(--border)", padding: "0.75rem", marginBottom: "1rem" }}>
                <legend style={{ padding: "0 0.5rem", fontSize: "0.85rem", color: "var(--text-secondary)" }}>TCG / 国際取引項目</legend>
                <div className="form-group"><label>JAN/EAN コード</label>
                  <input maxLength={20} placeholder="例: 4521329211527" value={form.jan_code} onChange={(e) => setForm({ ...form, jan_code: e.target.value })} />
                </div>
                <div className="form-group"><label>カード番号</label>
                  <input maxLength={50} placeholder="例: SV5a-001/073" value={form.card_number} onChange={(e) => setForm({ ...form, card_number: e.target.value })} />
                </div>
                <div className="form-group"><label>拡張パック略号</label>
                  <input maxLength={20} placeholder="例: SV5a" value={form.expansion_code} onChange={(e) => setForm({ ...form, expansion_code: e.target.value })} />
                </div>
                <div className="form-group"><label>レアリティ</label>
                  <input maxLength={20} placeholder="例: SAR / RR / UR" value={form.rarity} onChange={(e) => setForm({ ...form, rarity: e.target.value })} />
                </div>
                <div className="form-group"><label>言語版</label>
                  <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                    <option value="">-</option>
                    <option value="ja">日本語 (ja)</option>
                    <option value="en">英語 (en)</option>
                    <option value="kr">韓国語 (kr)</option>
                    <option value="zh">中国語 (zh)</option>
                  </select>
                </div>
              </fieldset>

              <div className="form-group"><label>状態</label>
                <input placeholder="例: 新品、中古" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })} />
              </div>

              {/* 価格 */}
              <fieldset style={{ border: "1px solid var(--border)", padding: "0.75rem", marginBottom: "1rem" }}>
                <legend style={{ padding: "0 0.5rem", fontSize: "0.85rem", color: "var(--text-secondary)" }}>価格</legend>
                <div className="form-group"><label>単価 (JPY)</label>
                  <input type="number" min="0" step="0.01" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
                </div>
                <div className="form-group"><label>単価 (USD)</label>
                  <input type="number" min="0" step="0.01" value={form.unit_price_usd} onChange={(e) => setForm({ ...form, unit_price_usd: e.target.value })} />
                </div>
                <div className="form-group"><label>単価 (EUR)</label>
                  <input type="number" min="0" step="0.01" value={form.unit_price_eur} onChange={(e) => setForm({ ...form, unit_price_eur: e.target.value })} />
                </div>
              </fieldset>

              <div className="form-group"><label>在庫数量</label>
                <input type="number" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
              </div>
              <div className="form-group"><label>重量 (kg)</label>
                <input type="number" min="0" step="0.001" value={form.weight} onChange={(e) => setForm({ ...form, weight: e.target.value })} />
              </div>
              <div className="form-group"><label>商品画像 URL</label>
                <input type="url" maxLength={500} placeholder="https://..." value={form.image_url} onChange={(e) => setForm({ ...form, image_url: e.target.value })} />
              </div>
              <div className="form-group"><label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="active">有効</option>
                  <option value="discontinued">廃盤</option>
                </select>
              </div>
              <div className="form-group"><label>備考</label>
                <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">{editId ? "更新" : "登録"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>コード</th>
              <th>商品名</th>
              <th>カード番号</th>
              <th>レアリティ</th>
              <th>言語</th>
              <th>カテゴリ</th>
              <th>単価</th>
              <th>在庫</th>
              <th>ステータス</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id} style={p.is_archived ? { opacity: 0.5 } : undefined}>
                <td className="mono">{p.product_code || "-"}</td>
                <td>
                  {p.image_url && <img src={p.image_url} alt="" style={{ width: 24, height: 24, marginRight: 4, objectFit: "cover", verticalAlign: "middle", borderRadius: 2 }} />}
                  {p.name_ja}
                  {p.is_archived && <span className="badge badge-lost" style={{ marginLeft: 6 }}>廃番</span>}
                </td>
                <td className="mono">{p.card_number || "-"}</td>
                <td>{p.rarity || "-"}</td>
                <td>{p.language || "-"}</td>
                <td>{p.category || "-"}</td>
                <td>
                  {p.unit_price != null ? `¥${p.unit_price.toLocaleString()}` : "-"}
                  {(p.unit_price_usd != null || p.unit_price_eur != null) && (
                    <span style={{ display: "block", fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                      {p.unit_price_usd != null ? `$${p.unit_price_usd}` : ""}
                      {p.unit_price_usd != null && p.unit_price_eur != null ? " / " : ""}
                      {p.unit_price_eur != null ? `€${p.unit_price_eur}` : ""}
                    </span>
                  )}
                </td>
                <td>
                  <span style={{ color: p.quantity <= 0 ? "var(--danger)" : "inherit", fontWeight: p.quantity <= 0 ? 600 : 400 }}>
                    {p.quantity}
                  </span>
                </td>
                <td><span className={`badge badge-${p.status === "active" ? "won" : "lost"}`}>{p.status === "active" ? "有効" : "廃盤"}</span></td>
                <td className="actions">
                  {hasPermission("products.update") && <button className="btn-sm" onClick={() => handleEdit(p)}>編集</button>}
                  {hasPermission("products.update") && (
                    <button className="btn-sm" onClick={() => handleArchiveToggle(p)}>
                      {p.is_archived ? "復活" : "アーカイブ"}
                    </button>
                  )}
                  {hasPermission("products.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(p)}>削除</button>}
                </td>
              </tr>
            ))}
            {products.length === 0 && <tr><td colSpan={10} className="empty">商品が登録されていません</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="商品を削除"
        message={<><strong>{deleteTarget?.name_ja}</strong> を削除します。<br />見積もり・請求書・仕入注文で参照されている場合は削除できません（アーカイブ推奨）。</>}
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      <ConfirmModal
        open={!!archiveBlocked}
        title="削除できません"
        message={
          <>
            <strong>{archiveBlocked?.name_ja}</strong> は下流テーブルから参照されています:
            {archiveBlocked && archiveBlocked.blocking_references.length > 0 ? (
              <ul>{archiveBlocked.blocking_references.map((r) => <li key={r}>{r}</li>)}</ul>
            ) : (
              <p style={{ color: "var(--text-secondary)" }}>（参照先未特定）</p>
            )}
            物理削除の代わりに <strong>アーカイブ</strong>（is_archived=true）を実行しますか？
            <br />
            アーカイブすると一覧から非表示になりますが、過去の参照は維持されます。
          </>
        }
        confirmLabel="アーカイブする"
        onConfirm={handleArchiveFromBlocked}
        onCancel={() => setArchiveBlocked(null)}
      />
    </div>
  );
}

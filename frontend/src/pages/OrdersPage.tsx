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
 */

import { useEffect, useMemo, useRef, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import CompanyContactSelector from "../components/CompanyContactSelector";

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

// ADR-021 第 1 節の 6 値 + 既存 DB enum との対応。
// `confirmed` は ADR-021 にない既存値だが破壊的変更を避けるため UI 上は「確認済」のままで残す。
const STATUSES = [
  "pending",
  "confirmed",
  "processing",
  "shipped",
  "delivered",
  "returned",
  "cancelled",
];
const STATUS_LABELS: Record<string, string> = {
  pending: "未処理",
  confirmed: "確認済",
  processing: "仕入中",
  shipped: "配送中",
  delivered: "完了",
  returned: "トラブル",
  cancelled: "キャンセル",
};

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "updated_at", label: "更新日時" },
  { value: "created_at", label: "登録日時" },
  { value: "total_amount", label: "金額" },
  { value: "status", label: "ステータス" },
];

const emptyForm = {
  deal_id: "",
  order_number: "",
  total_amount: "",
  status: "pending",
  notes: "",
};

export default function OrdersPage() {
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
      setError(e instanceof Error ? e.message : "取得に失敗しました");
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
      setSelectorError("会社と担当者を選択してください");
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
      setError(e instanceof Error ? e.message : "保存に失敗しました");
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
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const fmt = (n: number) =>
    n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });

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
        <h2>受注管理</h2>
        <button
          className="btn-primary"
          onClick={() => {
            setShowForm(true);
            setEditId(null);
            setForm(emptyForm);
            resetSelector();
          }}
        >
          新規登録
        </button>
      </div>

      {/* グループ件数バッジ（ADR-021 AC-1.6）。
          search 連動 / status fitler 非連動で全体ステータス分布を見せる。 */}
      <div
        className="orders-group-counts"
        role="group"
        aria-label="ステータス別件数"
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
          全件 {groupCounts ? `(${groupCounts.total})` : ""}
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
          aria-label="受注検索"
          placeholder="受注番号 / 会社名 / 担当者名で検索"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ flex: "1 1 240px", minWidth: 200 }}
          data-testid="orders-search-input"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="ステータスフィルタ"
          data-testid="orders-status-filter"
        >
          <option value="">全ステータス</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          aria-label="ソート対象"
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
          aria-label={`ソート順切替（現在: ${sortOrder === "desc" ? "降順" : "昇順"}）`}
          data-testid="orders-sort-order"
        >
          {sortOrder === "desc" ? "降順 ↓" : "昇順 ↑"}
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "受注編集" : "新規受注登録"}</h3>
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
                  ※ 受注の会社・担当者は作成後変更できません
                </p>
              )}
              <div className="form-group">
                <label>受注番号 *</label>
                <input
                  required
                  value={form.order_number}
                  onChange={(e) =>
                    setForm({ ...form, order_number: e.target.value })
                  }
                />
              </div>
              <div className="form-group">
                <label>合計金額</label>
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
                <label>ステータス</label>
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
                <label>備考</label>
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
                  キャンセル
                </button>
                <button type="submit" className="btn-primary">
                  {editId ? "更新" : "登録"}
                </button>
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
              <th>受注番号</th>
              <th>会社</th>
              <th>担当者</th>
              <th>合計金額</th>
              <th>ステータス</th>
              <th>登録日</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.order_number}</td>
                <td>{companyDisplay(o)}</td>
                <td>{o.contact_display_name ?? "-"}</td>
                <td>{o.total_amount ? fmt(o.total_amount) : "-"}</td>
                <td>
                  <span className={`badge badge-${o.status}`}>
                    {STATUS_LABELS[o.status] || o.status}
                  </span>
                </td>
                <td>{new Date(o.created_at).toLocaleDateString("ja-JP")}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => handleEdit(o)}>
                    編集
                  </button>
                  <button
                    className="btn-sm btn-danger"
                    onClick={() => setDeleteTarget(o)}
                  >
                    削除
                  </button>
                </td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  受注が登録されていません
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="受注を削除"
        message={
          <>
            受注番号 <strong>{deleteTarget?.order_number}</strong> を削除します。
            <br />
            この操作は取り消せません。
          </>
        }
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

/**
 * /super-admin/masters — TCG シリーズマスタタブ。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.3:
 *   - public.tcg_series_master 直接 CRUD
 *   - tcg_type で一覧フィルタ
 *
 * ADR-083 (2026-05-30):
 *   - 種別 (tcg_type) を固定リストから public.tcg_type_master ベースへ移行。
 *     種別自体を UI から増減できる「種別の管理」セクションを追加。
 *   - 種別の表示名は master の name_ja を用いる（旧 i18n 固定ラベルは廃止）。
 *   - 旧実装はフロントが "pokemon" を送る一方 DB は "pokemon_booster_box" を要求し
 *     不整合だった。master の code を正本にすることで是正。
 */
import { useEffect, useState, FormEvent, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";

interface TcgSeries {
  id: number;
  tcg_type: string;
  series_code: string;
  name_ja: string;
  name_en: string | null;
  release_date: string | null;
  category: string | null;
}

interface TcgType {
  id: number;
  code: string;
  name_ja: string;
  name_en: string | null;
  sort_order: number;
  is_active: boolean;
}

const emptySeries = {
  tcg_type: "",
  series_code: "",
  name_ja: "",
  name_en: "",
  release_date: "",
  category: "",
};

const emptyType = { code: "", name_ja: "", name_en: "" };

export default function TcgSeriesTab() {
  const { t } = useTranslation();
  const [types, setTypes] = useState<TcgType[]>([]);
  const [items, setItems] = useState<TcgSeries[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [form, setForm] = useState(emptySeries);
  const [editId, setEditId] = useState<number | null>(null);
  const [typeForm, setTypeForm] = useState(emptyType);
  const [showTypeManager, setShowTypeManager] = useState(false);
  const [error, setError] = useState("");

  const typeByCode = useMemo(() => {
    const m = new Map<string, TcgType>();
    types.forEach((tp) => m.set(tp.code, tp));
    return m;
  }, [types]);

  const typeLabel = (code: string) => typeByCode.get(code)?.name_ja ?? code;

  const loadTypes = async () => {
    try {
      const data = await api.get<TcgType[]>("/super-admin/tcg/types");
      setTypes(data);
      // 初期フィルタ / フォーム種別を先頭種別に補完
      setFilter((prev) => prev || data[0]?.code || "");
      setForm((f) => (f.tcg_type ? f : { ...f, tcg_type: data[0]?.code || "" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  const load = async (tcgType: string) => {
    try {
      const q = tcgType ? `?tcg_type=${encodeURIComponent(tcgType)}` : "";
      const data = await api.get<TcgSeries[]>(`/super-admin/tcg/series${q}`);
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  useEffect(() => {
    void loadTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (filter) void load(filter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const payload = {
      ...form,
      release_date: form.release_date || null,
      name_en: form.name_en || null,
      category: form.category || null,
    };
    try {
      if (editId) {
        await api.patch(`/super-admin/tcg/series/${editId}`, payload);
      } else {
        await api.post("/super-admin/tcg/series", payload);
      }
      setEditId(null);
      setForm({ ...emptySeries, tcg_type: filter });
      await load(filter);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  const startEdit = (s: TcgSeries) => {
    setEditId(s.id);
    setForm({
      tcg_type: s.tcg_type,
      series_code: s.series_code,
      name_ja: s.name_ja,
      name_en: s.name_en || "",
      release_date: s.release_date || "",
      category: s.category || "",
    });
  };

  const remove = async (id: number) => {
    try {
      await api.delete(`/super-admin/tcg/series/${id}`);
      await load(filter);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  // --- 種別の管理 (ADR-083) ---
  const submitType = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api.post("/super-admin/tcg/types", {
        code: typeForm.code.trim(),
        name_ja: typeForm.name_ja.trim(),
        name_en: typeForm.name_en.trim() || null,
        sort_order: 100,
        is_active: true,
      });
      setTypeForm(emptyType);
      await loadTypes();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  const removeType = async (id: number) => {
    setError("");
    try {
      await api.delete(`/super-admin/tcg/types/${id}`);
      await loadTypes();
    } catch (e) {
      // 使用中(409)などはメッセージを表示
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  return (
    <div className="super-admin-tcg-tab">
      <h3>{t("superAdmin.tcg.title")}</h3>
      {error && <div className="error-message">{error}</div>}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-3)",
          margin: "0.5rem 0",
        }}
      >
        <label>
          {t("superAdmin.tcg.fields.tcgType")}:{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            {types.map((tp) => (
              <option key={tp.code} value={tp.code}>
                {tp.name_ja}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => setShowTypeManager((v) => !v)}
        >
          {t("superAdmin.tcg.typeManager.title")}
        </button>
      </div>

      {/* ADR-083: 種別の管理 (増減) */}
      {showTypeManager && (
        <div
          className="tcg-type-manager"
          data-testid="tcg-type-manager"
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--space-3)",
            margin: "0.5rem 0",
            background: "var(--bg-subtle)",
          }}
        >
          <form
            onSubmit={submitType}
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: "var(--space-2)",
            }}
          >
            <input
              placeholder={t("superAdmin.tcg.typeManager.code")}
              value={typeForm.code}
              onChange={(e) => setTypeForm({ ...typeForm, code: e.target.value })}
              required
            />
            <input
              placeholder={t("superAdmin.tcg.fields.nameJa")}
              value={typeForm.name_ja}
              onChange={(e) =>
                setTypeForm({ ...typeForm, name_ja: e.target.value })
              }
              required
            />
            <input
              placeholder={t("superAdmin.tcg.fields.nameEn")}
              value={typeForm.name_en}
              onChange={(e) =>
                setTypeForm({ ...typeForm, name_en: e.target.value })
              }
            />
            <button type="submit" className="btn-primary">
              {t("superAdmin.tcg.typeManager.addBtn")}
            </button>
          </form>

          <ul
            style={{
              listStyle: "none",
              margin: "var(--space-3) 0 0",
              padding: 0,
              display: "flex",
              flexWrap: "wrap",
              gap: "var(--space-2)",
            }}
          >
            {types.map((tp) => (
              <li
                key={tp.id}
                data-testid={`tcg-type-${tp.code}`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "var(--space-1)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: "var(--space-1) var(--space-2)",
                  background: "var(--bg-surface)",
                }}
              >
                <span>
                  {tp.name_ja}{" "}
                  <code style={{ color: "var(--text-muted)" }}>{tp.code}</code>
                </span>
                <button
                  type="button"
                  className="btn-danger-link"
                  aria-label={`${t("common.delete")} ${tp.name_ja}`}
                  onClick={() => removeType(tp.id)}
                >
                  {t("common.delete")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form
        onSubmit={submit}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: "var(--space-2)",
          margin: "0.5rem 0",
        }}
      >
        <select
          value={form.tcg_type}
          onChange={(e) => setForm({ ...form, tcg_type: e.target.value })}
        >
          {types.map((tp) => (
            <option key={tp.code} value={tp.code}>
              {tp.name_ja}
            </option>
          ))}
        </select>
        <input
          placeholder={t("superAdmin.tcg.fields.seriesCode")}
          value={form.series_code}
          onChange={(e) => setForm({ ...form, series_code: e.target.value })}
          required
        />
        <input
          placeholder={t("superAdmin.tcg.fields.nameJa")}
          value={form.name_ja}
          onChange={(e) => setForm({ ...form, name_ja: e.target.value })}
          required
        />
        <input
          placeholder={t("superAdmin.tcg.fields.nameEn")}
          value={form.name_en}
          onChange={(e) => setForm({ ...form, name_en: e.target.value })}
        />
        <button type="submit" className="btn-primary">
          {editId ? t("common.update") : t("superAdmin.tcg.newSeries")}
        </button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>{t("superAdmin.tcg.fields.tcgType")}</th>
            <th>{t("superAdmin.tcg.fields.seriesCode")}</th>
            <th>{t("superAdmin.tcg.fields.nameJa")}</th>
            <th>{t("superAdmin.tcg.fields.nameEn")}</th>
            <th>{t("superAdmin.tcg.fields.releaseDate")}</th>
            {/* QA 2026-05-30: 編集/削除列はボタン幅だけに縮め、余った幅を名称列に回す */}
            <th style={{ width: "1%", whiteSpace: "nowrap" }}>
              {t("common.edit")}
            </th>
            <th style={{ width: "1%", whiteSpace: "nowrap" }}>
              {t("common.delete")}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.id}>
              <td>{it.id}</td>
              <td>{typeLabel(it.tcg_type)}</td>
              <td>{it.series_code}</td>
              <td>{it.name_ja}</td>
              <td>{it.name_en}</td>
              <td>{it.release_date}</td>
              <td>
                <button onClick={() => startEdit(it)} className="btn-secondary">
                  {t("common.edit")}
                </button>
              </td>
              <td>
                <button onClick={() => remove(it.id)} className="btn-danger-link">
                  {t("common.delete")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * /super-admin/masters — TCG シリーズマスタタブ。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.3:
 *   - 5 TCG タイプ (pokemon / one_piece / dragon_ball / union_arena / yugioh) を select で切替
 *   - public.tcg_series_master 直接 CRUD
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2）
 */
import { useEffect, useState, FormEvent } from "react";
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

const TCG_TYPES = ["pokemon", "one_piece", "dragon_ball", "union_arena", "yugioh"] as const;

const emptySeries = {
  tcg_type: "pokemon",
  series_code: "",
  name_ja: "",
  name_en: "",
  release_date: "",
  category: "",
};

export default function TcgSeriesTab() {
  const { t } = useTranslation();
  const [items, setItems] = useState<TcgSeries[]>([]);
  const [filter, setFilter] = useState<string>("pokemon");
  const [form, setForm] = useState(emptySeries);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = async (tcgType?: string) => {
    try {
      const q = tcgType ? `?tcg_type=${encodeURIComponent(tcgType)}` : "";
      const data = await api.get<TcgSeries[]>(`/super-admin/tcg/series${q}`);
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  useEffect(() => {
    load(filter);
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

  return (
    <div className="super-admin-tcg-tab">
      <h3>{t("superAdmin.tcg.title")}</h3>
      {error && <div className="error-message">{error}</div>}
      <div style={{ margin: "0.5rem 0" }}>
        <label>
          {t("superAdmin.tcg.fields.tcgType")}:{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            {TCG_TYPES.map((tt) => (
              <option key={tt} value={tt}>
                {t(`superAdmin.tcg.types.${tt}`)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <form
        onSubmit={submit}
        style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "var(--space-2)", margin: "0.5rem 0" }}
      >
        <select
          value={form.tcg_type}
          onChange={(e) => setForm({ ...form, tcg_type: e.target.value })}
        >
          {TCG_TYPES.map((tt) => (
            <option key={tt} value={tt}>
              {t(`superAdmin.tcg.types.${tt}`)}
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
            <th>{t("common.edit")}</th>
            <th>{t("common.delete")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.id}>
              <td>{it.id}</td>
              <td>{t(`superAdmin.tcg.types.${it.tcg_type}`, it.tcg_type)}</td>
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

/**
 * /super-admin/masters — Pokemon / Trainer 図鑑タブ。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.4:
 *   - kind=pokemon / trainer で切替
 *   - dex_number, name_ja, name_en の編集
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2）
 */
import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";

type DexKind = "pokemon" | "trainer";

interface DexEntry {
  id: number;
  dex_number: number;
  name_ja: string;
  name_en: string | null;
  generation?: number | null;
  region?: string | null;
  era?: string | null;
}

export default function DexTab() {
  const { t } = useTranslation();
  const [kind, setKind] = useState<DexKind>("pokemon");
  const [items, setItems] = useState<DexEntry[]>([]);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<DexEntry | null>(null);
  const [editValues, setEditValues] = useState<Partial<DexEntry>>({});
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const q = search ? `?q=${encodeURIComponent(search)}` : "";
      const data = await api.get<DexEntry[]>(`/super-admin/dex/${kind}${q}`);
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const startEdit = (e: DexEntry) => {
    setEditing(e);
    setEditValues({
      dex_number: e.dex_number,
      name_ja: e.name_ja,
      name_en: e.name_en || "",
      generation: e.generation ?? null,
      region: e.region || "",
      era: e.era || "",
    });
  };

  const saveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setError("");
    try {
      await api.patch(`/super-admin/dex/${kind}/${editing.id}`, editValues);
      setEditing(null);
      setEditValues({});
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  return (
    <div className="super-admin-dex-tab">
      <h3>{t("superAdmin.dex.title")}</h3>
      {error && <div className="error-message">{error}</div>}
      <div style={{ display: "flex", gap: "0.5rem", margin: "0.5rem 0" }}>
        <label>
          <select value={kind} onChange={(e) => setKind(e.target.value as DexKind)}>
            <option value="pokemon">{t("superAdmin.dex.kinds.pokemon")}</option>
            <option value="trainer">{t("superAdmin.dex.kinds.trainer")}</option>
          </select>
        </label>
        <input
          placeholder={t("common.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") load();
          }}
        />
        <button onClick={load} className="btn-secondary">
          {t("common.search")}
        </button>
      </div>

      {editing && (
        <form onSubmit={saveEdit} className="modal-inline" style={{ border: "1px solid #ccc", padding: "0.5rem", margin: "0.5rem 0" }}>
          <strong>
            #{editing.dex_number} {editing.name_ja}
          </strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.5rem", marginTop: "0.5rem" }}>
            <input
              placeholder={t("superAdmin.dex.fields.nameJa")}
              value={editValues.name_ja || ""}
              onChange={(e) => setEditValues({ ...editValues, name_ja: e.target.value })}
            />
            <input
              placeholder={t("superAdmin.dex.fields.nameEn")}
              value={(editValues.name_en as string) || ""}
              onChange={(e) => setEditValues({ ...editValues, name_en: e.target.value })}
            />
            {kind === "pokemon" ? (
              <input
                placeholder={t("superAdmin.dex.fields.region")}
                value={(editValues.region as string) || ""}
                onChange={(e) => setEditValues({ ...editValues, region: e.target.value })}
              />
            ) : (
              <input
                placeholder={t("superAdmin.dex.fields.era")}
                value={(editValues.era as string) || ""}
                onChange={(e) => setEditValues({ ...editValues, era: e.target.value })}
              />
            )}
          </div>
          <div style={{ marginTop: "0.5rem" }}>
            <button type="submit" className="btn-primary">
              {t("common.save")}
            </button>{" "}
            <button type="button" onClick={() => setEditing(null)} className="btn-secondary">
              {t("common.cancel")}
            </button>
          </div>
        </form>
      )}

      <table className="data-table">
        <thead>
          <tr>
            <th>{t("superAdmin.dex.fields.dexNumber")}</th>
            <th>{t("superAdmin.dex.fields.nameJa")}</th>
            <th>{t("superAdmin.dex.fields.nameEn")}</th>
            {kind === "pokemon" ? (
              <>
                <th>{t("superAdmin.dex.fields.generation")}</th>
                <th>{t("superAdmin.dex.fields.region")}</th>
              </>
            ) : (
              <th>{t("superAdmin.dex.fields.era")}</th>
            )}
            <th>{t("common.edit")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.id}>
              <td>{it.dex_number}</td>
              <td>{it.name_ja}</td>
              <td>{it.name_en}</td>
              {kind === "pokemon" ? (
                <>
                  <td>{it.generation}</td>
                  <td>{it.region}</td>
                </>
              ) : (
                <td>{it.era}</td>
              )}
              <td>
                <button onClick={() => startEdit(it)} className="btn-secondary">
                  {t("common.edit")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

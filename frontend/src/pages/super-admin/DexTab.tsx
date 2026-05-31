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

// ADR-084: PokeAPI 取込
interface ImportEntry {
  dex_number: number;
  name_ja: string;
  name_en: string | null;
  generation: number | null;
}

interface ImportPreview {
  source_count: number;
  db_count: number;
  added: ImportEntry[];
  added_count: number;
  truncated: boolean;
}

export default function DexTab() {
  const { t } = useTranslation();
  const [kind, setKind] = useState<DexKind>("pokemon");
  const [items, setItems] = useState<DexEntry[]>([]);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<DexEntry | null>(null);
  const [editValues, setEditValues] = useState<Partial<DexEntry>>({});
  const [error, setError] = useState("");
  // ADR-084: PokeAPI 取込
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState("");

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

  // ADR-084: PokeAPI から最新を取得し、DB に無い新規分を差分プレビュー（DB書込なし）
  const runImportPreview = async () => {
    setError("");
    setImportMsg("");
    setImporting(true);
    try {
      const data = await api.post<ImportPreview>(
        "/super-admin/dex/pokemon/import/preview",
        {},
      );
      setImportPreview(data);
      if (data.added_count === 0) {
        setImportMsg(t("superAdmin.dex.import.upToDate"));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setImporting(false);
    }
  };

  // プレビューで得た新規分のみ一括 INSERT（既存は不変）
  const runImportApply = async () => {
    if (!importPreview || importPreview.added_count === 0) return;
    setError("");
    setImporting(true);
    try {
      const res = await api.post<{ inserted_count: number }>(
        "/super-admin/dex/pokemon/import/apply",
        { entries: importPreview.added },
      );
      setImportMsg(
        t("superAdmin.dex.import.applied", { count: res.inserted_count }),
      );
      setImportPreview(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setImporting(false);
    }
  };

  const renderHead = () => (
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
  );

  const renderRow = (it: DexEntry) => (
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
  );

  // QA 2026-05-30: 図鑑は1行あたりの情報が少なく横に余白が大きいため、項目を
  // 2列(2-up)に分割して縦の長さを半減する。狭い画面では flex-wrap で1列に戻る。
  const half = Math.ceil(items.length / 2);
  const columns = [items.slice(0, half), items.slice(half)].filter(
    (c) => c.length > 0,
  );

  return (
    <div className="super-admin-dex-tab">
      <h3>{t("superAdmin.dex.title")}</h3>
      {error && <div className="error-message">{error}</div>}
      <div style={{ display: "flex", gap: "var(--space-2)", margin: "0.5rem 0" }}>
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

      {/* ADR-084: PokeAPI 取込 (ポケモン図鑑のみ) */}
      {kind === "pokemon" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-2)",
            flexWrap: "wrap",
            margin: "0.5rem 0",
          }}
        >
          <button
            type="button"
            className="btn-secondary"
            disabled={importing}
            onClick={runImportPreview}
            data-testid="dex-import-preview-btn"
          >
            {t("superAdmin.dex.import.previewBtn")}
          </button>
          {importMsg && (
            <span style={{ color: "var(--text-secondary)" }}>{importMsg}</span>
          )}
        </div>
      )}

      {importPreview && importPreview.added_count > 0 && (
        <div
          className="dex-import-preview"
          data-testid="dex-import-preview"
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--space-3)",
            margin: "0.5rem 0",
            background: "var(--bg-subtle)",
          }}
        >
          <div style={{ fontWeight: "var(--font-weight-semi)" }}>
            {t("superAdmin.dex.import.diffSummary", {
              count: importPreview.added_count,
              source: importPreview.source_count,
              db: importPreview.db_count,
            })}
          </div>
          {importPreview.truncated && (
            <div style={{ color: "var(--color-warning)" }}>
              {t("superAdmin.dex.import.truncated", { max: 500 })}
            </div>
          )}
          <ul
            style={{
              maxHeight: "12rem",
              overflowY: "auto",
              margin: "var(--space-2) 0",
              paddingLeft: "var(--space-4)",
            }}
          >
            {importPreview.added.slice(0, 100).map((e) => (
              <li key={e.dex_number}>
                #{e.dex_number} {e.name_ja}
                {e.name_en ? ` (${e.name_en})` : ""}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="btn-primary"
            disabled={importing}
            onClick={runImportApply}
            data-testid="dex-import-apply-btn"
          >
            {t("superAdmin.dex.import.applyBtn", {
              count: importPreview.added_count,
            })}
          </button>
        </div>
      )}

      {editing && (
        <form onSubmit={saveEdit} className="modal-inline" style={{ border: "1px solid var(--border-color)", padding: "var(--space-2)", margin: "0.5rem 0" }}>
          <strong>
            #{editing.dex_number} {editing.name_ja}
          </strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
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
          <div style={{ marginTop: "var(--space-2)" }}>
            <button type="submit" className="btn-primary">
              {t("common.save")}
            </button>{" "}
            <button type="button" onClick={() => setEditing(null)} className="btn-secondary">
              {t("common.cancel")}
            </button>
          </div>
        </form>
      )}

      {/* QA 2026-05-30: 図鑑は横幅に余裕があるため 2 列(2-up)表示。
          狭い画面では flex-wrap で 1 列に折り返す。 */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--space-3)",
          alignItems: "flex-start",
        }}
      >
        {columns.map((colItems, ci) => (
          <div key={ci} style={{ flex: "1 1 26rem", minWidth: 0 }}>
            <table className="data-table">
              {renderHead()}
              <tbody>{colItems.map(renderRow)}</tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * /super-admin/masters — Knowledge + Aliases タブ。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.2 / AC2.6 / AC2.7:
 *   - public.knowledge_rules CRUD（検索付き）
 *   - public.supplier_aliases CRUD（検索付き）
 *   - CSV import (dry-run → commit) / CSV export
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2）
 */
import { useEffect, useRef, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";

interface KnowledgeRule {
  id: number;
  category: string;
  pattern_type: string;
  pattern: string;
  normalized_to: string;
  priority: number;
  language: string;
  is_active: boolean;
  created_at: string;
}

interface SupplierAlias {
  id: number;
  supplier_id: number;
  alias_text: string;
  language: string;
  product_id: number | null;
  source: string | null;
}

const emptyRule = {
  category: "",
  pattern_type: "regex",
  pattern: "",
  normalized_to: "",
  priority: 100,
  language: "ja",
  is_active: true,
};

const emptyAlias = {
  supplier_id: 0,
  alias_text: "",
  language: "ja",
  product_id: null as number | null,
  source: "manual",
};

export default function KnowledgeAliasesTab() {
  const { t } = useTranslation();
  // ---- Rules ----
  const [rules, setRules] = useState<KnowledgeRule[]>([]);
  const [ruleForm, setRuleForm] = useState(emptyRule);
  const [ruleSearch, setRuleSearch] = useState("");
  const [ruleError, setRuleError] = useState("");
  const [ruleCsvMsg, setRuleCsvMsg] = useState<string>("");
  const csvInputRef = useRef<HTMLInputElement>(null);

  // ---- Aliases ----
  const [aliases, setAliases] = useState<SupplierAlias[]>([]);
  const [aliasForm, setAliasForm] = useState(emptyAlias);
  const [aliasSearch, setAliasSearch] = useState("");
  const [aliasError, setAliasError] = useState("");

  // ---- 仕入先別 Gemini プロンプト (ADR-085) ----
  const [suppliers, setSuppliers] = useState<{ id: number; name: string }[]>([]);
  const [promptSupplierId, setPromptSupplierId] = useState<number | null>(null);
  const [promptText, setPromptText] = useState("");
  const [promptActive, setPromptActive] = useState(true);
  const [promptMsg, setPromptMsg] = useState("");
  const [promptError, setPromptError] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);

  const loadSuppliers = async () => {
    try {
      const data = await api.get<{ id: number; name: string }[]>(
        "/super-admin/suppliers?per_page=500",
      );
      setSuppliers(data);
    } catch (e) {
      setPromptError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  const loadPrompt = async (supplierId: number) => {
    setPromptError("");
    setPromptMsg("");
    try {
      const data = await api.get<{ prompt: string; is_active: boolean }>(
        `/super-admin/suppliers/${supplierId}/prompt`,
      );
      setPromptText(data.prompt);
      setPromptActive(data.is_active);
    } catch (e) {
      setPromptError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  const savePrompt = async () => {
    if (promptSupplierId === null) return;
    setPromptError("");
    setPromptMsg("");
    setPromptSaving(true);
    try {
      await api.put(`/super-admin/suppliers/${promptSupplierId}/prompt`, {
        prompt: promptText,
        is_active: promptActive,
      });
      setPromptMsg(t("common.saved"));
    } catch (e) {
      setPromptError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setPromptSaving(false);
    }
  };

  const loadRules = async (q?: string) => {
    try {
      const data = await api.get<KnowledgeRule[]>(
        `/super-admin/knowledge${q ? `?q=${encodeURIComponent(q)}` : ""}`,
      );
      setRules(data);
    } catch (e) {
      setRuleError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  const loadAliases = async (q?: string) => {
    try {
      const data = await api.get<SupplierAlias[]>(
        `/super-admin/aliases${q ? `?q=${encodeURIComponent(q)}` : ""}`,
      );
      setAliases(data);
    } catch (e) {
      setAliasError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  useEffect(() => {
    loadRules();
    loadAliases();
    loadSuppliers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createRule = async (e: FormEvent) => {
    e.preventDefault();
    setRuleError("");
    try {
      await api.post("/super-admin/knowledge", ruleForm);
      setRuleForm(emptyRule);
      await loadRules(ruleSearch);
    } catch (err) {
      setRuleError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  const deleteRule = async (id: number) => {
    try {
      await api.delete(`/super-admin/knowledge/${id}`);
      await loadRules(ruleSearch);
    } catch (e) {
      setRuleError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const createAlias = async (e: FormEvent) => {
    e.preventDefault();
    setAliasError("");
    try {
      await api.post("/super-admin/aliases", aliasForm);
      setAliasForm(emptyAlias);
      await loadAliases(aliasSearch);
    } catch (err) {
      setAliasError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  const deleteAlias = async (id: number) => {
    try {
      await api.delete(`/super-admin/aliases/${id}`);
      await loadAliases(aliasSearch);
    } catch (e) {
      setAliasError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const exportRulesCsv = () => {
    // ブラウザのダウンロードを発火（認証ヘッダー付きで取得 → blob → a.click）
    (async () => {
      try {
        const blob = await api.getBlob("/super-admin/knowledge/export");
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "knowledge_rules.csv";
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        setRuleError(e instanceof Error ? e.message : t("common.fetchError"));
      }
    })();
  };

  const importRulesCsv = async (file: File, dryRun: boolean) => {
    setRuleCsvMsg("");
    setRuleError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api.postForm<{
        dry_run: boolean;
        would_insert?: number;
        inserted?: number;
        preview?: unknown[];
      }>(`/super-admin/knowledge/import?dry_run=${dryRun}`, form);
      if (data.dry_run) {
        setRuleCsvMsg(
          `${t("superAdmin.knowledge.previewWouldInsert")}: ${data.would_insert ?? 0}`,
        );
      } else {
        setRuleCsvMsg(
          `${t("superAdmin.knowledge.csvCommit")} ${data.inserted ?? 0}`,
        );
        await loadRules(ruleSearch);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("common.saveError");
      setRuleError(`${t("superAdmin.knowledge.csvErrors")}: ${msg}`);
    }
  };

  return (
    <div className="super-admin-knowledge-tab">
      {/* ============ 仕入先別 Gemini プロンプト (ADR-085) ============ */}
      <section style={{ marginBottom: "var(--space-8)" }}>
        <h3>{t("superAdmin.knowledge.promptSection")}</h3>
        <p style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)" }}>
          {t("superAdmin.knowledge.promptHelp")}
        </p>
        {promptError && <div className="error-message">{promptError}</div>}
        {/* QA 2026-05-31: 既存 e2e は button[type=submit].first() で「ルール新規作成」を
            クリックするため、ここは type=submit を使わない（先頭の submit を奪わない）。 */}
        <div style={{ margin: "0.5rem 0" }}>
          <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBottom: "var(--space-2)", flexWrap: "wrap" }}>
            <label>
              {t("superAdmin.suppliersAdmin.fields.name")}:{" "}
              <select
                value={promptSupplierId ?? ""}
                data-testid="supplier-prompt-select"
                onChange={(e) => {
                  const id = e.target.value ? Number(e.target.value) : null;
                  setPromptSupplierId(id);
                  setPromptText("");
                  setPromptMsg("");
                  if (id !== null) loadPrompt(id);
                }}
              >
                <option value="">—</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={promptActive}
                onChange={(e) => setPromptActive(e.target.checked)}
              />{" "}
              {t("superAdmin.suppliersAdmin.fields.isActive")}
            </label>
            <button
              type="button"
              className="btn-primary"
              disabled={promptSupplierId === null || promptSaving}
              onClick={savePrompt}
              data-testid="supplier-prompt-save"
            >
              {promptSaving ? t("common.saving") : t("common.save")}
            </button>
            {promptMsg && <span style={{ color: "var(--text-secondary)" }}>{promptMsg}</span>}
          </div>
          <textarea
            value={promptText}
            data-testid="supplier-prompt-textarea"
            disabled={promptSupplierId === null}
            onChange={(e) => setPromptText(e.target.value)}
            placeholder={t("superAdmin.knowledge.promptPlaceholder")}
            rows={16}
            style={{ width: "100%", fontFamily: "var(--font-mono, monospace)", fontSize: "var(--font-sm)" }}
          />
        </div>
      </section>

      {/* ============ Rules section ============ */}
      <section style={{ marginBottom: "var(--space-8)" }}>
        <h3>{t("superAdmin.knowledge.rulesSection")}</h3>
        {ruleError && <div className="error-message">{ruleError}</div>}
        <div style={{ display: "flex", gap: "var(--space-2)", margin: "0.5rem 0" }}>
          <input
            placeholder={t("common.search")}
            value={ruleSearch}
            onChange={(e) => setRuleSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") loadRules(ruleSearch);
            }}
          />
          <button onClick={() => loadRules(ruleSearch)} className="btn-secondary">
            {t("common.search")}
          </button>
          <button onClick={exportRulesCsv} className="btn-secondary">
            {t("superAdmin.knowledge.csvExport")}
          </button>
          <input
            ref={csvInputRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importRulesCsv(f, true);
              e.target.value = "";
            }}
            data-testid="csv-import-input"
          />
          <button onClick={() => csvInputRef.current?.click()} className="btn-secondary">
            {t("superAdmin.knowledge.csvImport")} ({t("superAdmin.knowledge.csvDryRun")})
          </button>
        </div>
        {ruleCsvMsg && <div className="info-message">{ruleCsvMsg}</div>}

        <form onSubmit={createRule} style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-2)", margin: "0.5rem 0" }}>
          <input
            placeholder={t("superAdmin.knowledge.fields.category")}
            value={ruleForm.category}
            onChange={(e) => setRuleForm({ ...ruleForm, category: e.target.value })}
            required
          />
          <select
            value={ruleForm.pattern_type}
            onChange={(e) => setRuleForm({ ...ruleForm, pattern_type: e.target.value })}
          >
            <option value="regex">regex</option>
            <option value="exact">exact</option>
            <option value="prefix">prefix</option>
            <option value="suffix">suffix</option>
            <option value="contains">contains</option>
          </select>
          <input
            placeholder={t("superAdmin.knowledge.fields.pattern")}
            value={ruleForm.pattern}
            onChange={(e) => setRuleForm({ ...ruleForm, pattern: e.target.value })}
            required
          />
          <input
            placeholder={t("superAdmin.knowledge.fields.normalizedTo")}
            value={ruleForm.normalized_to}
            onChange={(e) => setRuleForm({ ...ruleForm, normalized_to: e.target.value })}
            required
          />
          <button type="submit" className="btn-primary">
            {t("superAdmin.knowledge.newRule")}
          </button>
        </form>

        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>{t("superAdmin.knowledge.fields.category")}</th>
              <th>{t("superAdmin.knowledge.fields.patternType")}</th>
              <th>{t("superAdmin.knowledge.fields.pattern")}</th>
              <th>{t("superAdmin.knowledge.fields.normalizedTo")}</th>
              <th>{t("superAdmin.knowledge.fields.priority")}</th>
              <th>{t("superAdmin.knowledge.fields.language")}</th>
              <th>{t("common.delete")}</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.category}</td>
                <td>{r.pattern_type}</td>
                <td><code>{r.pattern}</code></td>
                <td><code>{r.normalized_to}</code></td>
                <td>{r.priority}</td>
                <td>{r.language}</td>
                <td>
                  <button onClick={() => deleteRule(r.id)} className="btn-danger-link">
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* ============ Aliases section ============ */}
      <section>
        <h3>{t("superAdmin.knowledge.aliasesSection")}</h3>
        {aliasError && <div className="error-message">{aliasError}</div>}
        <div style={{ display: "flex", gap: "var(--space-2)", margin: "0.5rem 0" }}>
          <input
            placeholder={t("common.search")}
            value={aliasSearch}
            onChange={(e) => setAliasSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") loadAliases(aliasSearch);
            }}
          />
          <button onClick={() => loadAliases(aliasSearch)} className="btn-secondary">
            {t("common.search")}
          </button>
        </div>

        <form onSubmit={createAlias} style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-2)", margin: "0.5rem 0" }}>
          <input
            type="number"
            placeholder={t("superAdmin.knowledge.fields.supplierId")}
            value={aliasForm.supplier_id || ""}
            onChange={(e) => setAliasForm({ ...aliasForm, supplier_id: Number(e.target.value) })}
            required
          />
          <input
            placeholder={t("superAdmin.knowledge.fields.aliasText")}
            value={aliasForm.alias_text}
            onChange={(e) => setAliasForm({ ...aliasForm, alias_text: e.target.value })}
            required
          />
          <select
            value={aliasForm.language}
            onChange={(e) => setAliasForm({ ...aliasForm, language: e.target.value })}
          >
            <option value="ja">ja</option>
            <option value="en">en</option>
            <option value="ko">ko</option>
            <option value="zh">zh</option>
          </select>
          <button type="submit" className="btn-primary">
            {t("superAdmin.knowledge.newAlias")}
          </button>
        </form>

        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>{t("superAdmin.knowledge.fields.supplierId")}</th>
              <th>{t("superAdmin.knowledge.fields.aliasText")}</th>
              <th>{t("superAdmin.knowledge.fields.language")}</th>
              <th>{t("common.delete")}</th>
            </tr>
          </thead>
          <tbody>
            {aliases.map((a) => (
              <tr key={a.id}>
                <td>{a.id}</td>
                <td>{a.supplier_id}</td>
                <td>{a.alias_text}</td>
                <td>{a.language}</td>
                <td>
                  <button onClick={() => deleteAlias(a.id)} className="btn-danger-link">
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

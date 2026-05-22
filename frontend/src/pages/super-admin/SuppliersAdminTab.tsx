/**
 * /super-admin/masters — 仕入元（中央 admin、public.suppliers）+ Discord routing タブ。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.5:
 *   - supplier_type (individual / corporate) 切替
 *   - default_language 切替
 *   - 各 supplier に Discord guild_id / channel_id 紐付け
 *
 * 注意: 既存 /suppliers（テナント側 SuppliersPage）はそのまま温存。
 *       本タブは public.suppliers 側を扱う中央 admin 専用。
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2）
 */
import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { STATUS_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";

interface CentralSupplier {
  id: number;
  supplier_code: string | null;
  name: string;
  supplier_type: "individual" | "corporate";
  default_language: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  notes: string | null;
  is_active: boolean;
}

interface DiscordRouting {
  id: number;
  supplier_id: number;
  discord_guild_id: string;
  discord_channel_id: string;
  is_active: boolean;
}

type SupplierFormState = {
  name: string;
  supplier_type: "individual" | "corporate";
  default_language: string;
  contact_name: string;
  email: string;
  phone: string;
  address: string;
  notes: string;
  is_active: boolean;
};

const emptyForm: SupplierFormState = {
  name: "",
  supplier_type: "corporate",
  default_language: "ja",
  contact_name: "",
  email: "",
  phone: "",
  address: "",
  notes: "",
  is_active: true,
};

export default function SuppliersAdminTab() {
  const { t } = useTranslation();
  const [items, setItems] = useState<CentralSupplier[]>([]);
  const [form, setForm] = useState<SupplierFormState>(emptyForm);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState("");

  // routing 編集
  const [routingFor, setRoutingFor] = useState<CentralSupplier | null>(null);
  const [routings, setRoutings] = useState<DiscordRouting[]>([]);
  const [routingForm, setRoutingForm] = useState({
    discord_guild_id: "",
    discord_channel_id: "",
    is_active: true,
  });

  const load = async () => {
    try {
      const data = await api.get<CentralSupplier[]>("/super-admin/suppliers");
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  useEffect(() => {
    load();
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const toNull = (v: string) => v || null;
    const payload = {
      ...form,
      contact_name: toNull(form.contact_name),
      email: toNull(form.email),
      phone: toNull(form.phone),
      address: toNull(form.address),
      notes: toNull(form.notes),
    };
    try {
      if (editId) {
        await api.patch(`/super-admin/suppliers/${editId}`, payload);
      } else {
        await api.post("/super-admin/suppliers", payload);
      }
      setForm(emptyForm);
      setEditId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  const startEdit = (s: CentralSupplier) => {
    setEditId(s.id);
    setForm({
      name: s.name,
      supplier_type: s.supplier_type,
      default_language: s.default_language,
      contact_name: s.contact_name || "",
      email: s.email || "",
      phone: s.phone || "",
      address: s.address || "",
      notes: s.notes || "",
      is_active: s.is_active,
    });
  };

  const remove = async (s: CentralSupplier) => {
    try {
      await api.delete(`/super-admin/suppliers/${s.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const openRouting = async (s: CentralSupplier) => {
    setRoutingFor(s);
    try {
      const data = await api.get<DiscordRouting[]>(
        `/super-admin/suppliers/${s.id}/discord-routing`,
      );
      setRoutings(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  const addRouting = async (e: FormEvent) => {
    e.preventDefault();
    if (!routingFor) return;
    try {
      await api.post(`/super-admin/suppliers/${routingFor.id}/discord-routing`, {
        supplier_id: routingFor.id,
        ...routingForm,
      });
      setRoutingForm({ discord_guild_id: "", discord_channel_id: "", is_active: true });
      const refreshed = await api.get<DiscordRouting[]>(
        `/super-admin/suppliers/${routingFor.id}/discord-routing`,
      );
      setRoutings(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };

  const deleteRouting = async (id: number) => {
    if (!routingFor) return;
    try {
      await api.delete(`/super-admin/suppliers/discord-routing/${id}`);
      const refreshed = await api.get<DiscordRouting[]>(
        `/super-admin/suppliers/${routingFor.id}/discord-routing`,
      );
      setRoutings(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
    }
  };

  return (
    <div className="super-admin-suppliers-tab">
      <h3>{t("superAdmin.suppliersAdmin.title")}</h3>
      {error && <div className="error-message">{error}</div>}

      <form
        onSubmit={submit}
        style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-2)", margin: "0.5rem 0" }}
      >
        <input
          placeholder={t("superAdmin.suppliersAdmin.fields.name")}
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <select
          value={form.supplier_type}
          onChange={(e) =>
            setForm({ ...form, supplier_type: e.target.value as "individual" | "corporate" })
          }
        >
          <option value="corporate">{t("superAdmin.suppliersAdmin.types.corporate")}</option>
          <option value="individual">{t("superAdmin.suppliersAdmin.types.individual")}</option>
        </select>
        <select
          value={form.default_language}
          onChange={(e) => setForm({ ...form, default_language: e.target.value })}
        >
          <option value="ja">ja</option>
          <option value="en">en</option>
          <option value="ko">ko</option>
          <option value="zh">zh</option>
        </select>
        <button type="submit" className="btn-primary">
          {editId ? t("common.update") : t("superAdmin.suppliersAdmin.newSupplier")}
        </button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>{t("superAdmin.suppliersAdmin.fields.name")}</th>
            <th>{t("superAdmin.suppliersAdmin.fields.supplierType")}</th>
            <th>{t("superAdmin.suppliersAdmin.fields.defaultLanguage")}</th>
            <th>{t("superAdmin.suppliersAdmin.fields.isActive")}</th>
            <th>{t("common.edit")}</th>
            <th>{t("superAdmin.suppliersAdmin.discordRouting")}</th>
            <th>{t("common.delete")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id}>
              <td>{s.id}</td>
              <td>{s.name}</td>
              <td>{t(`superAdmin.suppliersAdmin.types.${s.supplier_type}`)}</td>
              <td>{s.default_language}</td>
              <td>{s.is_active ? <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" /> : "—"}</td>
              <td>
                <button onClick={() => startEdit(s)} className="btn-secondary">
                  {t("common.edit")}
                </button>
              </td>
              <td>
                <button onClick={() => openRouting(s)} className="btn-secondary">
                  {t("superAdmin.suppliersAdmin.discordRouting")}
                </button>
              </td>
              <td>
                <button onClick={() => remove(s)} className="btn-danger-link">
                  {t("common.delete")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {routingFor && (
        <div
          className="modal-overlay"
          onClick={() => setRoutingFor(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}
        >
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--bg-surface)", padding: "var(--space-4)", borderRadius: "var(--radius-lg)", minWidth: "600px", maxWidth: "90%" }}
          >
            <h4>
              {t("superAdmin.suppliersAdmin.discordRouting")} — {routingFor.name}
            </h4>
            <form
              onSubmit={addRouting}
              style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-2)", margin: "0.5rem 0" }}
            >
              <input
                placeholder={t("superAdmin.suppliersAdmin.guildId")}
                value={routingForm.discord_guild_id}
                onChange={(e) =>
                  setRoutingForm({ ...routingForm, discord_guild_id: e.target.value })
                }
                required
              />
              <input
                placeholder={t("superAdmin.suppliersAdmin.channelId")}
                value={routingForm.discord_channel_id}
                onChange={(e) =>
                  setRoutingForm({ ...routingForm, discord_channel_id: e.target.value })
                }
                required
              />
              <button type="submit" className="btn-primary">
                {t("superAdmin.suppliersAdmin.addRouting")}
              </button>
            </form>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t("superAdmin.suppliersAdmin.guildId")}</th>
                  <th>{t("superAdmin.suppliersAdmin.channelId")}</th>
                  <th>{t("superAdmin.suppliersAdmin.fields.isActive")}</th>
                  <th>{t("common.delete")}</th>
                </tr>
              </thead>
              <tbody>
                {routings.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>
                      <code>{r.discord_guild_id}</code>
                    </td>
                    <td>
                      <code>{r.discord_channel_id}</code>
                    </td>
                    <td>{r.is_active ? <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" /> : "—"}</td>
                    <td>
                      <button onClick={() => deleteRouting(r.id)} className="btn-danger-link">
                        {t("common.delete")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ marginTop: "var(--space-2)", textAlign: "right" }}>
              <button onClick={() => setRoutingFor(null)} className="btn-secondary">
                {t("common.close")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

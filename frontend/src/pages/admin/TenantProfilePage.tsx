/**
 * TenantProfilePage (Sprint 8 / F8)
 *
 * 各テナント admin が PO PDF / メールの差出人情報 (会社名・住所・印鑑 URL 等) を
 * 編集する画面。
 *
 * 権限:
 *   tenant.profile.view → 閲覧
 *   tenant.profile.edit → 保存
 *
 * 関連:
 *   .claude-pipeline/spec.md F8 / AC8.7
 *   backend/app/routers/tenant_profile.py
 *   migrations/069_create_tenant_profile.sql
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { usePageTitle } from "../../hooks/usePageTitle";

interface TenantProfile {
  id: number;
  company_name: string | null;
  company_name_en: string | null;
  address: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  seal_image_url: string | null;
  default_language: string;
  created_at: string;
  updated_at: string;
}

interface FormState {
  company_name: string;
  company_name_en: string;
  address: string;
  phone: string;
  email: string;
  website: string;
  seal_image_url: string;
  default_language: string;
}

const emptyForm: FormState = {
  company_name: "",
  company_name_en: "",
  address: "",
  phone: "",
  email: "",
  website: "",
  seal_image_url: "",
  default_language: "ja",
};

export default function TenantProfilePage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const title = usePageTitle();
  const [form, setForm] = useState<FormState>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const canView = hasPermission("tenant.profile.view");
  const canEdit = hasPermission("tenant.profile.edit");

  useEffect(() => {
    let alive = true;
    const fetchProfile = async () => {
      try {
        const data = await api.get<TenantProfile>("/admin/tenant-profile");
        if (!alive) return;
        setForm({
          company_name: data.company_name ?? "",
          company_name_en: data.company_name_en ?? "",
          address: data.address ?? "",
          phone: data.phone ?? "",
          email: data.email ?? "",
          website: data.website ?? "",
          seal_image_url: data.seal_image_url ?? "",
          default_language: data.default_language ?? "ja",
        });
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : t("common.fetchError"));
      } finally {
        if (alive) setLoading(false);
      }
    };
    if (canView) fetchProfile(); else setLoading(false);
    return () => { alive = false; };
  }, [canView, t]);

  const handleChange = (key: keyof FormState) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
  ) => {
    setForm((prev) => ({ ...prev, [key]: e.target.value }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setInfo("");
    setSaving(true);
    try {
      // 空文字は null に変換 (バックエンド側で null と空文字を等価扱い)
      const payload: Record<string, string | null> = {};
      (Object.keys(form) as Array<keyof FormState>).forEach((k) => {
        const v = form[k];
        payload[k] = v === "" ? null : v;
      });
      await api.put("/admin/tenant-profile", payload);
      setInfo(t("tenantProfile.saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.operationError"));
    } finally {
      setSaving(false);
    }
  };

  if (!canView) {
    return (
      <div className="page">
        <div className="error-message">{t("tenantProfile.permissionRequired")}</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <h2>{title}</h2>
        <p className="text-muted">{t("tenantProfile.subtitle")}</p>
      </div>
      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <form className="form" onSubmit={handleSave} data-testid="tenant-profile-form">
          {error && <div className="error-message">{error}</div>}
          {info && <div className="info-message" data-testid="tenant-profile-info">{info}</div>}

          <div className="form-group">
            <label htmlFor="tp-company-name">{t("tenantProfile.companyName")}</label>
            <input
              id="tp-company-name"
              data-testid="tp-company-name"
              type="text"
              value={form.company_name}
              onChange={handleChange("company_name")}
              disabled={!canEdit}
              maxLength={255}
            />
          </div>

          <div className="form-group">
            <label htmlFor="tp-company-name-en">{t("tenantProfile.companyNameEn")}</label>
            <input
              id="tp-company-name-en"
              data-testid="tp-company-name-en"
              type="text"
              value={form.company_name_en}
              onChange={handleChange("company_name_en")}
              disabled={!canEdit}
              maxLength={255}
            />
          </div>

          <div className="form-group">
            <label htmlFor="tp-address">{t("tenantProfile.address")}</label>
            <textarea
              id="tp-address"
              data-testid="tp-address"
              value={form.address}
              onChange={handleChange("address")}
              disabled={!canEdit}
              rows={3}
            />
          </div>

          <div className="form-group">
            <label htmlFor="tp-phone">{t("tenantProfile.phone")}</label>
            <input
              id="tp-phone"
              data-testid="tp-phone"
              type="text"
              value={form.phone}
              onChange={handleChange("phone")}
              disabled={!canEdit}
              maxLength={50}
            />
          </div>

          <div className="form-group">
            <label htmlFor="tp-email">{t("tenantProfile.email")}</label>
            <input
              id="tp-email"
              data-testid="tp-email"
              type="email"
              value={form.email}
              onChange={handleChange("email")}
              disabled={!canEdit}
              maxLength={255}
            />
          </div>

          <div className="form-group">
            <label htmlFor="tp-website">{t("tenantProfile.website")}</label>
            <input
              id="tp-website"
              data-testid="tp-website"
              type="text"
              value={form.website}
              onChange={handleChange("website")}
              disabled={!canEdit}
              maxLength={255}
            />
          </div>

          <div className="form-group">
            <label htmlFor="tp-seal-url">{t("tenantProfile.sealImageUrl")}</label>
            <input
              id="tp-seal-url"
              data-testid="tp-seal-image-url"
              type="text"
              value={form.seal_image_url}
              onChange={handleChange("seal_image_url")}
              disabled={!canEdit}
              placeholder="https://..."
            />
            <small className="form-hint">{t("tenantProfile.sealHint")}</small>
          </div>

          <div className="form-group">
            <label htmlFor="tp-default-language">{t("tenantProfile.defaultLanguage")}</label>
            <select
              id="tp-default-language"
              data-testid="tp-default-language"
              value={form.default_language}
              onChange={handleChange("default_language")}
              disabled={!canEdit}
            >
              <option value="ja">{t("language.ja")} (ja)</option>
              <option value="en">English (en)</option>
              <option value="ko">한국어 (ko)</option>
              <option value="zh">{t("language.zh")} (zh)</option>
            </select>
          </div>

          {canEdit && (
            <div className="form-actions">
              <button
                type="submit"
                className="btn-primary"
                disabled={saving}
                data-testid="tenant-profile-save"
              >
                {saving ? t("common.saving") : t("common.save")}
              </button>
            </div>
          )}
        </form>
      )}
    </div>
  );
}

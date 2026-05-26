/**
 * 会社詳細ページ（Phase 1-B-2 Step 5c-2）。
 *
 * URL: /companies/:id
 * 4 タブ: 基本情報 / 住所（multi_branch）/ 担当者 / 販売チャネル
 *
 * このファイルはオーケストレーターのみ。ロジックは useCompanyDetail、
 * UI は各タブコンポーネントに分割済み。
 */

import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { usePermissions } from "../../hooks/usePermissions";
import ConfirmModal from "../../components/ConfirmModal";
import MergeCompanyModal from "../../components/MergeCompanyModal";
import { useCompanyDetail } from "./useCompanyDetail";
import { CompanyBasicTab } from "./CompanyBasicTab";
import { CompanyAddressesTab } from "./CompanyAddressesTab";
import { CompanyContactsTab } from "./CompanyContactsTab";
import { CompanyChannelsTab } from "./CompanyChannelsTab";
import { CompanyAddressModal } from "./CompanyAddressModal";
import { typeLabel } from "./company-detail.types";

export default function CompanyDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const canEdit = hasPermission("customers.update");
  // A-4: 会社マージは customers.delete 権限相当
  const canMerge = hasPermission("customers.delete");

  const state = useCompanyDetail(id);
  const {
    company, contacts, loading, error,
    activeTab, setActiveTab,
    basicForm, setBasicForm, basicDirty, setBasicDirty, basicSubmitting,
    channelsText, setChannelsText, channelsDirty, setChannelsDirty, channelsSubmitting,
    addrModalOpen, setAddrModalOpen,
    addrForm, setAddrForm,
    addrDeleteTarget, setAddrDeleteTarget,
    dedupConfirmOpen, setDedupConfirmOpen, dedupSubmitting,
    mergeModalOpen, setMergeModalOpen,
    handleBasicSubmit, handleChannelsSubmit,
    submitAddresses,
    openAddressNew, openAddressEdit,
    handleAddressTypeChange,
    handleResolveAsDistinct, handleAddressDelete,
  } = state;

  if (loading) return <div className="page-container"><p>{t("common.loading")}</p></div>;
  if (!company) {
    return (
      <div className="page-container">
        <p>{t("common.noData")}</p>
        <button onClick={() => navigate("/companies")}>{t("common.back")}</button>
      </div>
    );
  }

  const billingAddresses = company.addresses.filter((a) => a.address_type === "billing");
  const deliveryAddresses = company.addresses.filter((a) => a.address_type === "delivery");

  const switchTab = (tab: typeof activeTab) => {
    if ((basicDirty || channelsDirty) && tab !== activeTab) {
      if (!window.confirm(t("companies.unsavedChangesConfirm"))) return;
      setBasicForm(state.basicForm ? { ...state.basicForm } : null);
      setChannelsText(company.sales_channels.join(", "));
      setBasicDirty(false);
      setChannelsDirty(false);
    }
    setActiveTab(tab);
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <button className="btn-sm" onClick={() => navigate("/companies")}>&larr; {t("common.back")}</button>
          <h1>{company.name}</h1>
        </div>
        <div className="page-header-actions">
          <span className={`status-badge status-${company.status}`}>{company.status}</span>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="tabs">
        <button className={`tab ${activeTab === "basic" ? "active" : ""}`} onClick={() => switchTab("basic")}>
          {t("companies.basicInfo")}
        </button>
        <button className={`tab ${activeTab === "addresses" ? "active" : ""}`} onClick={() => switchTab("addresses")}>
          {t("companies.address")} ({company.addresses.length})
        </button>
        <button className={`tab ${activeTab === "contacts" ? "active" : ""}`} onClick={() => switchTab("contacts")}>
          {t("contacts.title")} ({contacts.length})
        </button>
        <button className={`tab ${activeTab === "channels" ? "active" : ""}`} onClick={() => switchTab("channels")}>
          {t("nav.channels")} ({company.sales_channels.length})
        </button>
      </div>

      {activeTab === "basic" && basicForm && (
        <CompanyBasicTab
          basicForm={basicForm}
          setBasicForm={setBasicForm}
          basicDirty={basicDirty}
          setBasicDirty={setBasicDirty}
          basicSubmitting={basicSubmitting}
          handleBasicSubmit={handleBasicSubmit}
          canEdit={canEdit}
          canMerge={canMerge}
          company={company}
          dedupSubmitting={dedupSubmitting}
          setDedupConfirmOpen={setDedupConfirmOpen}
          setMergeModalOpen={setMergeModalOpen}
        />
      )}

      {activeTab === "addresses" && (
        <CompanyAddressesTab
          billingAddresses={billingAddresses}
          deliveryAddresses={deliveryAddresses}
          canEdit={canEdit}
          openAddressNew={openAddressNew}
          openAddressEdit={openAddressEdit}
          setAddrDeleteTarget={setAddrDeleteTarget}
        />
      )}

      {activeTab === "contacts" && (
        <CompanyContactsTab company={company} contacts={contacts} />
      )}

      {activeTab === "channels" && (
        <CompanyChannelsTab
          company={company}
          channelsText={channelsText}
          setChannelsText={setChannelsText}
          channelsDirty={channelsDirty}
          setChannelsDirty={setChannelsDirty}
          channelsSubmitting={channelsSubmitting}
          handleChannelsSubmit={handleChannelsSubmit}
          canEdit={canEdit}
        />
      )}

      <CompanyAddressModal
        isOpen={addrModalOpen}
        onClose={() => setAddrModalOpen(false)}
        addrForm={addrForm}
        setAddrForm={setAddrForm}
        submitAddresses={submitAddresses}
        company={company}
        canEdit={canEdit}
        handleAddressTypeChange={handleAddressTypeChange}
      />

      <ConfirmModal
        open={addrDeleteTarget !== null}
        title={t("companies.deleteAddressTitle")}
        message={
          addrDeleteTarget
            // eslint-disable-next-line local/no-japanese-literal -- TODO: 文章全体を1翻訳キーに統合（ADR-027 既知負債）
            ? `${typeLabel(t, addrDeleteTarget.address_type)}${t("companies.address")}「${addrDeleteTarget.branch_name || addrDeleteTarget.name || "(無名)"}」を${t("common.delete")}しますか？`
            : ""
        }
        confirmLabel={t("common.delete")}
        onConfirm={handleAddressDelete}
        onCancel={() => setAddrDeleteTarget(null)}
      />

      {/* PR #145 Q2: 別会社として確定の確認 */}
      <ConfirmModal
        open={dedupConfirmOpen}
        title={t("companies.dedupResolveTitle")}
        message={t("companies.dedupResolveConfirmMessage", { name: company.name })}
        confirmLabel={t("companies.dedupResolveConfirmLabel")}
        onConfirm={handleResolveAsDistinct}
        onCancel={() => setDedupConfirmOpen(false)}
      />

      {/* A-4: 重複マージモーダル */}
      <MergeCompanyModal
        open={mergeModalOpen}
        source={{ id: company.id, name: company.name, company_code: company.company_code }}
        onMerged={(masterId) => {
          setMergeModalOpen(false);
          navigate(`/companies/${masterId}`);
        }}
        onCancel={() => setMergeModalOpen(false)}
      />
    </div>
  );
}

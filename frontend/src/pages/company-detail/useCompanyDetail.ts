/**
 * 会社詳細ページの状態管理フック。
 * CompanyDetailPage の全 useState / useEffect / handler を集約する。
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import type {
  Company, Contact, Tab, AddressFormState, BasicFormState, CompanyAddress,
  ContactFormState, DiscordFormState,
} from "./company-detail.types";
import {
  emptyAddress, addressFromApi, basicFromApi, emptyContact, contactFromApi,
  emptyDiscordForm, discordFromApi,
} from "./company-detail.types";

export function useCompanyDetail(id: string | undefined) {
  const { t } = useTranslation();

  const [company, setCompany] = useState<Company | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("basic");

  // 基本情報タブ
  const [basicForm, setBasicForm] = useState<BasicFormState | null>(null);
  const [basicDirty, setBasicDirty] = useState(false);
  const [basicSubmitting, setBasicSubmitting] = useState(false);

  // 販売チャネルタブ
  const [channelsText, setChannelsText] = useState("");
  const [channelsDirty, setChannelsDirty] = useState(false);
  const [channelsSubmitting, setChannelsSubmitting] = useState(false);

  // 住所モーダル
  const [addrModalOpen, setAddrModalOpen] = useState(false);
  const [addrForm, setAddrForm] = useState<AddressFormState>(emptyAddress("billing"));
  const [addrDeleteTarget, setAddrDeleteTarget] = useState<CompanyAddress | null>(null);

  // 担当者モーダル
  const [contactModalOpen, setContactModalOpen] = useState(false);
  const [contactForm, setContactForm] = useState<ContactFormState>(emptyContact());
  const [contactSubmitting, setContactSubmitting] = useState(false);
  const [contactDeleteTarget, setContactDeleteTarget] = useState<Contact | null>(null);

  // Discord タブ（ADR-089 Sprint 2）
  const [discordForm, setDiscordForm] = useState<DiscordFormState>(emptyDiscordForm());
  const [discordDirty, setDiscordDirty] = useState(false);
  const [discordSubmitting, setDiscordSubmitting] = useState(false);

  // dedup 解消
  const [dedupConfirmOpen, setDedupConfirmOpen] = useState(false);
  const [dedupSubmitting, setDedupSubmitting] = useState(false);
  const [mergeModalOpen, setMergeModalOpen] = useState(false);

  const load = async () => {
    if (!id) return;
    try {
      const c = await api.get<Company>(`/companies/${id}`);
      setCompany(c);
      setBasicForm(basicFromApi(c));
      setChannelsText(c.sales_channels.join(", "));
      setBasicDirty(false);
      setChannelsDirty(false);
      setDiscordForm(c.discord ? discordFromApi(c.discord) : emptyDiscordForm());
      setDiscordDirty(false);
      const list = await api.get<Contact[]>(`/companies/${id}/contacts`);
      setContacts(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [id]);

  const handleBasicSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!basicForm || !company) return;
    setError("");
    setBasicSubmitting(true);
    try {
      const toNull = (v: string) => (v ? v : null);
      const payload: Record<string, unknown> = {
        name: basicForm.name.trim(),
        name_en: toNull(basicForm.name_en),
        industry: toNull(basicForm.industry),
        website: toNull(basicForm.website),
        trust_level: basicForm.trust_level ? parseInt(basicForm.trust_level, 10) : null,
        priority_focus: toNull(basicForm.priority_focus),
        per_order_amount: basicForm.per_order_amount || null,
        monthly_frequency: basicForm.monthly_frequency ? parseInt(basicForm.monthly_frequency, 10) : null,
        monthly_forecast: basicForm.monthly_forecast || null,
        billing_display_name: toNull(basicForm.billing_display_name),
        payment_recipient_name: toNull(basicForm.payment_recipient_name),
        fedex_account: toNull(basicForm.fedex_account),
        shipping_note: toNull(basicForm.shipping_note),
        status: basicForm.status || "active",
        notes: toNull(basicForm.notes),
      };
      await api.patch(`/companies/${company.id}`, payload);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setBasicSubmitting(false);
    }
  };

  const handleChannelsSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!company) return;
    setError("");
    setChannelsSubmitting(true);
    try {
      const list = channelsText
        .split(/[,、，]/)
        .map((s) => s.trim())
        .filter(Boolean);
      await api.patch(`/companies/${company.id}`, { sales_channels: list });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setChannelsSubmitting(false);
    }
  };

  const handleDiscordSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!company) return;
    setError("");
    setDiscordSubmitting(true);
    try {
      const toNull = (v: string) => (v.trim() ? v.trim() : null);
      const discord = {
        is_joined: discordForm.is_joined,
        channel_id: toNull(discordForm.channel_id),
        user_id: toNull(discordForm.user_id),
        invoice_webhook: toNull(discordForm.invoice_webhook),
        shipment_webhook: toNull(discordForm.shipment_webhook),
      };
      await api.patch(`/companies/${company.id}`, { discord });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setDiscordSubmitting(false);
    }
  };

  const handleDiscordDelete = async () => {
    if (!company) return;
    setError("");
    try {
      await api.patch(`/companies/${company.id}`, { discord: null });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
    }
  };

  const submitAddresses = async (next: AddressFormState[]) => {
    if (!company) return;
    const toNull = (v: string) => (v ? v : null);
    const seen: Record<string, boolean> = { billing: false, delivery: false };
    const payload = next.map((a) => {
      const isDefault = a.is_default && !seen[a.address_type];
      if (isDefault) seen[a.address_type] = true;
      return {
        address_type: a.address_type,
        branch_name: toNull(a.branch_name),
        name: toNull(a.name),
        email: toNull(a.email),
        telephone: toNull(a.telephone),
        tax_id: toNull(a.tax_id),
        address_line_1: toNull(a.address_line_1),
        address_line_2: toNull(a.address_line_2),
        address_line_3: toNull(a.address_line_3),
        city: toNull(a.city),
        state: toNull(a.state),
        zip: toNull(a.zip),
        country_code: toNull(a.country_code),
        is_default: isDefault,
      };
    });
    await api.patch(`/companies/${company.id}`, { addresses: payload });
    await load();
  };

  const hasOtherDefault = (type: "billing" | "delivery", excludeId: number | null): boolean =>
    (company?.addresses || []).some(
      (a) => a.address_type === type && a.is_default && a.id !== excludeId,
    );

  const openAddressNew = (type: "billing" | "delivery") => {
    setAddrForm({ ...emptyAddress(type), is_default: !hasOtherDefault(type, null) });
    setAddrModalOpen(true);
  };

  const openAddressEdit = (a: CompanyAddress) => {
    setAddrForm(addressFromApi(a));
    setAddrModalOpen(true);
  };

  const handleAddressTypeChange = (newType: "billing" | "delivery") => {
    setAddrForm({
      ...addrForm,
      address_type: newType,
      is_default: !hasOtherDefault(newType, addrForm.id),
    });
  };

  const handleResolveAsDistinct = async () => {
    if (!company) return;
    setError("");
    setDedupSubmitting(true);
    try {
      await api.patch(`/companies/${company.id}`, { status: "active" });
      setDedupConfirmOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.operationError"));
      setDedupConfirmOpen(false);
    } finally {
      setDedupSubmitting(false);
    }
  };

  const openContactNew = () => {
    setContactForm(emptyContact());
    setContactModalOpen(true);
  };

  const openContactEdit = (c: Contact) => {
    setContactForm(contactFromApi(c));
    setContactModalOpen(true);
  };

  const handleContactSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!company) return;
    setError("");
    setContactSubmitting(true);
    try {
      const toNull = (v: string) => (v.trim() ? v.trim() : null);
      const payload = {
        company_id: company.id,
        display_name: toNull(contactForm.display_name),
        surname: toNull(contactForm.surname),
        given_name: toNull(contactForm.given_name),
        job_title: toNull(contactForm.job_title),
        department: toNull(contactForm.department),
        is_primary_contact: contactForm.is_primary_contact,
        primary_email: toNull(contactForm.primary_email),
        primary_phone: toNull(contactForm.primary_phone),
        status: contactForm.status || "active",
      };
      if (contactForm.id === null) {
        await api.post("/contacts", payload);
      } else {
        await api.patch(`/contacts/${contactForm.id}`, payload);
      }
      setContactModalOpen(false);
      const list = await api.get<Contact[]>(`/companies/${company.id}/contacts`);
      setContacts(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setContactSubmitting(false);
    }
  };

  const handleContactDelete = async () => {
    if (!company || !contactDeleteTarget) return;
    try {
      await api.delete(`/contacts/${contactDeleteTarget.id}`);
      setContactDeleteTarget(null);
      const list = await api.get<Contact[]>(`/companies/${company.id}/contacts`);
      setContacts(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
      setContactDeleteTarget(null);
    }
  };

  const handleAddressDelete = async () => {
    if (!company || !addrDeleteTarget) return;
    try {
      const next = (company.addresses || [])
        .filter((a) => a.id !== addrDeleteTarget.id)
        .map(addressFromApi);
      await submitAddresses(next);
      setAddrDeleteTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
      setAddrDeleteTarget(null);
    }
  };

  return {
    company, contacts, loading, error, setError,
    activeTab, setActiveTab,
    basicForm, setBasicForm, basicDirty, setBasicDirty, basicSubmitting,
    channelsText, setChannelsText, channelsDirty, setChannelsDirty, channelsSubmitting,
    addrModalOpen, setAddrModalOpen,
    addrForm, setAddrForm,
    addrDeleteTarget, setAddrDeleteTarget,
    contactModalOpen, setContactModalOpen,
    contactForm, setContactForm, contactSubmitting,
    contactDeleteTarget, setContactDeleteTarget,
    discordForm, setDiscordForm, discordDirty, setDiscordDirty, discordSubmitting,
    dedupConfirmOpen, setDedupConfirmOpen, dedupSubmitting,
    mergeModalOpen, setMergeModalOpen,
    load,
    handleBasicSubmit, handleChannelsSubmit,
    submitAddresses, hasOtherDefault,
    openAddressNew, openAddressEdit,
    handleAddressTypeChange,
    openContactNew, openContactEdit,
    handleContactSubmit, handleContactDelete,
    handleDiscordSubmit, handleDiscordDelete,
    handleResolveAsDistinct, handleAddressDelete,
  };
}

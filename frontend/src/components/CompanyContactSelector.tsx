/**
 * Phase 1-B-2 Step 5c-3: 会社 + 担当者 連動セレクタ。
 *
 * deals/quotes/orders/leads.convert の各フォームで顧客（旧 customer_id）の代わりに
 * (company_id, contact_id) を選択させるための共通コンポーネント。
 *
 * 動作:
 *   1. 初回マウントで /api/v1/companies?per_page=200 を取得（companies prop が渡されない時のみ）
 *   2. company を選ぶと /api/v1/contacts?company_id=N&per_page=100 で contact を読み直す
 *   3. company を変更すると contactId は null にリセット
 *   4. initialFromSearchParams=true なら ?company_id=N からの遷移で初期値を復元
 *   5. error prop で submit 時の検証メッセージを表示
 *
 * backend は Step 5c-3 で customer_id 未指定時に contact_id から _customer_migration_map で
 * 逆引きするため、本コンポーネントの返す (company_id, contact_id) のみで送信できる。
 *
 * 変更履歴:
 *   2026-04-25: Phase 1-B-2 Step 5c-3 — 新設
 *   2026-04-27: PR #147 review follow-up
 *     - F4: URL クエリ初期値復元 effect の依存配列を正しく宣言（useRef ガード）
 *     - F6: companies を props で受け取れるようにし、親で読み込んだ一覧を共有可能に
 *     - F7: companies ロード後に value.companyId が一覧に存在しない場合は警告表示し、
 *       contacts API のエラーと「0 件」を区別して表示
 */

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";

interface CompanyMini {
  id: number;
  company_code: string;
  name: string;
}

interface ContactMini {
  id: number;
  contact_code: string;
  display_name: string | null;
  surname: string | null;
  given_name: string | null;
  primary_email: string | null;
  is_primary_contact: boolean;
}

const contactDisplayName = (c: ContactMini): string => {
  if (c.display_name) return c.display_name;
  const combined = `${c.surname || ""} ${c.given_name || ""}`.trim();
  return combined || c.contact_code;
};

export interface CompanyContactSelectorValue {
  companyId: number | null;
  contactId: number | null;
}

export interface CompanyContactSelectorProps {
  value: CompanyContactSelectorValue;
  onChange: (next: CompanyContactSelectorValue) => void;
  /** 必須（HTML required 属性に反映、デフォルト true） */
  required?: boolean;
  /** 編集ロック用。両セレクタを disabled にする（デフォルト false） */
  disabled?: boolean;
  /** URL クエリ ?company_id=N から初期値を復元する（デフォルト false） */
  initialFromSearchParams?: boolean;
  /** submit 時の検証エラー文。設定するとセレクタ下に赤字で表示 */
  error?: string;
  /** ラベルを表示するか（デフォルト true）。フォームレイアウトに組み込まない場合 false にする */
  showLabels?: boolean;
  /**
   * 親側で既に取得済の companies 一覧を共有する場合に渡す（PR #147 F6）。
   * 渡された場合はコンポーネント内で /companies API を呼ばない。
   */
  companies?: CompanyMini[];
}

export default function CompanyContactSelector({
  value,
  onChange,
  required = true,
  disabled = false,
  initialFromSearchParams = false,
  error,
  showLabels = true,
  companies: externalCompanies,
}: CompanyContactSelectorProps) {
  const [searchParams] = useSearchParams();
  const [internalCompanies, setInternalCompanies] = useState<CompanyMini[]>([]);
  const [contacts, setContacts] = useState<ContactMini[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);
  const [contactsLoadFailed, setContactsLoadFailed] = useState(false);
  // PR #147 F4: マウント時 1 回だけ URL クエリ復元を走らせるためのガード
  const searchParamRestoredRef = useRef(false);

  // 親から companies が渡されない場合のみ自前で取得（F6）
  const companies = externalCompanies ?? internalCompanies;
  const useExternalCompanies = externalCompanies !== undefined;

  // 1. companies 初回ロード（外部から提供されない時のみ）
  useEffect(() => {
    if (useExternalCompanies) return;
    api
      .get<CompanyMini[]>("/companies?per_page=200")
      .then((data) =>
        setInternalCompanies(
          data.map((c) => ({ id: c.id, company_code: c.company_code, name: c.name })),
        ),
      )
      .catch(() => {
        // 静かに無視（セレクタが空になるだけ）
      });
  }, [useExternalCompanies]);

  // 2. URL クエリ初期値復元（マウント時 1 回のみ、value.companyId が未設定の時だけ）
  // PR #147 F4: 依存配列を正しくするため useRef でガードし、value.companyId と
  // initialFromSearchParams を依存に含める（lint も満たす）
  useEffect(() => {
    if (!initialFromSearchParams) return;
    if (searchParamRestoredRef.current) return;
    if (value.companyId !== null) {
      // 初期値が既に親から流し込まれている場合も「復元済」扱いで以降走らせない
      searchParamRestoredRef.current = true;
      return;
    }
    const cid = searchParams.get("company_id");
    if (cid) {
      const parsed = parseInt(cid, 10);
      if (Number.isFinite(parsed) && parsed > 0) {
        searchParamRestoredRef.current = true;
        onChange({ companyId: parsed, contactId: null });
      }
    }
  }, [initialFromSearchParams, value.companyId, searchParams, onChange]);

  // 3. companyId 変化で contacts ロード
  useEffect(() => {
    if (value.companyId === null) {
      setContacts([]);
      setContactsLoadFailed(false);
      return;
    }
    setLoadingContacts(true);
    setContactsLoadFailed(false);
    api
      .get<ContactMini[]>(`/contacts?company_id=${value.companyId}&per_page=100`)
      .then((data) => setContacts(data))
      .catch(() => {
        setContacts([]);
        // PR #147 F7: 取得失敗を「0 件」と区別するため失敗フラグを立てる
        setContactsLoadFailed(true);
      })
      .finally(() => setLoadingContacts(false));
  }, [value.companyId]);

  const handleCompanyChange = (raw: string) => {
    const next = raw ? parseInt(raw, 10) : null;
    // company が変わったら contactId をリセット（別会社の contact が残ると整合性が壊れる）
    onChange({ companyId: next, contactId: null });
  };

  const handleContactChange = (raw: string) => {
    const next = raw ? parseInt(raw, 10) : null;
    onChange({ companyId: value.companyId, contactId: next });
  };

  // PR #147 F7: companies が読み込まれた後に value.companyId が一覧に存在しないケースを警告。
  // 巨大 ID やテナント外の ID を URL クエリで渡された等で起こりうる。
  const companyIdMissing =
    value.companyId !== null &&
    companies.length > 0 &&
    !companies.some((c) => c.id === value.companyId);

  // contacts ドロップダウンのプレースホルダ
  const contactsPlaceholder = (() => {
    if (value.companyId === null) return "先に会社を選択してください";
    if (companyIdMissing) return "選択中の会社が見つかりません";
    if (loadingContacts) return "読み込み中...";
    if (contactsLoadFailed) return "担当者の取得に失敗しました";
    if (contacts.length === 0) return "この会社に担当者が登録されていません";
    return "選択してください";
  })();

  return (
    <>
      <div className="form-group">
        {showLabels && <label>会社{required ? " *" : ""}</label>}
        <select
          required={required}
          disabled={disabled}
          value={value.companyId !== null ? String(value.companyId) : ""}
          onChange={(e) => handleCompanyChange(e.target.value)}
        >
          <option value="">選択してください</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}（{c.company_code}）
            </option>
          ))}
        </select>
        {companyIdMissing && (
          <div
            className="error-message"
            style={{ marginTop: 4, fontSize: "0.875rem" }}
          >
            指定された会社が一覧に存在しません。再度選択してください。
          </div>
        )}
      </div>
      <div className="form-group">
        {showLabels && <label>担当者{required ? " *" : ""}</label>}
        <select
          required={required}
          disabled={
            disabled ||
            value.companyId === null ||
            companyIdMissing ||
            loadingContacts
          }
          value={value.contactId !== null ? String(value.contactId) : ""}
          onChange={(e) => handleContactChange(e.target.value)}
        >
          <option value="">{contactsPlaceholder}</option>
          {contacts.map((c) => (
            <option key={c.id} value={c.id}>
              {contactDisplayName(c)}
              {c.is_primary_contact ? "（主担当）" : ""}
            </option>
          ))}
        </select>
        {error && (
          <div className="error-message" style={{ marginTop: 4, fontSize: "0.875rem" }}>
            {error}
          </div>
        )}
      </div>
    </>
  );
}

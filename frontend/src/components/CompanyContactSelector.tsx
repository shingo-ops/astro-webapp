/**
 * Phase 1-B-2 Step 5c-3: 会社 + 担当者 連動セレクタ。
 *
 * deals/quotes/orders/leads.convert の各フォームで顧客（旧 customer_id）の代わりに
 * (company_id, contact_id) を選択させるための共通コンポーネント。
 *
 * 動作:
 *   1. 初回マウントで /api/v1/companies?per_page=200 を取得
 *   2. company を選ぶと /api/v1/contacts?company_id=N&per_page=100 で contact を読み直す
 *   3. company を変更すると contactId は null にリセット
 *   4. initialFromSearchParams=true なら ?company_id=N からの遷移で初期値を復元
 *   5. error prop で submit 時の検証メッセージを表示
 *
 * backend は Step 5c-3 で customer_id 未指定時に contact_id から _customer_migration_map で
 * 逆引きするため、本コンポーネントの返す (company_id, contact_id) のみで送信できる。
 */

import { useEffect, useState } from "react";
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
}

export default function CompanyContactSelector({
  value,
  onChange,
  required = true,
  disabled = false,
  initialFromSearchParams = false,
  error,
  showLabels = true,
}: CompanyContactSelectorProps) {
  const [searchParams] = useSearchParams();
  const [companies, setCompanies] = useState<CompanyMini[]>([]);
  const [contacts, setContacts] = useState<ContactMini[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);

  // 1. companies 初回ロード
  useEffect(() => {
    api
      .get<CompanyMini[]>("/companies?per_page=200")
      .then((data) =>
        setCompanies(
          data.map((c) => ({ id: c.id, company_code: c.company_code, name: c.name })),
        ),
      )
      .catch(() => {
        // 静かに無視（セレクタが空になるだけ）
      });
  }, []);

  // 2. URL クエリ初期値復元（マウント時 1 回のみ、value.companyId が未設定の時だけ）
  useEffect(() => {
    if (!initialFromSearchParams) return;
    if (value.companyId !== null) return;
    const cid = searchParams.get("company_id");
    if (cid) {
      const parsed = parseInt(cid, 10);
      if (Number.isFinite(parsed)) {
        onChange({ companyId: parsed, contactId: null });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 3. companyId 変化で contacts ロード
  useEffect(() => {
    if (value.companyId === null) {
      setContacts([]);
      return;
    }
    setLoadingContacts(true);
    api
      .get<ContactMini[]>(`/contacts?company_id=${value.companyId}&per_page=100`)
      .then((data) => setContacts(data))
      .catch(() => setContacts([]))
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
      </div>
      <div className="form-group">
        {showLabels && <label>担当者{required ? " *" : ""}</label>}
        <select
          required={required}
          disabled={disabled || value.companyId === null || loadingContacts}
          value={value.contactId !== null ? String(value.contactId) : ""}
          onChange={(e) => handleContactChange(e.target.value)}
        >
          <option value="">
            {value.companyId === null
              ? "先に会社を選択してください"
              : loadingContacts
                ? "読み込み中..."
                : contacts.length === 0
                  ? "この会社に担当者が登録されていません"
                  : "選択してください"}
          </option>
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

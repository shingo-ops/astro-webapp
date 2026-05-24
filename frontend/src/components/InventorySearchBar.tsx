/**
 * InventorySearchBar — Sprint 7 / spec F7 在庫検索 UI コンポーネント。
 *
 * 用途:
 *   - QuoteCreatePage で商品選択用に組み込む (既存 `<select>` を置換)。
 *   - ParseReviewPage の product_id===null 行に埋め込み、インライン解決にも使用 (Sprint 6 申し送り)。
 *
 * 機能:
 *   - 7 種横断検索 (products name/name_en/expansion_code/card_number/jan_code +
 *     pokemon_dex/trainer_dex/tcg_series_master/supplier_aliases)
 *   - AND / OR トグル (segmented control、i18n)
 *   - debounce 250ms
 *   - 候補リスト: 在庫 > 0 通常、stock_quantity === 0 グレーアウト + 末尾配置 (バックエンドが score で末尾化)
 *   - stock_quantity === null は inventory.visibility.full 権限なし → `***` 表示 (AC7.9)
 *   - matched_via バッジ表示 (i18n、各 source ごと)
 *   - 候補クリック時 onSelect(candidate) → 親 component 側で line_item 追加
 *   - 在庫 0 商品選択時に warning メッセージを inline 表示
 *
 * AC 対応:
 *   AC7.1〜7.5, 7.7, 7.8, 7.9
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

export interface InventorySearchCandidate {
  product_id: number;
  name: string;
  name_en: string | null;
  product_code: string | null;
  expansion_code: string | null;
  card_number: string | null;
  jan_code: string | null;
  unit_price: number | null;
  stock_quantity: number | null;
  supplier_default_id: number | null;
  supplier_name: string | null;
  image_url: string | null;
  matched_via: string;
  score: number;
}

export interface InventorySearchResponse {
  query: string;
  op: string;
  total: number;
  masked: boolean;
  candidates: InventorySearchCandidate[];
}

export interface InventorySearchBarProps {
  /** 候補クリック時に呼ばれる。在庫 0 でも呼ばれるが、in-stock=false がフラグで渡る。 */
  onSelect: (candidate: InventorySearchCandidate) => void;
  /** UI 言語 (placeholder / バッジ表示に影響する。バックエンド検索は ja/en 両方横断するのでロジックには影響なし)。 */
  language?: "ja" | "en";
  /** 入力フィールドを disable する。 */
  disabled?: boolean;
  /** UI ラベル (placeholder の代わり)。省略時は i18n key。 */
  placeholder?: string;
  /** debounce 時間 (ms)。デフォルト 250ms、テスト時に短くできる。 */
  debounceMs?: number;
  /** AC 検証 / E2E 用の data-testid prefix (省略時 `inventory-search`)。 */
  testIdPrefix?: string;
}

const DEFAULT_DEBOUNCE = 250;
const MAX_RESULTS = 20;

function matchedViaKey(via: string): string {
  // backend: products_name / products_name_en / products_card_number_exact / ...
  // i18n key: inventory.search.matchedVia.<via>
  return `inventory.search.matchedVia.${via}`;
}

export default function InventorySearchBar({
  onSelect,
  language = "ja",
  disabled = false,
  placeholder,
  debounceMs = DEFAULT_DEBOUNCE,
  testIdPrefix = "inventory-search",
}: InventorySearchBarProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState<string>("");
  const [op, setOp] = useState<"and" | "or">("or");
  const [results, setResults] = useState<InventorySearchCandidate[]>([]);
  const [masked, setMasked] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [zeroStockWarning, setZeroStockWarning] = useState<string>("");
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const [open, setOpen] = useState<boolean>(false);

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastQueryRef = useRef<string>("");

  const doSearch = useCallback(
    async (q: string, currentOp: "and" | "or") => {
      const trimmed = q.trim();
      if (!trimmed) {
        setResults([]);
        setMasked(false);
        setError("");
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const resp = await api.get<InventorySearchResponse>(
          `/inventory/search?q=${encodeURIComponent(trimmed)}&lang=${language}&op=${currentOp}&limit=${MAX_RESULTS}`,
        );
        // 古いリクエストの結果は捨てる
        if (lastQueryRef.current !== trimmed) return;
        setResults(resp.candidates);
        setMasked(resp.masked);
        setActiveIndex(-1);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("common.fetchError"));
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [language, t],
  );

  // debounce
  useEffect(() => {
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }
    lastQueryRef.current = query.trim();
    if (!query.trim()) {
      setResults([]);
      setError("");
      setLoading(false);
      return;
    }
    debounceTimer.current = setTimeout(() => {
      void doSearch(query, op);
    }, debounceMs);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
    // op 変更時も再検索したいので依存に含める
  }, [query, op, debounceMs, doSearch]);

  const handleSelect = useCallback(
    (c: InventorySearchCandidate) => {
      if (c.stock_quantity !== null && c.stock_quantity <= 0) {
        // 在庫 0 警告 (AC7.5)
        setZeroStockWarning(
          t("inventory.search.zeroStockWarning", { name: c.name }),
        );
      } else {
        setZeroStockWarning("");
      }
      onSelect(c);
      // 候補確定後は listbox を閉じ、入力欄もリセットして次の検索に備える。
      // (Major F3 fix) query を残したまま閉じると、同一キーワードで再検索した時に
      //   React の controlled value 同値判定で onChange / useEffect が発火せず
      //   listbox が再 open できないため、明示的に空文字へ戻す。
      setOpen(false);
      setQuery("");
      setResults([]);
      setActiveIndex(-1);
      lastQueryRef.current = "";
    },
    [onSelect, t],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      if (activeIndex >= 0 && activeIndex < results.length) {
        e.preventDefault();
        handleSelect(results[activeIndex]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const placeholderText = useMemo(
    () => placeholder ?? t("inventory.search.placeholder"),
    [placeholder, t],
  );

  const renderStock = (c: InventorySearchCandidate): string => {
    if (c.stock_quantity === null) return "***";
    return String(c.stock_quantity);
  };

  return (
    <div
      className="inventory-search-bar"
      style={{ position: "relative", width: "100%" }}
      data-testid={`${testIdPrefix}-root`}
    >
      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={placeholderText}
          data-testid={`${testIdPrefix}-input`}
          style={{ flex: 1, minWidth: "var(--min-width-input-sm)", padding: "var(--space-6px) var(--space-2)" }}
          aria-label={t("inventory.search.placeholder")}
        />
        <div
          role="radiogroup"
          aria-label={t("inventory.search.opGroupLabel")}
          style={{ display: "inline-flex", gap: 0, border: "1px solid var(--border-color)", borderRadius: "var(--radius-sm)" }}
          data-testid={`${testIdPrefix}-op-toggle`}
        >
          <button
            type="button"
            onClick={() => setOp("and")}
            disabled={disabled}
            aria-pressed={op === "and"}
            data-testid={`${testIdPrefix}-op-and`}
            style={{
              padding: "var(--space-1) var(--space-10px)",
              border: "none",
              background: op === "and" ? "var(--accent-bg)" : "transparent",
              color: op === "and" ? "var(--on-accent)" : "inherit",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            {t("inventory.search.opAnd")}
          </button>
          <button
            type="button"
            onClick={() => setOp("or")}
            disabled={disabled}
            aria-pressed={op === "or"}
            data-testid={`${testIdPrefix}-op-or`}
            style={{
              padding: "var(--space-1) var(--space-10px)",
              border: "none",
              background: op === "or" ? "var(--accent-bg)" : "transparent",
              color: op === "or" ? "var(--on-accent)" : "inherit",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            {t("inventory.search.opOr")}
          </button>
        </div>
      </div>

      {error && (
        <div
          className="error-message"
          role="alert"
          data-testid={`${testIdPrefix}-error`}
          style={{ marginTop: "var(--space-1)" }}
        >
          {error}
        </div>
      )}
      {zeroStockWarning && (
        <div
          className="warning-message"
          role="status"
          data-testid={`${testIdPrefix}-zero-stock`}
          style={{
            marginTop: "var(--space-1)",
            color: "var(--color-warning)",
            fontSize: "var(--font-base)",
          }}
        >
          {zeroStockWarning}
        </div>
      )}

      {open && query.trim().length > 0 && (
        <ul
          role="listbox"
          aria-label={t("inventory.search.candidatesLabel")}
          data-testid={`${testIdPrefix}-results`}
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            maxHeight: 320,
            overflowY: "auto",
            margin: "2px 0 0 0",
            padding: 0,
            listStyle: "none",
            background: "var(--bg-surface)",
            border: "1px solid var(--border-color)",
            borderRadius: "var(--radius-sm)",
            boxShadow: "var(--shadow-md)",
            zIndex: "var(--z-dropdown)",
          }}
        >
          {loading && (
            <li
              data-testid={`${testIdPrefix}-loading`}
              style={{ padding: "var(--space-2) var(--space-10px)", color: "var(--text-secondary)" }}
            >
              {t("common.loading")}
            </li>
          )}
          {!loading && results.length === 0 && (
            <li
              data-testid={`${testIdPrefix}-empty`}
              style={{ padding: "var(--space-2) var(--space-10px)", color: "var(--text-secondary)" }}
            >
              {t("inventory.search.noResults")}
            </li>
          )}
          {!loading &&
            results.map((c, i) => {
              const isZero =
                c.stock_quantity !== null && c.stock_quantity <= 0;
              const isActive = i === activeIndex;
              return (
                <li
                  key={c.product_id}
                  role="option"
                  aria-selected={isActive}
                  data-testid={`${testIdPrefix}-result-${i}`}
                  data-product-id={c.product_id}
                  data-matched-via={c.matched_via}
                  data-zero-stock={isZero ? "true" : "false"}
                  onMouseEnter={() => setActiveIndex(i)}
                  onMouseDown={(e) => {
                    // mouse down で focus 失わずに選択する (blur 前)
                    e.preventDefault();
                    handleSelect(c);
                  }}
                  style={{
                    padding: "var(--space-2) var(--space-10px)",
                    cursor: "pointer",
                    background: isActive
                      ? "var(--bg-hover)"
                      : "transparent",
                    opacity: isZero ? 0.55 : 1,
                    borderBottom: "1px solid var(--border-light)",
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: "var(--font-weight-semi)",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                      data-testid={`${testIdPrefix}-result-${i}-name`}
                    >
                      {c.name}
                      {c.name_en && (
                        <span
                          style={{
                            marginLeft: "var(--space-6px)",
                            color: "var(--text-muted)",
                            fontWeight: "var(--font-weight-normal)",
                          }}
                          data-testid={`${testIdPrefix}-result-${i}-name-en`}
                        >
                          {c.name_en}
                        </span>
                      )}
                    </div>
                    <div
                      style={{ fontSize: "var(--font-sm)", color: "var(--text-secondary)", marginTop: "var(--space-2px)" }}
                    >
                      <span
                        data-testid={`${testIdPrefix}-result-${i}-matched-via`}
                        style={{
                          padding: "var(--space-2px) var(--space-6px)",
                          marginRight: "var(--space-6px)",
                          border: "1px solid var(--border-color)",
                          borderRadius: "var(--radius-xl)",
                          background: "var(--bg-badge)",
                        }}
                      >
                        {t(matchedViaKey(c.matched_via), c.matched_via)}
                      </span>
                      {c.card_number && (
                        <span style={{ marginRight: "var(--space-6px)" }}>
                          <code>{c.card_number}</code>
                        </span>
                      )}
                      {c.expansion_code && (
                        <span style={{ marginRight: "var(--space-6px)" }}>
                          [{c.expansion_code}]
                        </span>
                      )}
                      {c.supplier_name && (
                        <span style={{ marginRight: "var(--space-6px)" }}>
                          {c.supplier_name}
                        </span>
                      )}
                    </div>
                  </div>
                  <div
                    style={{ textAlign: "right", whiteSpace: "nowrap" }}
                    data-testid={`${testIdPrefix}-result-${i}-stock-block`}
                  >
                    <div style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)" }}>
                      {t("inventory.search.stockLabel")}:{" "}
                      <span
                        data-testid={`${testIdPrefix}-result-${i}-stock`}
                        style={{
                          fontWeight: "var(--font-weight-semi)",
                          color: isZero ? "var(--color-warning)" : "inherit",
                        }}
                      >
                        {renderStock(c)}
                      </span>
                    </div>
                    {c.unit_price !== null && (
                      <div style={{ fontSize: "var(--font-sm)" }}>
                        ¥{c.unit_price.toLocaleString()}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
        </ul>
      )}

      {masked && (
        <div
          data-testid={`${testIdPrefix}-masked-indicator`}
          style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)", marginTop: "var(--space-2px)" }}
        >
          {t("inventory.search.stockMaskedNote")}
        </div>
      )}
    </div>
  );
}

/**
 * InventoryPicker — 在庫一覧から商品を選ぶコンボボックス (A案2 / QA 2026-05-29)。
 *
 * 「検索してから選択」ではなく、フォーカスで在庫一覧を表示し、入力で絞り込みつつ
 * 一覧の行をクリックして選択する。AND/OR トグルは持たない。在庫数は“目安”として参考表示。
 *
 * データ源: GET /products (search / per_page)。テナント共通の商品マスタ + 在庫数 + 単価。
 * 用途: 発注 (PurchaseOrdersFormModal) と 解析結果レビュー (ParseReviewPage) の商品選択。
 *
 * テーブルセル内 (overflow) で使うため、ドロップダウンは createPortal で body 直下に描画する
 * (InventorySearchBar と同じ理由)。
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

/** GET /products の 1 行 (必要フィールドのみ)。 */
interface PickerProduct {
  id: number;
  name_ja: string;
  name_en: string | null;
  category: string | null;
  unit_price: number | null;
  quantity: number;
}

/** onSelect で親に渡す確定商品。 */
export interface PickedProduct {
  product_id: number;
  name: string;
  unit_price: number | null;
  stock_quantity: number;
  category: string | null;
}

export interface InventoryPickerProps {
  /** 行クリック / Enter で確定した商品を親へ渡す。 */
  onSelect: (product: PickedProduct) => void;
  disabled?: boolean;
  /** placeholder 文言 (省略時は i18n)。 */
  placeholder?: string;
  /** debounce (ms)。デフォルト 250、テストで短縮可。 */
  debounceMs?: number;
  /** E2E / AC 用 data-testid prefix。 */
  testIdPrefix?: string;
  /**
   * 初期検索クエリ (QA 2026-05-30)。解析結果レビューで「解析された商品名」を
   * 予めセットし、その名前を含む商品マスタを候補として絞り込んだ状態にする。
   */
  initialQuery?: string;
  /**
   * 候補に「在庫(目安)」を表示するか (QA 2026-05-30)。デフォルト true (発注画面は従来どおり)。
   * 解析結果レビューの商品マスタ選択では在庫は無関係なため false を渡して非表示にする。
   */
  showStockGuide?: boolean;
}

const DEFAULT_DEBOUNCE = 250;
const MAX_RESULTS = 20;

export default function InventoryPicker({
  onSelect,
  disabled = false,
  placeholder,
  debounceMs = DEFAULT_DEBOUNCE,
  testIdPrefix = "inventory-picker",
  initialQuery,
  showStockGuide = true,
}: InventoryPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState<string>(initialQuery ?? "");
  const [results, setResults] = useState<PickerProduct[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const [open, setOpen] = useState<boolean>(false);

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastQueryRef = useRef<string>("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [rect, setRect] = useState<{ top: number; left: number; width: number }>(
    { top: 0, left: 0, width: 0 },
  );

  const recalc = useCallback(() => {
    if (!inputRef.current) return;
    const r = inputRef.current.getBoundingClientRect();
    setRect({ top: r.bottom + 2, left: r.left, width: r.width });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    recalc();
    const handler = () => recalc();
    window.addEventListener("scroll", handler, true);
    window.addEventListener("resize", handler);
    return () => {
      window.removeEventListener("scroll", handler, true);
      window.removeEventListener("resize", handler);
    };
  }, [open, recalc]);

  const doFetch = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      setLoading(true);
      setError("");
      try {
        const qs = trimmed
          ? `?search=${encodeURIComponent(trimmed)}&per_page=${MAX_RESULTS}`
          : `?per_page=${MAX_RESULTS}`;
        const data = await api.get<PickerProduct[]>(`/products${qs}`);
        // 古いリクエストの結果は捨てる
        if (lastQueryRef.current !== trimmed) return;
        setResults(data);
        setActiveIndex(-1);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("common.fetchError"));
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  // open 中は (空クエリ=在庫一覧 / 入力=絞り込み) を debounce 付きで取得
  useEffect(() => {
    if (!open) return;
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    lastQueryRef.current = query.trim();
    debounceTimer.current = setTimeout(() => {
      void doFetch(query);
    }, debounceMs);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [query, open, debounceMs, doFetch]);

  const handleSelect = useCallback(
    (p: PickerProduct) => {
      onSelect({
        product_id: p.id,
        name: p.name_ja,
        unit_price: p.unit_price,
        stock_quantity: p.quantity,
        category: p.category,
      });
      setOpen(false);
      setQuery("");
      setResults([]);
      setActiveIndex(-1);
      lastQueryRef.current = "";
    },
    [onSelect],
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
    () => placeholder ?? t("inventory.search.pickerPlaceholder"),
    [placeholder, t],
  );

  return (
    <div
      className="inventory-picker"
      style={{ position: "relative", width: "100%" }}
      data-testid={`${testIdPrefix}-root`}
    >
      <input
        ref={inputRef}
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
        style={{
          width: "100%",
          minWidth: "var(--min-width-input-sm)",
          padding: "var(--space-6px) var(--space-2)",
        }}
        aria-label={placeholderText}
      />
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
      {open &&
        createPortal(
          <ul
            role="listbox"
            data-testid={`${testIdPrefix}-results`}
            style={{
              position: "fixed",
              top: `${rect.top}px`,
              left: `${rect.left}px`,
              width: `${Math.max(rect.width, Math.min(560, Math.max(0, window.innerWidth - rect.left - 16)))}px`,
              minWidth: "var(--dropdown-min-width)",
              maxHeight: "var(--dropdown-results-max-h)",
              overflowY: "auto",
              margin: 0,
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
              results.map((p, i) => {
                const isZero = p.quantity <= 0;
                const isActive = i === activeIndex;
                return (
                  <li
                    key={p.id}
                    role="option"
                    aria-selected={isActive}
                    data-testid={`${testIdPrefix}-result-${i}`}
                    data-product-id={p.id}
                    onMouseEnter={() => setActiveIndex(i)}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      handleSelect(p);
                    }}
                    style={{
                      padding: "var(--space-2) var(--space-10px)",
                      cursor: "pointer",
                      background: isActive ? "var(--bg-hover)" : "transparent",
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
                        {p.name_ja}
                        {p.name_en && (
                          <span
                            style={{
                              marginLeft: "var(--space-6px)",
                              color: "var(--text-muted)",
                              fontWeight: "var(--font-weight-normal)",
                            }}
                          >
                            {p.name_en}
                          </span>
                        )}
                      </div>
                      {p.category && (
                        <div
                          style={{
                            fontSize: "var(--font-sm)",
                            color: "var(--text-secondary)",
                            marginTop: "var(--space-2px)",
                          }}
                        >
                          {p.category}
                        </div>
                      )}
                    </div>
                    <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {showStockGuide && (
                        <div style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)" }}>
                          {t("inventory.search.stockGuide")}:{" "}
                          <span
                            data-testid={`${testIdPrefix}-result-${i}-stock`}
                            style={{
                              fontWeight: "var(--font-weight-semi)",
                              color: isZero ? "var(--color-warning)" : "inherit",
                            }}
                          >
                            {p.quantity}
                          </span>
                        </div>
                      )}
                      {p.unit_price !== null && (
                        <div style={{ fontSize: "var(--font-sm)" }}>
                          ¥{p.unit_price.toLocaleString()}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
          </ul>,
          document.body,
        )}
    </div>
  );
}

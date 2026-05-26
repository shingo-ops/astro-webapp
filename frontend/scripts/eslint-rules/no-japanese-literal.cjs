'use strict';
/**
 * ESLint rule: no-japanese-literal
 *
 * JSX / TS(X) ソースコード内の日本語文字列ハードコードを禁止する。
 * UI 文字列はすべて t("key") 経由にすること（ADR-027）。
 *
 * 検出対象:
 *   - JSXText:         <p>日本語</p>
 *   - Literal:         const x = "日本語" / placeholder="日本語"
 *   - TemplateElement: `日本語${x}`
 *
 * 除外:
 *   - ImportDeclaration: import foo from "日本語/パス"
 *   - SwitchCase:        case "ステータス値":
 *   - <option value="DB値">: DB 由来の選択肢値（<option> 限定）
 *   - コメント: ESLint は AST ノードしか検査しないため自動除外
 */

const JP = /[\u3041-\u3096\u30A1-\u30F6\u4E00-\u9FFF]/;

module.exports = {
  meta: {
    type: 'problem',
    docs: {
      description: 'JSX/TSX 内の日本語文字列ハードコードを禁止する（ADR-027）',
    },
    schema: [],
    messages: {
      jsxText:      'i18n: JSX直書き日本語禁止。{t("key")} を使ってください（ADR-027）',
      literal:      'i18n: 文字列リテラル日本語禁止。t("key") を使ってください（ADR-027）',
      templateElem: 'i18n: テンプレートリテラル日本語禁止。t("key") を使ってください（ADR-027）',
    },
  },

  create(context) {
    return {
      // <p>日本語テキスト</p>
      JSXText(node) {
        if (JP.test(node.value.trim())) {
          context.report({ node, messageId: 'jsxText' });
        }
      },

      // "日本語" / placeholder="日本語" / aria-label="日本語"
      Literal(node) {
        if (typeof node.value !== 'string') return;
        if (!JP.test(node.value)) return;

        // import 文のパス文字列は除外
        if (node.parent?.type === 'ImportDeclaration') return;

        // switch (x) { case "DB値": } は除外
        if (node.parent?.type === 'SwitchCase') return;

        // <option value="DB値"> のみ除外（他の要素の value は対象）
        // node → parent (JSXAttribute) → parent (JSXOpeningElement) → name.name
        const jsxAttr = node.parent?.type === 'JSXAttribute' ? node.parent : null;
        if (
          jsxAttr?.name?.name === 'value' &&
          jsxAttr?.parent?.name?.name === 'option'
        ) {
          return;
        }

        context.report({ node, messageId: 'literal' });
      },

      // `日本語${x}テキスト`
      TemplateElement(node) {
        if (JP.test(node.value.raw)) {
          context.report({ node, messageId: 'templateElem' });
        }
      },
    };
  },
};

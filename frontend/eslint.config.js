// For more info, see https://github.com/storybookjs/eslint-plugin-storybook#configuration-flat-config-format
import storybook from "eslint-plugin-storybook";

import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactHooksPlugin from 'eslint-plugin-react-hooks';
import { createRequire } from 'module';

// CJS カスタムルールを ESM flat config に読み込む（ADR-027 i18n 強制）
const _require = createRequire(import.meta.url);
const noJapaneseLiteral = _require('./scripts/eslint-rules/no-japanese-literal.cjs');

export default [{
  files: ['src/**/*.{ts,tsx}'],
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
  plugins: {
    '@typescript-eslint': tsPlugin,
    'react-hooks': reactHooksPlugin,
    // i18n ハードコード検出（ADR-027）
    'local': { rules: { 'no-japanese-literal': noJapaneseLiteral } },
  },
  rules: {
    // i18n ハードコード日本語禁止（ADR-027）
    // Phase 1: warn のみ（既存違反を把握してから error に昇格）
    // ※ lint-staged は --max-warnings=0 のためローカルコミット時も検出される
    'local/no-japanese-literal': 'warn',

    // react-hooks ルールを有効化（eslint-disable コメントのルール不明エラーを防ぐ）
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',

    // ダークモード強制（ADR-067）:
    // TSXインラインスタイルへのhex色ハードコード禁止。
    // CSS変数を使ってください: style={{ color: 'var(--text-primary)' }}
    'no-restricted-syntax': [
      'error',
      // 純粋なhex値: style={{ color: "#fff" }}
      {
        selector:
          "JSXAttribute[name.name='style'] Property > Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
        message:
          "❌ インラインスタイルへのhex色ハードコード禁止（ADR-067）。CSS変数を使ってください: style={{ color: 'var(--text-primary)' }}",
      },
      // 複合文字列に埋め込まれたhex値: style={{ border: "1px solid #ddd" }}
      {
        selector:
          "JSXAttribute[name.name='style'] Property > Literal[value=/#[0-9a-fA-F]{3,8}/][value!=/^#[0-9a-fA-F]{3,8}$/]",
        message:
          "❌ インラインスタイルへのhex色ハードコード禁止（ADR-067）。CSS変数を使ってください: style={{ border: '1px solid var(--border-color)' }}",
      },
      // opacity 数値直書き禁止: style={{ opacity: 0.5 }} ※文字列 var() は除外
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='opacity'][value.type='Literal'][value.value!=/^var\\(/]",
        message:
          "❌ インラインスタイルへの opacity 数値直書き禁止（ADR-067）。CSS変数を使ってください: style={{ opacity: 'var(--opacity-dim)' }}",
      },
      // zIndex 数値直書き禁止: style={{ zIndex: 50 }} ※文字列 var() は除外
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='zIndex'][value.type='Literal'][value.value!=/^var\\(/]",
        message:
          "❌ インラインスタイルへの zIndex 数値直書き禁止（ADR-067）。CSS変数を使ってください: style={{ zIndex: 'var(--z-topbar)' }}",
      },
      // rgba()/rgb() 色直書き禁止: style={{ background: "rgba(0,0,0,0.5)" }}
      {
        selector:
          "JSXAttribute[name.name='style'] Property > Literal[value=/rgba?\\s*\\(/]",
        message:
          "❌ インラインスタイルへの rgba()/rgb() 色直書き禁止（ADR-067）。CSS変数を使ってください: style={{ background: 'var(--overlay-bg)' }}",
      },
      // ---- Phase 5: width/height/minWidth/maxWidth/minHeight/maxHeight 数値直書き禁止 (ADR-067) ----
      // 0 は flexbox リセット用として許可。文字列値（"100%" 等）は許可。
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='width'][value.type='Literal'][value.raw=/^\\d+(\\.\\d+)?$/]",
        message:
          "❌ width 数値直書き禁止（ADR-067 Phase 5）→ style={{ width: 'var(--input-width-qty)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='height'][value.type='Literal'][value.raw=/^\\d+(\\.\\d+)?$/]",
        message:
          "❌ height 数値直書き禁止（ADR-067 Phase 5）→ style={{ height: 'var(--size-thread-avatar)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='minWidth'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ minWidth 数値直書き禁止（ADR-067 Phase 5）→ style={{ minWidth: 'var(--table-col-min-width)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='maxWidth'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ maxWidth 数値直書き禁止（ADR-067 Phase 5）→ style={{ maxWidth: 'var(--modal-wide-w)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='minHeight'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ minHeight 数値直書き禁止（ADR-067 Phase 5）→ style={{ minHeight: 'var(--textarea-min-h-lg)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='maxHeight'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ maxHeight 数値直書き禁止（ADR-067 Phase 5）→ style={{ maxHeight: 'var(--dropdown-results-max-h)' }}",
      },
    ],

    // アイコン一元管理（ADR-067 拡張）:
    // lucide-react からの直接 import 禁止。constants/icons.tsx 経由でインポートすること。
    // 型 import も含む（LucideIcon 型は constants/icons.tsx から export type で取得）。
    'no-restricted-imports': [
      'error',
      {
        paths: [
          {
            name: 'lucide-react',
            message:
              "❌ lucide-react からの直接 import 禁止（ADR-067）。constants/icons.tsx 経由でインポートしてください。型が必要な場合: import type { LucideIcon } from '../constants/icons'",
          },
        ],
      },
    ],
  },
}, // 例外: constants/icons.tsx は lucide-react を直接 import してよい（唯一の窓口）
{
  files: ['src/constants/icons.tsx'],
  rules: {
    'no-restricted-imports': 'off',
  },
}, // PageLayout 強制（ADR-067 拡張）:
// pages/ 配下で raw <h2> を書かせない。<PageLayout navKey="nav.xxx"> を使うこと。
{
  files: ['src/pages/**/*.tsx', 'src/pages/**/*.ts'],
  rules: {
    'no-restricted-syntax': [
      'error',
      {
        selector: "JSXOpeningElement[name.name='h2']",
        message:
          '❌ raw <h2> 禁止（ADR-067）。<PageLayout navKey="nav.xxx"> を使ってください（frontend/CLAUDE.md 参照）',
      },
      // ---- Phase 5 (再掲: pages/ ブロックが上書きするため重複必要) ----
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='width'][value.type='Literal'][value.raw=/^\\d+(\\.\\d+)?$/]",
        message:
          "❌ width 数値直書き禁止（ADR-067 Phase 5）→ style={{ width: 'var(--input-width-qty)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='height'][value.type='Literal'][value.raw=/^\\d+(\\.\\d+)?$/]",
        message:
          "❌ height 数値直書き禁止（ADR-067 Phase 5）→ style={{ height: 'var(--size-thread-avatar)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='minWidth'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ minWidth 数値直書き禁止（ADR-067 Phase 5）→ style={{ minWidth: 'var(--table-col-min-width)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='maxWidth'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ maxWidth 数値直書き禁止（ADR-067 Phase 5）→ style={{ maxWidth: 'var(--modal-wide-w)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='minHeight'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ minHeight 数値直書き禁止（ADR-067 Phase 5）→ style={{ minHeight: 'var(--textarea-min-h-lg)' }}",
      },
      {
        selector:
          "JSXAttribute[name.name='style'] Property[key.name='maxHeight'][value.type='Literal'][value.raw=/^[1-9]\\d*(\\.\\d+)?$/]",
        message:
          "❌ maxHeight 数値直書き禁止（ADR-067 Phase 5）→ style={{ maxHeight: 'var(--dropdown-results-max-h)' }}",
      },
    ],
  },
}, // 例外: PageLayout.tsx 自体は h2 を直接使ってよい（唯一の実装箇所）
{
  files: ['src/components/PageLayout.tsx'],
  rules: {
    'no-restricted-syntax': 'off',
  },
}, // i18n ルール除外: Storybook / デザインシステム / ロケールファイル
// ストーリーファイルはデモ用途のため除外。ロケールファイルは翻訳定義そのもの。
{
  files: [
    'src/**/*.stories.{ts,tsx}',
    'src/**/*.story.{ts,tsx}',
    'src/design-system/**/*.{ts,tsx}',
    'src/pages/design-system/**/*.{ts,tsx}',
    'src/locales/**',
    '.storybook/**',
  ],
  rules: {
    'local/no-japanese-literal': 'off',
    'no-restricted-syntax': 'off', // ストーリーはデモ用途のため寸法ハードコードを許容
  },
}, ...storybook.configs["flat/recommended"]];

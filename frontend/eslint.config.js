// For more info, see https://github.com/storybookjs/eslint-plugin-storybook#configuration-flat-config-format
import storybook from "eslint-plugin-storybook";

import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactHooksPlugin from 'eslint-plugin-react-hooks';

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
  },
  rules: {
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
    ],
  },
}, // 例外: PageLayout.tsx 自体は h2 を直接使ってよい（唯一の実装箇所）
{
  files: ['src/components/PageLayout.tsx'],
  rules: {
    'no-restricted-syntax': 'off',
  },
}, ...storybook.configs["flat/recommended"]];

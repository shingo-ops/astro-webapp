import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactHooksPlugin from 'eslint-plugin-react-hooks';

export default [
  {
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
        {
          selector:
            "JSXAttribute[name.name='style'] Property > Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
          message:
            "❌ インラインスタイルへのhex色ハードコード禁止（ADR-067）。CSS変数を使ってください: style={{ color: 'var(--text-primary)' }}",
        },
      ],
    },
  },
];

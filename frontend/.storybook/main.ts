import type { StorybookConfig } from '@storybook/react-vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const config: StorybookConfig = {
  "stories": [
    "../src/**/*.mdx",
    "../src/**/*.stories.@(js|jsx|mjs|ts|tsx)"
  ],
  "addons": [
    "@chromatic-com/storybook",
    "@storybook/addon-vitest",
    "@storybook/addon-a11y",
    "@storybook/addon-docs",
    "@storybook/addon-mcp"
  ],
  "framework": "@storybook/react-vite",
  // firebase/app と firebase/auth を Storybook/Chromatic 環境でモックに差し替える
  // 本番コード変更なし・視覚テスト時にネットワーク接続不要
  viteFinal: async (config) => {
    const existingAlias = config.resolve?.alias ?? {};
    const aliasRecord = Array.isArray(existingAlias)
      ? Object.fromEntries(existingAlias.map((a) => [a.find, a.replacement]))
      : existingAlias;

    return {
      ...config,
      resolve: {
        ...config.resolve,
        alias: {
          ...aliasRecord,
          'firebase/app': path.resolve(__dirname, '../src/lib/__storybook-mocks__/firebase-app.ts'),
          'firebase/auth': path.resolve(__dirname, '../src/lib/__storybook-mocks__/firebase-auth.ts'),
        },
      },
    };
  },
};
export default config;

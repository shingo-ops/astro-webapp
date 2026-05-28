# Storybook i18n ポリシー（ADR-073 軸5）

## 概要

salesanchor の Storybook stories で国際化（i18n）をどう扱うかを定める。

---

## 基本方針

Storybook stories 内でも **ADR-027（UI 国際化）と同じルール**を適用する。  
ハードコード日本語は禁止。すべての UI 文字列は `t("key")` 経由にする。

---

## stories での i18n 設定

### `preview.tsx` の設定

```tsx
// .storybook/preview.tsx
import '../src/i18n'; // i18n インスタンスを初期化

export const parameters = {
  // i18next-storybook-addon があれば設定可能（現在は任意）
};
```

### stories ファイル内での翻訳

```tsx
// ✅ 推奨: コンポーネント自体が t() を使っているためそのままレンダリング
export const Default: Story = {
  args: { /* コンポーネント props */ },
};

// ✅ 推奨: args に翻訳キーではなく表示文字列を渡す場合
import { t } from 'i18next';
export const WithLabel: Story = {
  args: { label: t('common.save') },
};

// ❌ 禁止: JSX の中に日本語をハードコード
export const Bad: Story = {
  render: () => <Button>保存する</Button>, // eslint が検出
};
```

---

## 言語切替のテスト

stories で言語切替を確認する必要がある場合:

```tsx
import i18n from '../src/i18n';

export const JaStory: Story = {
  play: async () => {
    await i18n.changeLanguage('ja');
  },
};

export const EnStory: Story = {
  play: async () => {
    await i18n.changeLanguage('en');
  },
};
```

---

## Storybook ビルド時の注意

- `build-storybook` は CI の必須チェック（ADR-073 軸3）
- i18n リソース（`src/locales/ja.json`, `src/locales/en.json`）は Vite の `assetsInclude` で自動バンドルされる
- stories で使う翻訳キーは必ず `ja.json` / `en.json` の両方に存在すること

---

## 関連

- ADR-027: UI 国際化（i18n 強制ルール）
- ADR-073: デザインシステム KGI 100% ルーブリック
- `frontend/.storybook/preview.tsx`
- `frontend/src/i18n.ts`

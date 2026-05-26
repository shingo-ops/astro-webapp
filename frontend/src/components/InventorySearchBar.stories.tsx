/**
 * InventorySearchBar — デザイントークンカタログ (ADR-067)
 *
 * 商品在庫横断検索バー（7種検索対応）
 * ※ 入力後にAPIを呼ぶため、Storybook上では空状態で表示される
 *   検索入力欄・AND/ORトグルの見た目確認が目的
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import InventorySearchBar from './InventorySearchBar'

const meta: Meta<typeof InventorySearchBar> = {
  title: 'Components/InventorySearchBar',
  component: InventorySearchBar,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof InventorySearchBar>

export const Default: Story = {
  name: '空状態（日本語UI）',
  args: {
    language: 'ja',
    onSelect: () => {},
  },
}

export const English: Story = {
  name: '空状態（英語UI）',
  args: {
    language: 'en',
    onSelect: () => {},
  },
}

export const Disabled: Story = {
  name: '無効状態',
  args: {
    language: 'ja',
    disabled: true,
    onSelect: () => {},
  },
}

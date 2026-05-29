/**
 * InventoryPicker — デザイントークンカタログ (ADR-067)
 *
 * 在庫一覧から商品を選ぶコンボボックス（A案2）。
 * ※ フォーカスで /products を呼ぶため、Storybook 上では空状態（入力欄）の見た目確認が目的。
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import InventoryPicker from './InventoryPicker'

const meta: Meta<typeof InventoryPicker> = {
  title: 'Components/InventoryPicker',
  component: InventoryPicker,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof InventoryPicker>

export const Default: Story = {
  name: '空状態',
  args: {
    onSelect: () => {},
  },
}

export const Disabled: Story = {
  name: '無効状態',
  args: {
    disabled: true,
    onSelect: () => {},
  },
}

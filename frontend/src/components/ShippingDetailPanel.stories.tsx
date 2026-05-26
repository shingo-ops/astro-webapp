/**
 * ShippingDetailPanel — デザイントークンカタログ (ADR-067)
 *
 * 受注発送情報フォーム
 * ※ マウント時にAPIでデータを取得するため、Storybook上ではローディング状態で表示される
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import ShippingDetailPanel from './ShippingDetailPanel'

const meta: Meta<typeof ShippingDetailPanel> = {
  title: 'Components/ShippingDetailPanel',
  component: ShippingDetailPanel,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof ShippingDetailPanel>

export const Default: Story = {
  name: '発送情報フォーム（API呼び出し→初期状態）',
  args: {
    orderId: 1,
    orderNumber: 'ORD-001',
    onClose: () => {},
  },
}

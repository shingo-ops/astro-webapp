/**
 * PurchaseDetailPanel — デザイントークンカタログ (ADR-067)
 *
 * 受注仕入情報フォーム
 * ※ マウント時にAPIでデータを取得するため、Storybook上ではローディング状態で表示される
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import PurchaseDetailPanel from './PurchaseDetailPanel'

const meta: Meta<typeof PurchaseDetailPanel> = {
  title: 'Components/PurchaseDetailPanel',
  component: PurchaseDetailPanel,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof PurchaseDetailPanel>

export const Default: Story = {
  name: '仕入情報フォーム（API呼び出し→初期状態）',
  args: {
    orderId: 1,
    orderNumber: 'ORD-001',
    onClose: () => {},
  },
}

/**
 * OrderFinancialPanel — デザイントークンカタログ (ADR-067)
 *
 * 受注売上情報フォーム
 * ※ マウント時にAPIでデータを取得するため、Storybook上ではローディング状態で表示される
 *   フォームフィールド・ラベル・ボタンのデザイントークン確認が目的
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import OrderFinancialPanel from './OrderFinancialPanel'

const meta: Meta<typeof OrderFinancialPanel> = {
  title: 'Components/OrderFinancialPanel',
  component: OrderFinancialPanel,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof OrderFinancialPanel>

export const Default: Story = {
  name: '売上情報フォーム（API呼び出し→初期状態）',
  args: {
    orderId: 1,
    orderNumber: 'ORD-001',
    onClose: () => {},
  },
}

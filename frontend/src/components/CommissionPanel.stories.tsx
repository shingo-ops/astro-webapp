/**
 * CommissionPanel — デザイントークンカタログ (ADR-067)
 *
 * 受注担当者報酬パネル
 * ※ マウント時にAPIで報酬データを取得するため、Storybook上ではローディング状態で表示される
 *   ロール・金額・ボタンのデザイントークン確認が目的
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import CommissionPanel from './CommissionPanel'

const meta: Meta<typeof CommissionPanel> = {
  title: 'Components/CommissionPanel',
  component: CommissionPanel,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof CommissionPanel>

export const Default: Story = {
  name: '報酬パネル（API呼び出し→初期状態）',
  args: {
    orderId: 1,
    orderNumber: 'ORD-001',
    onClose: () => {},
    onSaved: () => {},
  },
}

/**
 * MergeCompanyModal — デザイントークンカタログ (ADR-067)
 *
 * 会社重複マージモーダル
 * ※ マウント時にAPIで会社候補を取得するため、Storybook上ではローディング状態で表示される
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import MergeCompanyModal from './MergeCompanyModal'

const meta: Meta<typeof MergeCompanyModal> = {
  title: 'Components/MergeCompanyModal',
  component: MergeCompanyModal,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof MergeCompanyModal>

export const Open: Story = {
  name: 'モーダル表示',
  args: {
    open: true,
    source: { id: 99, name: '株式会社テスト（重複）', company_code: 'C099' },
    onMerged: () => {},
    onCancel: () => {},
  },
}

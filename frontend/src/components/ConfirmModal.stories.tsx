/**
 * ConfirmModal — デザイントークンカタログ (ADR-067)
 *
 * 確認ダイアログの3バリアント（通常・危険・警告）
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import ConfirmModal from './ConfirmModal'

const meta: Meta<typeof ConfirmModal> = {
  title: 'Components/ConfirmModal',
  component: ConfirmModal,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof ConfirmModal>

export const Default: Story = {
  name: '通常確認',
  args: {
    open: true,
    title: '変更を保存しますか？',
    message: '保存すると内容が更新されます。',
    onConfirm: () => {},
    onCancel: () => {},
  },
}

export const Danger: Story = {
  name: '削除確認（danger）',
  args: {
    open: true,
    title: '顧客データを削除しますか？',
    message: 'この操作は取り消せません。顧客に紐づくすべてのデータが削除されます。',
    danger: true,
    confirmLabel: '削除する',
    cancelLabel: 'キャンセル',
    onConfirm: () => {},
    onCancel: () => {},
  },
}

export const CustomLabels: Story = {
  name: 'カスタムラベル',
  args: {
    open: true,
    title: 'サインアウトしますか？',
    message: '未保存のデータは失われます。',
    confirmLabel: 'サインアウト',
    cancelLabel: '戻る',
    onConfirm: () => {},
    onCancel: () => {},
  },
}

/**
 * GoalSetting — デザイントークンカタログ (ADR-067)
 *
 * 新規追加トークン（rgba 直書き禁止対応）の視覚確認:
 * - --success-bg-subtle  保存完了入力フィールド背景
 * ライト / ダークモード両対応
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import './GoalSettingPage.css'

const meta: Meta = {
  title: 'Pages/GoalSetting',
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

// ─────────────────────────────────────────────
// 保存完了状態の入力フィールド（rgba→トークン化）
// ─────────────────────────────────────────────
export const SavedInputState: Story = {
  name: '保存完了状態（--success-bg-subtle）',
  render: () => (
    <div style={{ width: 320 }}>
      <div className="gs-input-wrap">
        <input
          className="gs-input gs-input-saved"
          type="number"
          defaultValue={100}
          style={{ width: '100%' }}
        />
      </div>
      <p style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: 'var(--space-2)' }}>
        保存完了時: border-color → --success, background → --success-bg-subtle
      </p>
    </div>
  ),
}

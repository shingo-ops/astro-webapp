/**
 * Dashboard — デザイントークンカタログ (ADR-067)
 *
 * 新規追加トークン（rgba 直書き禁止対応）の視覚確認:
 * - --danger-bg-subtle  期限超過アイテム背景
 * - --accent-bg-subtle  当日期限アイテム背景
 * - --warning-bg-subtle 停滞アイテム背景
 * ライト / ダークモード両対応
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import './DashboardPage.css'

const meta: Meta = {
  title: 'Pages/Dashboard',
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

// ─────────────────────────────────────────────
// フォローアップアイテムの状態色（rgba→トークン化）
// ─────────────────────────────────────────────
export const FollowupStatusColors: Story = {
  name: 'フォローアップ状態色（ADR-067 rgba トークン）',
  render: () => (
    <div style={{ width: 320 }}>
      <div className="db-followup-item db-overdue" style={{ padding: 'var(--space-3)', marginBottom: 'var(--space-2)', borderRadius: 'var(--radius-md)' }}>
        <span style={{ fontSize: 'var(--font-sm)' }}>期限超過（--danger-bg-subtle）</span>
      </div>
      <div className="db-followup-item db-due-today" style={{ padding: 'var(--space-3)', marginBottom: 'var(--space-2)', borderRadius: 'var(--radius-md)' }}>
        <span style={{ fontSize: 'var(--font-sm)' }}>当日期限（--accent-bg-subtle）</span>
      </div>
      <div className="db-followup-item db-stalled" style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}>
        <span style={{ fontSize: 'var(--font-sm)' }}>停滞中（--warning-bg-subtle）</span>
      </div>
    </div>
  ),
}

// ─────────────────────────────────────────────
// タブナビゲーション
// ─────────────────────────────────────────────
export const Tabs: Story = {
  name: 'タブナビゲーション',
  render: () => (
    <div className="db-controls">
      <div className="db-tabs">
        <button className="db-tab active">月次</button>
        <button className="db-tab">週次</button>
        <button className="db-tab">日次</button>
      </div>
    </div>
  ),
}

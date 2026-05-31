/**
 * ManagementCenter — デザイントークンカタログ (ADR-067)
 *
 * 管理センターのサブナビゲーション・レイアウト確認
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import '../../hub-shell.css'

const meta: Meta = {
  title: 'Pages/ManagementCenter',
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

export const SubNav: Story = {
  name: 'サブナビゲーション',
  render: () => (
    <div className="hub-shell" style={{ height: 400 }}>
      <nav className="hub-subnav">
        <div className="hub-subnav-section">
          <div className="hub-subnav-title">スタッフ管理</div>
          <a href="#" className="hub-subnav-item active">スタッフ一覧</a>
          <a href="#" className="hub-subnav-item">チーム</a>
          <a href="#" className="hub-subnav-item">シフト</a>
        </div>
        <div className="hub-subnav-section">
          <div className="hub-subnav-title">システム設定</div>
          <a href="#" className="hub-subnav-item">ロール・権限</a>
          <a href="#" className="hub-subnav-item">チャンネル</a>
        </div>
      </nav>
      <div className="hub-content">
        <span style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-sm)' }}>
          コンテンツエリア
        </span>
      </div>
    </div>
  ),
}

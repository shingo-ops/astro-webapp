/**
 * ManagementCenter — デザイントークンカタログ (ADR-067)
 *
 * 管理センターのサブナビゲーション・レイアウト確認
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import './ManagementCenterPage.css'

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
    <div className="mc-shell" style={{ height: 400 }}>
      <nav className="mc-subnav">
        <div className="mc-subnav-section">
          <div className="mc-subnav-title">スタッフ管理</div>
          <a href="#" className="mc-subnav-item active">スタッフ一覧</a>
          <a href="#" className="mc-subnav-item">チーム</a>
          <a href="#" className="mc-subnav-item">シフト</a>
        </div>
        <div className="mc-subnav-section">
          <div className="mc-subnav-title">システム設定</div>
          <a href="#" className="mc-subnav-item">ロール・権限</a>
          <a href="#" className="mc-subnav-item">チャンネル</a>
        </div>
      </nav>
      <div className="mc-content">
        <span style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-sm)' }}>
          コンテンツエリア
        </span>
      </div>
    </div>
  ),
}

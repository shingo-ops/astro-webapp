/**
 * Layout（App Shell）— デザイントークンカタログ (ADR-067)
 *
 * サイドバー + トップバーのデザイントークン視覚確認
 * ※ Layout.tsx本体はAuthContext等の多数のContextに依存するため、
 *   CSSクラスを直接使った静的スケルトンでデザイントークンを確認する
 */
import type { Meta, StoryObj } from '@storybook/react-vite'

const meta: Meta = {
  title: 'Components/Layout',
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

// サイドバー折りたたみ状態（collapsed: 54px）
export const CollapsedSidebar: Story = {
  name: 'サイドバー折りたたみ（54px）',
  render: () => (
    <div className="app-shell" style={{ height: '400px', position: 'relative' }}>
      {/* Sidebar */}
      <div style={{
        width: 'var(--sidebar-width-collapsed, 54px)',
        background: 'var(--sidebar-bg)',
        borderRight: '1px solid var(--sidebar-border)',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: 'var(--space-3) 0',
        gap: 'var(--space-2)',
        flexShrink: 0,
      }}>
        {/* アイコン列のダミー */}
        {[...Array(5)].map((_, i) => (
          <div key={i} style={{
            width: 32,
            height: 32,
            borderRadius: 'var(--radius-md)',
            background: 'var(--sidebar-item-bg-hover, var(--bg-subtle))',
            opacity: i === 1 ? 1 : 0.4,
          }} />
        ))}
      </div>
      {/* Main area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* Topbar */}
        <div className="app-topbar">
          <div className="topbar-search" style={{ height: 32 }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
              顧客名またはリードIDで検索...
            </span>
          </div>
        </div>
        {/* Content */}
        <div style={{ padding: 'var(--space-4)', color: 'var(--text-secondary)', fontSize: 'var(--font-sm)' }}>
          コンテンツエリア
        </div>
      </div>
    </div>
  ),
}

// サイドバー展開状態（expanded: 240px）
export const ExpandedSidebar: Story = {
  name: 'サイドバー展開（240px）',
  render: () => (
    <div className="app-shell" style={{ height: '400px', position: 'relative' }}>
      {/* Sidebar */}
      <div style={{
        width: 'var(--sidebar-width-expanded, 240px)',
        background: 'var(--sidebar-bg)',
        borderRight: '1px solid var(--sidebar-border)',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        padding: 'var(--space-3)',
        gap: 'var(--space-1)',
        flexShrink: 0,
      }}>
        {['ダッシュボード', '受信箱', '受注管理', '顧客情報', '設定'].map((label, i) => (
          <div key={i} style={{
            padding: 'var(--space-2) var(--space-3)',
            borderRadius: 'var(--radius-md)',
            background: i === 1 ? 'var(--sidebar-item-bg-active, var(--bg-subtle))' : 'transparent',
            color: i === 1 ? 'var(--sidebar-item-color-active, var(--text-primary))' : 'var(--sidebar-item-color, var(--text-secondary))',
            fontSize: 'var(--font-sm)',
            fontWeight: i === 1 ? 'var(--font-weight-medium)' : 'normal',
          }}>
            {label}
          </div>
        ))}
      </div>
      {/* Main area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="app-topbar">
          <div className="topbar-search" style={{ height: 32 }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
              顧客名またはリードIDで検索...
            </span>
          </div>
        </div>
        <div style={{ padding: 'var(--space-4)', color: 'var(--text-secondary)', fontSize: 'var(--font-sm)' }}>
          コンテンツエリア
        </div>
      </div>
    </div>
  ),
}

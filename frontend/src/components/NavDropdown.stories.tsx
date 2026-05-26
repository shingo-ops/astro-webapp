/**
 * NavDropdown — デザイントークンカタログ (ADR-067)
 *
 * ナビゲーションドロップダウンメニュー（MemoryRouter必須）
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import NavDropdown from './NavDropdown'

const meta: Meta<typeof NavDropdown> = {
  title: 'Components/NavDropdown',
  component: NavDropdown,
  decorators: [
    (Story) => (
      <MemoryRouter>
        <div style={{ padding: 'var(--space-4)', background: 'var(--bg-sidebar, var(--bg-primary))' }}>
          <Story />
        </div>
      </MemoryRouter>
    ),
  ],
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof NavDropdown>

export const Default: Story = {
  name: '標準（閉じた状態）',
  args: {
    label: '受注管理',
    activePaths: ['/orders', '/purchase-orders'],
    children: (
      <>
        <a href="#" className="nav-dropdown-item">受注一覧</a>
        <a href="#" className="nav-dropdown-item">発注一覧</a>
      </>
    ),
  },
}

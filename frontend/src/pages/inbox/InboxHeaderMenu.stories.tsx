/**
 * Inbox ヘッダーメニュー — デザイントークンカタログ (ADR-067)
 *
 * ≤1279px で表示される三点メニューのスタイルを視覚確認するためのカタログ。
 * - .inbox-header-menu-btn  （三点トグルボタン）
 * - .inbox-header-menu      （ドロップダウン本体）
 * - .inbox-header-menu-item （メニュー項目：通常 / danger）
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import './InboxPage.css'

const meta: Meta = {
  title: 'Inbox/HeaderMenu',
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

// ─────────────────────────────────────────────
// 三点ボタン（閉じた状態）
// ─────────────────────────────────────────────
export const ThreeDotButton: Story = {
  name: '三点ボタン（閉じた状態）',
  render: () => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
      {/* ≤1279px で表示される三点ボタン。display:none のデフォルトを上書きして確認 */}
      <button
        type="button"
        className="inbox-header-menu-btn"
        style={{ display: 'flex' }}
        aria-label="その他の操作"
        aria-expanded={false}
        aria-haspopup="menu"
      >
        {/* アイコンはビルド外のため SVG で代替 */}
        <svg width="16" height="16" viewBox="0 0 256 256" aria-hidden="true">
          <circle cx="64" cy="128" r="16" fill="currentColor" />
          <circle cx="128" cy="128" r="16" fill="currentColor" />
          <circle cx="192" cy="128" r="16" fill="currentColor" />
        </svg>
      </button>
      <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
        .inbox-header-menu-btn — var(--border-icon) / var(--radius-md)
      </span>
    </div>
  ),
}

// ─────────────────────────────────────────────
// ドロップダウンメニュー（開いた状態）
// ─────────────────────────────────────────────
export const MenuOpen: Story = {
  name: 'ドロップダウンメニュー（開いた状態）',
  render: () => (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <div role="menu" className="inbox-header-menu" style={{ position: 'relative', display: 'block' }}>
        <button role="menuitem" className="inbox-header-menu-item">
          <svg width="16" height="16" viewBox="0 0 256 256" aria-hidden="true" fill="currentColor">
            <path d="M224,48H32a8,8,0,0,0-8,8V192a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V56A8,8,0,0,0,224,48Z" />
          </svg>
          未読にする
        </button>
        <button role="menuitem" className="inbox-header-menu-item">
          <svg width="16" height="16" viewBox="0 0 256 256" aria-hidden="true" fill="currentColor">
            <path d="M212.24,83.76l-56-56A6,6,0,0,0,152,26H56A14,14,0,0,0,42,40V216a14,14,0,0,0,14,14H200a14,14,0,0,0,14-14V88A6,6,0,0,0,212.24,83.76Z" />
          </svg>
          対象外にする
        </button>
        <button role="menuitem" className="inbox-header-menu-item danger">
          <svg width="16" height="16" viewBox="0 0 256 256" aria-hidden="true" fill="currentColor">
            <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V216a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16Z" />
          </svg>
          削除
        </button>
        <button role="menuitem" className="inbox-header-menu-item">
          <svg width="16" height="16" viewBox="0 0 256 256" aria-hidden="true" fill="currentColor">
            <path d="M229.66,218.34l-50.07-50.07A88,88,0,1,0,165.59,181.59l50.07,50.07a8,8,0,0,0,11.32-11.32ZM40,112a72,72,0,1,1,72,72A72.08,72.08,0,0,1,40,112Z" />
          </svg>
          顧客情報
        </button>
      </div>
    </div>
  ),
}

// ─────────────────────────────────────────────
// メニュー項目スタイルスケール（トークン確認）
// ─────────────────────────────────────────────
export const MenuItemScale: Story = {
  name: 'メニュー項目スタイルスケール（トークン確認）',
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .inbox-header-menu-item — var(--font-sm) / var(--bg-hover) on hover
        </div>
        <div role="menu" className="inbox-header-menu" style={{ position: 'relative', display: 'block' }}>
          <button role="menuitem" className="inbox-header-menu-item">通常アイテム</button>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .inbox-header-menu-item.danger — var(--danger) / var(--danger-bg) on hover
        </div>
        <div role="menu" className="inbox-header-menu" style={{ position: 'relative', display: 'block' }}>
          <button role="menuitem" className="inbox-header-menu-item danger">danger アイテム</button>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .inbox-header-menu — var(--shadow-dropdown) / var(--z-dropdown):50 / min-width:var(--min-width-dropdown)
        </div>
        <div role="menu" className="inbox-header-menu" style={{ position: 'relative', display: 'block' }}>
          <button role="menuitem" className="inbox-header-menu-item">アイテム A</button>
          <button role="menuitem" className="inbox-header-menu-item">アイテム B</button>
          <button role="menuitem" className="inbox-header-menu-item danger">danger</button>
        </div>
      </div>
    </div>
  ),
}

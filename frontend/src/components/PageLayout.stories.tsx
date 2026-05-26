/**
 * PageLayout — デザイントークンカタログ (ADR-067)
 *
 * 全ページ共通のタイトル・サブタイトルレイアウト標準パターン
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import { PageLayout } from './PageLayout'

const meta: Meta<typeof PageLayout> = {
  title: 'Components/PageLayout',
  component: PageLayout,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof PageLayout>

export const TitleOnly: Story = {
  name: 'タイトルのみ',
  args: {
    navKey: 'nav.dashboard',
    children: <div style={{ padding: 'var(--space-4)' }}>コンテンツエリア</div>,
  },
}

export const WithSubtitle: Story = {
  name: 'タイトル + サブタイトル',
  args: {
    navKey: 'nav.leadChat',
    subtitleKey: 'inbox.subtitle',
    children: <div style={{ padding: 'var(--space-4)' }}>コンテンツエリア</div>,
  },
}

export const WithHeaderAction: Story = {
  name: 'ヘッダーアクションボタン付き',
  args: {
    navKey: 'nav.companies',
    headerAction: (
      <button className="btn-primary">+ 新規追加</button>
    ),
    children: <div style={{ padding: 'var(--space-4)' }}>コンテンツエリア</div>,
  },
}

export const WithAll: Story = {
  name: 'フル構成（サブタイトル + アクション）',
  args: {
    navKey: 'nav.orders',
    subtitleKey: 'orders.subtitle',
    headerAction: (
      <button className="btn-primary">+ 受注追加</button>
    ),
    children: <div style={{ padding: 'var(--space-4)' }}>コンテンツエリア</div>,
  },
}

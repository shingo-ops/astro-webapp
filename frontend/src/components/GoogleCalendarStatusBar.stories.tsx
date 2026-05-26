/**
 * GoogleCalendarStatusBar — デザイントークンカタログ (ADR-067)
 *
 * Google Calendar 接続状態バー（3状態）
 * ※ 初期マウント時にAPIを呼ぶため、Storybook上ではloading→エラー状態で表示される
 *   デザイントークン（色・アイコン・フォント）の視覚確認が目的
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import { GoogleCalendarStatusBar } from './GoogleCalendarStatusBar'

const meta: Meta<typeof GoogleCalendarStatusBar> = {
  title: 'Components/GoogleCalendarStatusBar',
  component: GoogleCalendarStatusBar,
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof GoogleCalendarStatusBar>

export const CanManage: Story = {
  name: '管理権限あり（API呼び出し→初期状態）',
  args: {
    canManage: true,
    onReconnect: () => {},
    onConnect: () => {},
  },
}

export const ReadOnly: Story = {
  name: '読み取り専用（管理権限なし）',
  args: {
    canManage: false,
    onReconnect: () => {},
    onConnect: () => {},
  },
}

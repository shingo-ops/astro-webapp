/**
 * Schedule — デザイントークンカタログ (ADR-067)
 *
 * スケジュール/カレンダー固有CSSのデザイントークン確認
 * 今回トークン化した --schedule-day-num-size を含む
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import '../schedule.css'

const meta: Meta = {
  title: 'Pages/Schedule',
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

export const DayHeader: Story = {
  name: '曜日ヘッダー（--schedule-day-num-size 確認）',
  render: () => (
    <div style={{ display: 'flex', gap: 8 }}>
      {['月', '火', '水', '木', '金', '土', '日'].map((day, i) => (
        <div key={day} className="gcal-day-header" style={{ width: 80 }}>
          <div className="gcal-day-header__name">{day}</div>
          <div className={`gcal-day-header__num${i === 2 ? ' today' : ''}`}>
            {i + 19}
          </div>
        </div>
      ))}
    </div>
  ),
}

export const MonthColName: Story = {
  name: '月表示列ヘッダー（--font-2xs 確認）',
  render: () => (
    <div style={{ display: 'flex', gap: 4 }}>
      {['日', '月', '火', '水', '木', '金', '土'].map((day) => (
        <div key={day} className="gcal-month-col-name" style={{ width: 80 }}>
          {day}
        </div>
      ))}
    </div>
  ),
}

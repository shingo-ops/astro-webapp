/**
 * CompanyContactSelector — デザイントークンカタログ (ADR-067)
 *
 * 会社 + 担当者 連動セレクタ
 * ※ マウント時にAPIで会社一覧を取得するため、Storybook上では空セレクタが表示される
 *   セレクト・エラーメッセージのスタイル確認が目的
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter } from 'react-router-dom'
import CompanyContactSelector from './CompanyContactSelector'

const meta: Meta<typeof CompanyContactSelector> = {
  title: 'Components/CompanyContactSelector',
  component: CompanyContactSelector,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
  parameters: { layout: 'padded' },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof CompanyContactSelector>

const mockCompanies = [
  { id: 1, company_code: 'C001', name: '株式会社サンプル' },
  { id: 2, company_code: 'C002', name: 'Sample Corp Ltd.' },
  { id: 3, company_code: 'C003', name: 'テスト商事' },
]

export const Empty: Story = {
  name: '未選択状態',
  args: {
    value: { companyId: null, contactId: null },
    onChange: () => {},
    companies: mockCompanies,
  },
}

export const WithError: Story = {
  name: 'バリデーションエラー表示',
  args: {
    value: { companyId: null, contactId: null },
    onChange: () => {},
    companies: mockCompanies,
    error: '会社を選択してください',
  },
}

export const Disabled: Story = {
  name: '編集ロック状態',
  args: {
    value: { companyId: 1, contactId: null },
    onChange: () => {},
    companies: mockCompanies,
    disabled: true,
  },
}

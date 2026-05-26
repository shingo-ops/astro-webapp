/**
 * Inbox 右パネル — デザイントークンカタログ (ADR-067)
 *
 * このカタログは以下を視覚的に確認するためのものです:
 * - --inbox-panel-label-size (12px ラベル)
 * - --inbox-panel-group-heading-size (11.2px グループ見出し)
 * - ライト / ダークモード両対応
 */
import type { Meta, StoryObj } from '@storybook/react-vite'
import './InboxPage.css'

const meta: Meta = {
  title: 'Inbox/RightPanel',
  parameters: {
    layout: 'padded',
  },
  tags: ['autodocs'],
}
export default meta

type Story = StoryObj

// ─────────────────────────────────────────────
// ラベル + 値 のペア（最も頻出するパターン）
// ─────────────────────────────────────────────
export const FieldRow: Story = {
  name: 'フィールド行（ラベル + 値）',
  render: () => (
    <div style={{ width: 280 }}>
      <div className="right-panel-row">
        <span className="right-panel-label">メールアドレス</span>
        <span className="right-panel-value">taro.yamada@example.com</span>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">電話番号</span>
        <span className="right-panel-value">090-1234-5678</span>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">会社名</span>
        <span className="right-panel-value">株式会社サンプル</span>
      </div>
    </div>
  ),
}

// ─────────────────────────────────────────────
// ラベルのみ（空値状態）
// ─────────────────────────────────────────────
export const LabelOnly: Story = {
  name: 'ラベル単体（値なし状態）',
  render: () => (
    <div style={{ width: 280 }}>
      <div className="right-panel-row">
        <span className="right-panel-label">メールアドレス</span>
        <span className="right-panel-value" style={{ color: 'var(--text-muted)' }}>未設定</span>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">電話番号</span>
        <span className="right-panel-value" style={{ color: 'var(--text-muted)' }}>未設定</span>
      </div>
    </div>
  ),
}

// ─────────────────────────────────────────────
// セクション構造（グループ見出し + フィールド群）
// ─────────────────────────────────────────────
export const SectionWithGroups: Story = {
  name: 'セクション構造（グループ見出し付き）',
  render: () => (
    <div style={{ width: 280 }}>
      <p className="right-panel-section-title">連絡先情報</p>

      <p className="right-panel-group-heading">基本情報</p>
      <div className="right-panel-row">
        <span className="right-panel-label">氏名</span>
        <span className="right-panel-value">山田 太郎</span>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">メールアドレス</span>
        <span className="right-panel-value">taro@example.com</span>
      </div>

      <p className="right-panel-group-heading">会社情報</p>
      <div className="right-panel-row">
        <span className="right-panel-label">会社名</span>
        <span className="right-panel-value">株式会社サンプル</span>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">役職</span>
        <span className="right-panel-value">営業部長</span>
      </div>
    </div>
  ),
}

// ─────────────────────────────────────────────
// タイポグラフィスケール一覧（トークン検証用）
// ─────────────────────────────────────────────
export const TypographyScale: Story = {
  name: 'タイポグラフィスケール（トークン確認）',
  render: () => (
    <div style={{ width: 320, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .right-panel-section-title → var(--font-md) = 16px
        </div>
        <p className="right-panel-section-title" style={{ margin: 0 }}>セクションタイトル</p>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .right-panel-group-heading → var(--inbox-panel-group-heading-size) = var(--font-2xs) ≒ 11.2px
        </div>
        <p className="right-panel-group-heading" style={{ margin: 0, border: 'none', padding: 0 }}>グループ見出し</p>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .right-panel-label → var(--inbox-panel-label-size) = var(--font-xs) = 12px
        </div>
        <span className="right-panel-label">フィールドラベル</span>
      </div>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
          .right-panel-value → var(--font-sm) = 14px
        </div>
        <span className="right-panel-value">フィールド値</span>
      </div>
    </div>
  ),
}

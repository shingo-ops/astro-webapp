# ADR-058: サイドバーから「担当者」メニューを削除し会社ページに統合

## Status
Proposed

## Date
2026-05-21

## Context（背景）

現在、サイドバーの管理メニューに「会社」と「担当者」が独立したメニュー項目として並んでいる。

しかし、データ構造上 Contact（担当者）は Company（会社）の子エンティティであり、以下が確認済みである：

- `contacts.company_id → companies.id NOT NULL`（担当者は必ず会社に属する）
- `GET /companies/{company_id}/contacts` エンドポイントが実装済み
- `CompanyDetailPage` に「担当者」タブが既に実装済み（一覧表示・編集リンクあり）
- `ContactsPage` は `?company_id=N` クエリで会社別フィルタに対応済み

独立したサイドバーメニューとして「担当者」を残すと、ユーザーが「会社→担当者」という階層を意識しにくくなり、UX的にも誤解を招く。

## Decision（決定）

サイドバーの管理メニューから `/contacts`（担当者）エントリを削除する。

担当者への導線は以下に一本化する：
- 会社詳細ページ（`/companies/:id`）内の「担当者」タブ
- 会社一覧ページ（`/companies`）から会社を選択して詳細へ遷移

## Scope

### 変更対象
- `frontend/src/components/Layout.tsx` — `adminItems` から `/contacts` エントリを削除、`activePaths` も更新

### 変更しない
- `ContactsPage`（`/contacts`）自体は削除しない（会社詳細ページの編集リンク先として引き続き使用）
- バックエンド API は一切変更しない
- `CompanyDetailPage` の担当者タブは変更しない

## Consequences（影響）

### ポジティブ
- ナビゲーション構造が B2B データモデル（会社→担当者）と一致する
- 管理メニューの項目数が減り、シンプルになる
- 担当者操作の起点が会社ページに統一され、文脈が明確になる

### ネガティブ・リスク
- 直接 `/contacts` にアクセスしていたユーザーは会社ページ経由に変わる（軽微）
- `ContactsPage` 自体は残るため、URL直打ちは引き続き可能

## Verification（完了条件）

- [ ] 管理メニューに「担当者」が表示されない
- [ ] 会社詳細ページ（`/companies/:id`）の担当者タブから担当者一覧が表示される
- [ ] `/contacts?company_id=N` へのリンクが会社詳細ページから機能する
- [ ] CI（Playwright E2E）グリーン

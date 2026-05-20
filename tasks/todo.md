# Tasks

## 進行中

### [WIP] 会社・担当者ナビを管理メニューへ移動

**ブランチ:** `feature/morimoto/move-companies-contacts-to-admin-nav`

**背景:**
- 会社（`/companies`）・担当者（`/contacts`）はマスタデータであり、営業フロー（リード/商談）とは性質が異なる
- 現状はリードメニュー配下に置かれており、PO判断で管理メニューへ移動する

**変更内容:**
- [x] `frontend/src/components/Layout.tsx` — `leadsItems` から `companies`・`contacts` を削除
- [x] `frontend/src/components/Layout.tsx` — `adminItems` の先頭に `companies`・`contacts` を追加
- [x] `leadsItems` の `activePaths` から `/companies`・`/contacts` を削除
- [x] `adminItems` の `activePaths` に `/companies`・`/contacts` を追加
- [ ] コミット & PR 作成
- [ ] CI 確認

**完了条件:**
- 管理メニュー展開時に「会社」「担当者」が表示される
- リードメニューに「会社」「担当者」が表示されない
- CI 緑

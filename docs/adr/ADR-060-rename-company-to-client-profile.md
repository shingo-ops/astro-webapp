# ADR-060: 「会社」→「顧客情報」/ "Companies" → "Client Profile" リネーム

## Status
Proposed

## Date
2026-05-21

## Context（背景）

現在、会社マスタページは「会社（Companies）」と表記されているが、このページの実際の用途は以下の通りである：

- 成約した顧客の請求先・配送先情報の管理
- 商談中に取得した取引KPI（発注頻度・月間予測額）の管理
- 担当者（contacts）の紐付け管理

「会社」という名称は組織エンティティとしての意味が強く、「成約済み顧客との関係性を管理するマスタ」という目的が伝わりにくい。PO判断により「顧客情報（Client Profile）」にリネームする。

## Decision（決定）

`frontend/src/locales/ja.json` と `frontend/src/locales/en.json` の翻訳値を更新し、全UIで「会社」→「顧客情報」、「Company/Companies」→「Client Profile/Client Profiles」に統一する。

**翻訳キーは変更しない**（ADR-027 i18n ルールに従い、キー名はコードと一致させたまま値のみ変更）。

## Scope

### ja.json 変更対象（値のみ変更、キーは維持）

| キー | 変更前 | 変更後 |
|------|--------|--------|
| `common.company` | 会社 | 顧客情報 |
| `common.companies` | 会社 | 顧客情報 |
| `companies.title` | 会社管理 | 顧客情報管理 |
| `companies.newCompany` | 新規会社登録（存在すれば） | 新規顧客情報 |
| `companies.editCompany` | 会社編集 | 顧客情報編集 |
| `companies.companyCode` | 会社コード | 顧客コード |
| `companies.noCompanies` | 会社が登録されていません | 顧客情報が登録されていません |
| `companies.deleteCompany` | 会社を削除 | 顧客情報を削除 |
| `companies.searchPlaceholder` | 会社名・コードで検索... | 顧客名・コードで検索... |
| `companies.companyCodeLabel` | 会社コード（CO-00001、未指定で自動採番） | 顧客コード（CO-00001、未指定で自動採番） |
| `companies.nameLabel` | 会社名 * | 顧客名 * |
| `companies.allCompanies` | 全会社 | 全顧客情報 |
| `companies.companyLabel` | 所属会社 * | 所属顧客情報 * |
| `companies.primaryContactHint` | 〜（会社あたり 1 人のみ〜） | 〜（顧客情報あたり 1 人のみ〜） |
| `companies.companyRequired` | 所属会社を選択してください | 所属顧客情報を選択してください |
| `companies.dedupResolveDesc` | この会社は〜 | この顧客情報は〜（会社→顧客情報 に置換） |
| `companies.dedupConfirmAsDistinct` | 別会社として確定（active 化） | 別顧客情報として確定（active 化） |
| `companies.dedupMergeHint` | 既存の会社にマージして〜 | 既存の顧客情報にマージして〜 |
| `companies.dedupResolveConfirmMessage` | 〜別会社として〜独立した会社として〜 | 〜別顧客情報として〜独立した顧客情報として〜 |
| `companyContactSelector.selectCompany` | 会社を選択 | 顧客情報を選択 |
| `companyContactSelector.noCompany` | 会社が未選択 | 顧客情報が未選択 |
| `companyContactSelector.companyRequired` | 会社を選択してください | 顧客情報を選択してください |
| `companyContactSelector.contactRequired` | 会社と担当者を選択してください | 顧客情報と担当者を選択してください |
| `companyContactSelector.companyMissing` | 選択中の会社が見つかりません | 選択中の顧客情報が見つかりません |
| `companyContactSelector.companyNotInList` | 指定された会社が〜 | 指定された顧客情報が〜 |
| `mergeCompany.sourceDesc` | 〜既存の会社に吸収〜 | 〜既存の顧客情報に吸収〜 |
| `mergeCompany.selectMaster` | マージ先（master）の会社を選択 | マージ先（master）の顧客情報を選択 |
| `mergeCompany.searchPlaceholder` | 会社名 / 会社コードで絞り込み〜 | 顧客名 / 顧客コードで絞り込み〜 |
| `mergeCompany.resultsCapped` | 〜目的の会社が〜会社名 / 会社コードで〜 | 〜目的の顧客情報が〜顧客名 / 顧客コードで〜 |
| `mergeCompany.noResults` | 該当する会社がありません | 該当する顧客情報がありません |
| `mergeCompany.confirmDesc2` | 〜の会社レコードは削除されます | 〜の顧客情報レコードは削除されます |
| `nav.companies` | 会社 | 顧客情報 |
| `nav.company` | 会社（存在すれば） | 顧客情報 |

### en.json 変更対象（値のみ変更、キーは維持）

同一キーについて以下の置換ルールを適用する：

- `Company` → `Client Profile`
- `Companies` → `Client Profiles`
- `company` → `client profile`（文中の小文字）
- `companies` → `client profiles`（文中の小文字）

### 変更しないもの

- `common.companyName`、`contacts.companyName` 等の「会社名」フィールドラベル（法人名という意味での「会社名」は顧客名に統一）→ 上記テーブルに含める
- バックエンド・DB・APIのカラム名・エンドポイント名（変更なし）
- 翻訳キー名（変更なし）
- `carrierName`（運送会社）など、顧客情報と無関係な「会社」（別概念）

## Consequences（影響）

- 全UIで「顧客情報（Client Profile）」に統一され、ページの目的が明確になる
- バックエンド・DB変更なし（フロントエンドのみ）
- ja.json と en.json のキー数は変更前後で一致を維持（ADR-027準拠）

## Verification（完了条件）

- [ ] サイドバーに「顧客情報」と表示される
- [ ] 顧客情報一覧ページタイトルが「顧客情報管理」になる
- [ ] 顧客情報詳細・編集モーダルのラベルが「顧客情報」系に統一されている
- [ ] `nav.companies` の英語表記が "Client Profiles" になっている
- [ ] ja.json と en.json のキー数が一致している
- [ ] CI（Playwright E2E）グリーン

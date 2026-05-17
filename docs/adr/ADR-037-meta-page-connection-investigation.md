# ADR-037: Meta（Facebook/Instagram）ページ接続経路の現状調査

## ステータス
Draft - 調査フェーズ

## 背景（Context）

Meta App Review審査動画の撮影準備中、tenant_006（Sales Anchor運営テナント）で
Facebookページ接続が失敗する問題が発生した。直接の引き金はBusiness Integration
の手動削除だが、Meta公式ドキュメントとコミュニティ報告から、より根本的な
仕様要因が存在する可能性が判明している。

具体的には、Meta公式は `/me/accounts` について以下を明記している：
"It does not return pages that you are connected with through a business"

つまり Business Manager（Business Portfolio）で管理されているページは、
`business_management` 権限なしでは `/me/accounts` に返ってこない。
v17/v18以降この仕様が厳格化されている。

B2B SaaSとしてのSales Anchorの顧客は、ほぼ全員がページをBusiness Managerで
管理していると想定されるため、これは「特殊な障害」ではなく「構造的なリスク」
である可能性が高い。

ただし、現状のSales Anchorの実装が既にどこまで対応しているかが
コード調査なしには確定できない。本ADRはその調査を依頼するものである。

## What（何を調査するか）

以下の事実をコードとDBから確認し、調査レポート（Markdown）をPRで提出する。
実装変更は本ADRのスコープ外。

### 調査項目1：OAuthスコープの現状

- 現在Sales Anchorが Facebook OAuth 開始時にリクエストしているスコープ一覧
- 特に `business_management` 権限が含まれているか
- 関連ファイル：`meta_graph.py`、OAuth開始エンドポイント、認証コールバック

### 調査項目2：`list_user_pages()` の現状実装

- `/me/accounts` 以外の経路（`/me/businesses`、`/{business-id}/owned_pages` 等）
  を試している箇所があるか
- 空配列が返った場合のエラーハンドリングの挙動
- エラーメッセージのユーザー向け文言

### 調査項目3：既存テナントの接続状態

- `tenant_meta_config` テーブルの全テナント分の状態
- `meta_page_routing` の全レコード
- 接続済みテナントとtenant_006の差異（Business Manager管理ページか否か等、
  推定可能な範囲で）

### 調査項目4：既存ADRとの整合性

- Meta/Facebook接続に関する既存ADRの有無
- 設計上の制約・決定事項の一覧
- 本件で参照すべき過去の意思決定（ADR-024, ADR-025, ADR-028含む）

### 調査項目5：所見の提示

上記を踏まえて、Claude Codeとして以下の所見を提示する：

- フォールバック実装の選択肢（`business_management` 権限経由 / System User Token方式 / その他）
- それぞれのオプションで、Meta App Reviewへの影響
- 現状のコードに対する変更影響範囲の概算
- 推奨案と、その判断根拠

## Why（なぜこの調査が必要か）

- フォールバック実装のADRを起案する前に、現状の権限スコープ・実装状態が
  確定していないと、的外れな設計判断になるリスクがある
- 特に「Sales Anchorが既に `business_management` 権限を取得済みかどうか」
  によって、必要な作業範囲が大きく変わる
  - 取得済み → 実装追加のみ
  - 未取得 → Meta App Reviewのスコープ追加が先になり、撮影シナリオにも影響
- Shingoのtenant_006の問題が「特殊ケース」か「構造的問題」かを切り分ける
  必要がある

## Scope外

- 実装変更そのもの（本ADRは調査のみ）
- Meta Developer Console上の操作（コード外の作業）
- Meta App Reviewの手続き
- Business Integration削除後の自動リカバリー（Meta側の仕様で原理的に不可能）

## 出力形式

- `docs/research/` 配下に調査レポートを配置（ディレクトリがなければ作成）
- 「現状の事実（コード/DBから確認できたこと）」と
  「Claude Codeの所見（推論を含む判断）」を明確に分けて記述
- 調査結果に基づき、後続ADR起案時の論点を箇条書きで列挙

## 事業上の制約

- Meta App Review審査動画の撮影が止まっている。調査結果次第で「先に撮影」
  「先に実装してから撮影」の判断が分かれる
- 本番テナント（tenant_006以外）への影響は現時点で不明。調査項目3で確認する

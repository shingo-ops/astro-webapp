# ADR-059: リードナビゲーションをアコーディオン→クリック＋ページ内タブに統一

## Status
Accepted

## Date
2026-05-21

## Context
サイドバーの「リード」メニューが SidebarAccordion（展開式ドロップダウン）で実装されており、
リードチャット/新規リード/ルート顧客/アーカイブの4サブアイテムが展開表示される。
UX改善として、メニュークリック1回でリードページに遷移し、
ページ内タブ（すべて/新規/既存/アーカイブ）で絞り込む仕様に変更する。

## Decision
1. SidebarAccordion → NavLink（シングルクリック）に置換
2. /leads ページに LeadTabs コンポーネントを追加（URL searchParam: ?tab=）
   - すべて: GET /leads（全status）
   - 新規:   GET /leads（LeadsPage の既存挙動そのまま）
   - 既存:   GET /customers（CustomersPage のコンテンツを流用）
   - アーカイブ: GET /archives?source_table=leads（ArchivesPage のコンテンツを流用）
3. /customers, /archive ルートは維持（既存URLの後方互換）

## DB 影響エビデンス
- leads.status: インデックス済み → タブフィルタに使用可能
- customers テーブル: 既存エンドポイントをそのまま使用
- archives.source_table: 'leads' フィルタ対応済み
- **スキーマ変更ゼロ・マイグレーション不要**

## Consequences
- サイドバーのメニュー項目が減り、UX がシンプルになる
- リードチャット（/lead-chat）は引き続き独立したサイドバーリンクで維持
- /customers, /archive の直接アクセスは引き続き動作する

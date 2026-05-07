# Q01: ADR-015 リード管理モジュール — スコープ確定と既存ステータス衝突の確認

**Date**: 2026-05-07
**Asked by**: Claude Code (パートナー実装担当)
**Blocking**: ADR-015 の全実装（§1〜§7）

---

## なぜ止まったか

ADR-015 はリード管理モジュール全体の **設計指針 ADR**（Status: Proposed）であり、
他 ADR と異なり **個別の Acceptance Criteria（AC-XXX）が定義されていない**。
スコープが §1〜§7 にまたがり、以下のいずれを実装してもおよそ別 PR 1 本分に
なる規模である:

- §1 / §2 AI 自動収集ロジック（Q1 国 → Q2 タイトル）
- §3 新規リードフロー（Webhook と統合・既存顧客 dedup）
- §4 カルテの AI 補助（Qwen3 8B + Claude Haiku 4.5 呼び出し）
- §5 ダッシュボード再設計（OVERDUE / TODAY / TOMORROW / UPCOMING）
- §6 ステータス再設計（**既存実装と衝突あり、後述**）
- §7 テナントプレイブック（質問文・順番・アサイン条件のテナント別設定）

CLAUDE.md §「不可逆操作は必ず PO 確認」および「シンプル第一・影響を最小化」原則
に照らし、複数の **破壊的変更を含む** 設計判断について PO（しんごさん）の
明示確認を取るべきと判断した。

---

## 確認したい論点

### Q1-A. 実装の分割方針

ADR-015 は単一 PR には収まらない。以下のどちらで進めるか:

- **(A) 段階分割**: ADR-015 を複数 PR に分け、本 PR では「下回り（§7 プレイブック
  テーブル + §1/§2 用の AI 収集ステート + §4 用カルテ追加列）のみ」を実装。
  続く ADR-015a / 015b / 015c で AI 連携・ダッシュボード・ステータス移行を扱う。
- **(B) ADR の再分割**: ADR-015 を 015-foundation / 015-ai-collection /
  015-dashboard / 015-status-migration に分割し、Web Claude 側で個別 ADR を
  起こしてから順に実装する（推奨：粒度が claude-pipeline と整合）。

### Q1-B. ステータス再設計の既存実装との衝突 ⚠️

§6 のステータス設計と現行 `LeadStatus` enum
（`backend/app/schemas/lead.py:21-27`）が **不整合**:

| ADR-015 §6 | 現行 LeadStatus |
|---|---|
| 新規（AI対応中） | `new = "新規"` |
| 商談中 | `contacting / proposing` |
| 既存顧客 | （なし） |
| アーカイブ（追客短期/長期/失注/対象外） | `lost`, `on_hold`（一部） |

加えて `prospect_rank` 自動算出ロジック（leads.py:53-99 / `compute_prospect_rank`）が
温度感・規模・返信速度から A / B+ / B / B- / 仮C / 確定C を計算している。
ADR-015 §4 では「温度感は人間のみ」「規模は自動」とあり、**ランク自動算出の
前提が変わる**可能性がある。

確認したいこと:

- (1) §6 のステータスは **既存の日本語 enum を置き換える** か、それとも **既存に追加**する形か？
- (2) 既存 `prospect_rank` ロジック（A/B+/B/B-/仮C/確定C）は維持するか、撤廃するか？
- (3) `本番テナント highlife-jpn` に **既存リードデータ** が入っている場合、
  ステータス値の移行スクリプトが必要。実行可否は PO 判断（CLAUDE.md「不可逆操作」）。

### Q1-C. ダッシュボード再設計（§5）の既存ダッシュボードとの関係

`backend/app/routers/dashboard.py` および `tasks/dashboard.py` に **KPI キャッシュ
（schema_version=2）** の実装が既にある。§5 の OVERDUE / TODAY / TOMORROW /
UPCOMING は **新規ビュー** として既存 KPI ダッシュボードと並存させるか、
ダッシュボード自体を置き換えるか？

「次回アクション日」フィールドは現状 `leads` / `deals` のいずれにも存在しない。
新カラムを `deals` に追加する想定で良いか（§4 の「次回アクション日」は商談中の
属性として読める）？

### Q1-D. LLM 接続の前提

§4 で「Qwen3 8B（ASTRO FORCE Server B）」と「Claude Haiku 4.5 API」の使用が
指定されている。実装前に確認したい:

- (1) ASTRO FORCE Server B の **エンドポイント URL / API スキーマ** は決まっているか？
  （OpenAI 互換？vLLM？それともカスタム？）
- (2) Claude Haiku 4.5 API の **API キー** は環境変数で渡される予定か？
  本番 / dev のどこに置くか？
- (3) コスト制限の上限（ADR §事業上の制約「月 ¥60〜210/月」）の **強制機構**は
  必要か？それとも運用監視のみで足りるか？

### Q1-E. AI が触る顧客 dedup（§3）の判定キー

「SNS ID で顧客検索」とあるが、現行 `customers` / `contacts` テーブルに
**Discord/Messenger/Instagram/Telegram の ID** をどこに格納するか未定:

- 現行 `customer_contact_channels`（migration 026）は Discord 専用設計
- Messenger PSID / Instagram IGSID は `meta_messages.sender_id` にしかない
- Telegram は連携自体まだ存在しない（exploration 結果より）

dedup に必要なテーブル拡張は本 ADR スコープか、別 ADR か？

---

## 提案

CLAUDE.md §「コア原則 — シンプル第一・影響を最小化」および ADR-012「What/How
分離」に従い、以下の進め方を提案する:

1. **本 PR ではコミットしない**。Q1-A〜Q1-E の回答を待つ。
2. PO 回答後、Web Claude 側で **ADR-015 を foundation / ai-collection /
   dashboard / status-migration に分割再起案** することを推奨。
3. 分割後、各 ADR に明示的な AC-XXX を付与し、claude-pipeline で順次実装。

**待機中**: 本 PR には実装変更を含めず、本ファイルのみコミットして PO 判断を仰ぐ。

---

## 参考（コードベース実態調査ログ）

- 最新マイグレーション: #045 `add_meta_messages_page_id`
- 既存リードルーター: `backend/app/routers/leads.py`（1,157 行、Meta 送受信を含む）
- 既存スキーマ: `backend/app/schemas/lead.py`（LeadStatus enum を含む）
- 既存ダッシュボード: `backend/app/routers/dashboard.py` / `tasks/dashboard.py`
- マルチテナントパターン: `tenant_{NNN}` schema prefix（`backend/app/auth/dependencies.py:173`）
- Discord 通知ヘルパー: `backend/app/routers/notifications.py:101` `send_discord_notification()`
- 既存 LLM クライアント: **なし**（新規作成必要）
- 既存 `analyzeDeal` 関数: **なし**（新規作成必要）

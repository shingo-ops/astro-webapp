# Phase 1-E Follow-up Backlog

| 項目 | 内容 |
|---|---|
| ステータス | **9 / 16 medium・low 完了 + high 全 5 完了 + 追加 follow-up 多数（2026-04-30 18:30 更新）** |
| 作成日 | 2026-04-30 |
| 元ソース | Sprint 1〜6 の Evaluator / Reviewer レポート、および Generator の Known Limitations |
| 対象 | Phase 1-E（Phase 1-D 直後の次フェーズ） |

このドキュメントは Phase 1-D Sprint 1〜6 で **意図的に Phase 1-E に持ち越した** 改善項目を網羅する。優先度は **high / medium / low** で分類。

## 進捗サマリ（2026-04-30 時点）

### High Priority（5 / 5 完了 ✅）
- ✅ F1-S2 Page Access Token 60 日リフレッシュ Cron (PR #215, #216, #218 v2)
- ✅ F2-S3 Playwright E2E (PR #221)
- ✅ F3-S2 PostgreSQL CI 構築 (PR #214 v1, #218 v2)
- ✅ F4-S5 force_human_agent_tag UI (PR #213)
- ✅ F5-S2 Backend lifespan unit テスト (PR #212)

### Medium Priority（4 / 11 完了）
- ✅ F6-S2 401/403 統合テスト (PR #228)
- ✅ F7-S2 OAuth scope エンコード検証 (PR #229)
- ✅ F9-S4 audit_log（mark-read 呼び出し）ミニ版 (PR #227、firebase_uid 列追加は別 follow-up)
- ✅ F10-S4 cursor pagination — **実質完了**（Sprint 5 で `before` 実装済 + test_messages.py で検証済）
- ⏳ F8-S3 failed_pages Frontend 表示 — **実質完了確認**（Sprint 3 OAuthCallbackPage の partial パターンで対応済）
- ⏳ F11-S5 SQLite フォールバック削除 — **当面 skip 推奨**（既存 SQLite テストへの破壊的影響が大、F3-S2 v2 で PostgreSQL CI 構築済のため緊急性低）
- ⏳ F12-S5 送信失敗バブル赤枠 (PR #223 完了)
- ⏳ F13-S5 polling 二重取得最適化 (PR #224 完了)
- ⏳ F14-S5 複数 Page 対応 Inbox フィルタ — 規模 1d、frontend のみ
- ⏳ F15-S6 customer_name の Graph API 補完 — 規模 1d、Webhook 拡張
- ⏳ F16-S6 PostgreSQL マルチテナント検索 N+1 — 規模 0.5d、view migration 追加

### Low Priority（5 / 8 完了）
- ✅ F17-S6 添付メタデータ対応 — 一部対応：`error_code` 等は migration 041 で追加済、添付バイナリは Phase 2 で対応
- ⏳ F18-S6 SQLite 用 auth_events ミドルウェア — F11-S5 とセット、当面 skip
- ⏳ F19-S6 Discord 通知 platform 表記 — Sprint 6 で既解消（PR #222 で確認）
- ⏳ F20-S2 SQLite RLS skip テスト — F3-S2 v2 で PostgreSQL CI 構築済、現状の skipif で機能上問題なし
- ⏳ F21-S3 ChannelsPage Vitest テスト — 別途 frontend テストインフラ整備が必要
- ⏳ F22-S3 ?status=partial URL パラメータ仕様 (PR #222 完了)
- ⏳ F23-S3 Channels リンク表示名統一 (PR #222 完了)
- ⏳ F24-S5 lib/messages.ts さらなる集約 (PR #226 完了)

### 廃止予定 / Phase 1-E 着手時に対応
- ⏳ F25-S6 META_PAGE_ID 環境変数の削除 — 後方互換 fallback として残置中、Phase 1-E 着手時に判断

### 追加項目（Phase 1-D 後に発生）
- ⏳ F9-S4 拡張版: audit_logs に firebase_uid 列追加 + record_audit_log 引数拡張（migration 必要、規模 0.5d）
- ⏳ F3-S2 v3: 既存 backend テストを PostgreSQL でも動かす（pytest --rls-postgres 等のオプション化、規模 1-2d）

---

---

## 凡例

| 列 | 意味 |
|---|---|
| ID | 連番 + 元 Sprint 番号 |
| 優先度 | **high** = 本番運用で実害あり/Meta 審査リスク / **medium** = UX 改善 / **low** = 内部品質 |
| 元 Sprint | 提起された Sprint 番号 |
| 元レポート | 提起元（Reviewer / Evaluator / Generator） |
| 工数目安 | 0.5d / 1d / 2d+ |

---

## 1. High Priority（本番運用 / 審査リスク）

### F1-S2. Page Access Token 60 日リフレッシュ Cron

- **元 Sprint**: 2 (Reviewer)
- **問題**: 長期 Page Access Token は 60 日で失効。現状は失効後に再 OAuth が必要で、リフレッシュ自動化なし
- **影響**: 60 日後にメッセージ送受信が止まり、運用ダウン
- **対応**:
  - `tenant_meta_config.last_token_refreshed_at` 列を活用
  - Celery beat で日次 Cron、`expires_at - 7d` 以内で `/oauth/access_token?grant_type=fb_exchange_token` を呼ぶ
  - 失敗時は audit_log + Discord 通知
  - UI に「Token 期限切れ間近」警告（既存 page_token_expires_at を表示）
- **工数目安**: 1d
- **依存**: なし

### F2-S3. Playwright E2E 自動化（7 シーン）

- **元 Sprint**: 3, 7 (Generator)
- **問題**: Sprint 7 で Use Case Descriptions §2 の 7 シーンを撮影台本でカバーしたが、自動化 E2E は未実装
- **影響**: 回帰検出が手動撮影リハ依存。CI でブロックできない
- **対応**:
  - Playwright を frontend に追加
  - `tests/e2e/meta-inbox-7-scenarios.spec.ts` で 7 シーン再現
  - mock-meta-api サーバー（既存 `pytest-httpx` の延長）で OAuth/Send API を mock
  - GitHub Actions で nightly 実行
- **工数目安**: 2-3d
- **依存**: テスト用 Test User 認証情報（しんごさん）

### F3-S2. PostgreSQL CI 構築

- **元 Sprint**: 2, 3 (Reviewer)
- **問題**: 現状 CI は SQLite。PostgreSQL 固有の RLS / JSONB / 部分 INDEX / Fernet BYTEA をリポジトリで毎回手動確認
- **影響**: PR ごとに PostgreSQL 固有 regression を見逃す可能性
- **対応**:
  - GitHub Actions の services に postgres:15 追加
  - `tests/conftest.py` で DATABASE_URL を分岐
  - test_rls_*.py の `pytest.skip` を解除して常時実行
- **工数目安**: 1d
- **依存**: GitHub Actions の billing 確認（時間消費）

### F4-S5. force_human_agent_tag UI 表示

- **元 Sprint**: 5 (Evaluator I1)
- **問題**: 24h-7d 範囲で自動的に `MESSAGE_TAG=HUMAN_AGENT` が適用されるが、Frontend の送信フォームでは「自動付与中」の表示がなく、ユーザーが意識しない
- **影響**: Meta 審査担当が「Human Agent Tag が明示的に使われている」と判定しない可能性（Sprint 7 撮影で補完するが、運用フローでも明示が望ましい）
- **対応**:
  - InboxPage の messaging_window バナーに「Human Agent Tag を付与して送信します」を表示
  - 24h 内なら「Standard Messaging」表示
  - 強制 Human Agent Tag を staff が ON/OFF できる toggle 追加（運用回避用）
- **工数目安**: 0.5d
- **依存**: なし

### F5-S2. Backend lifespan unit テスト

- **元 Sprint**: 2 (Generator Known Limitations)
- **問題**: 起動時の Fernet 鍵検証 (`ENFORCE_METADATA_FERNET_KEY=1` の fail-fast) が unit テストで網羅されていない（実機起動でしか検証できていない）
- **影響**: 起動時に regression が出ても CI で検出できない
- **対応**:
  - `tests/test_lifespan.py` 新規
  - lifespan event を直接 invoke、env を変えて成功/失敗を検証
- **工数目安**: 0.5d
- **依存**: なし

---

## 2. Medium Priority（UX 改善）

### F6-S2. 401/403 統合テスト

- **元 Sprint**: 2 (Generator Known Limitations)
- **問題**: meta_inbox.py の各 endpoint が require_permission ガード済だが、auth missing → 401, perm missing → 403 の網羅統合テストが無い
- **対応**: `tests/test_meta_inbox_auth.py` 新規、4 endpoint × 2 (401/403) = 8 ケース
- **工数目安**: 0.5d

### F7-S2. OAuth scope エンコード検証

- **元 Sprint**: 2 (Generator Known Limitations)
- **問題**: scope パラメータがカンマ区切りで URL エンコードされている前提だが、テストで scope 文字列の正確性を assert していない
- **対応**: `test_meta_inbox_oauth.py` に scope 文字列の RegEx assert 追加
- **工数目安**: 0.5d

### F8-S3. failed_pages Frontend 表示

- **元 Sprint**: 2, 3 (Reviewer)
- **問題**: OAuth callback 時に一部の Page で subscribed_apps 登録失敗した場合、レスポンスに failed_pages が含まれる予定だが、Frontend での表示が未実装
- **対応**: ChannelsPage で warning バナー、failed_pages を一覧表示し再試行ボタン
- **工数目安**: 1d

### F9-S4. audit_log に user_id 併記

- **元 Sprint**: 4 (Reviewer F2)
- **問題**: messages mark-read の audit_log で staff_id のみ、user_id（Firebase UID）が記録されていない
- **対応**: insert_audit_log の引数に user_id 追加、既存呼び出し全箇所更新
- **工数目安**: 0.5d

### F10-S4. cursor pagination（messages）

- **元 Sprint**: 4 (Reviewer F3, F4)
- **問題**: `?before=<id>` の単純カーソル。長期間で性能劣化の可能性、また同 created_at の境界で取りこぼし
- **対応**: cursor を `(created_at, id)` 複合に変更、結果は `next_cursor` として返却
- **工数目安**: 1d

### F11-S5. SQLite フォールバック削除

- **元 Sprint**: 5 (Evaluator I3)
- **問題**: meta_inbox.py / leads.py 内に SQLite 用フォールバックコードが残っており（dead code）、PostgreSQL 一本化後に削除推奨
- **対応**: SQLite 分岐を削除、テストは PostgreSQL CI に移行（F3-S2 とセット）
- **工数目安**: 0.5d
- **依存**: F3-S2

### F12-S5. 送信失敗バブル赤枠

- **元 Sprint**: 5 (Evaluator I4)
- **問題**: 送信失敗時、現状は alert ポップアップのみ。バブル自体が赤くハイライトされる仕様は spec §4-2 で言及済だが UI 未実装
- **対応**: InboxPage で `error_code IS NOT NULL` のメッセージバブルに赤枠 CSS 適用
- **工数目安**: 0.5d

### F13-S5. 送信後 polling 二重取得最適化

- **元 Sprint**: 5 (Evaluator I5)
- **問題**: 送信成功後に楽観的 UI 更新 + 10s polling の両方が走り、同じメッセージが二重取得される瞬間がある（dedup されるので実害なし）
- **対応**: 楽観的 UI に `pendingId` を入れ、polling 結果で重複検出時にマージ
- **工数目安**: 0.5d

### F14-S5. 複数 Page 対応 Inbox フィルタ

- **元 Sprint**: 5 (Evaluator I2)
- **問題**: 1 テナントで複数 Page 接続済の場合、Inbox は全 Page の会話を統合表示。Page ごとフィルタ未実装
- **対応**: InboxPage に Page 選択ドロップダウン追加、`?page_id=` クエリで絞込
- **工数目安**: 1d

### F15-S6. customer_name の Graph API 補完

- **元 Sprint**: 4, 6 (Reviewer F2)
- **問題**: 受信メッセージから自動作成された lead の customer_name が PSID/IGSID 文字列のまま
- **対応**: Webhook 受信時に Graph API `/{psid}?fields=name` を呼んで lead.customer_name を更新（Page Scoped User の name は Permission `pages_messaging` で取得可能）
- **工数目安**: 1d

### F16-S6. PostgreSQL マルチテナント検索 N+1 解消

- **元 Sprint**: 6 (Reviewer F4)
- **問題**: webhook.py で active 全テナントを順次 SELECT して page_id 逆引き。テナント数 N で線形
- **対応**: `meta_page_routing` view を public schema に作成、page_id → (tenant_id, schema) を 1 回で解決
- **工数目安**: 1d
- **依存**: 各テナント schema 統合管理（既存）

---

## 3. Low Priority（内部品質）

### F17-S6. 添付メタデータ対応

- **元 Sprint**: 6 (Reviewer F3)
- **問題**: Webhook で attachment 受信時、`raw_payload` には記録されるが `meta_messages.message_text` は空文字。UI には何も出ない
- **対応**: `attachments` JSONB 列追加、Inbox に「画像添付」「動画添付」のプレースホルダ表示
- **工数目安**: 1d
- **依存**: 仕様確定（添付プレビューの可否）

### F18-S6. SQLite 用 auth_events ミドルウェア

- **元 Sprint**: 6 (Reviewer F5)
- **問題**: PostgreSQL 用 audit_logs ミドルウェアは稼働中、SQLite では未対応
- **対応**: SQLite 分岐削除と同時に消滅予定（F11-S5 / F3-S2 とセット）
- **工数目安**: 0d（F11-S5 で吸収）

### F19-S6. Discord 通知 platform 表記

- **元 Sprint**: 6 (Reviewer F6)
- **問題**: Discord 通知のタイトルが「[Inbox] 新規メッセージ」のみ、platform (Messenger/Instagram) が分からない
- **対応**: タイトルに platform 表記追加 → spec § にも追記
- **工数目安**: 0.5d

### F20-S2. SQLite RLS skip テスト

- **元 Sprint**: 2 (Reviewer)
- **問題**: PostgreSQL CI 整備後、`pytest.skip` を解除すべき
- **対応**: F3-S2 完了後に skip 解除
- **工数目安**: 0d（F3-S2 で吸収）

### F21-S3. ChannelsPage Vitest テスト

- **元 Sprint**: 3 (Reviewer)
- **問題**: Frontend に Vitest 未導入。ChannelsPage / OAuthCallbackPage のロジックが unit test されていない
- **対応**: Vitest 導入 + msw で API mock + 主要状態（Active / Inactive / Pending）レンダリング検証
- **工数目安**: 1.5d

### F22-S3. `?status=partial` URL パラメータ仕様

- **元 Sprint**: 3 (Reviewer)
- **問題**: OAuth callback 後の Frontend redirect で `?status=partial` を使う実装と spec の整合性が曖昧
- **対応**: spec §3-2 と implementation を一致させる、もしくは仕様明文化
- **工数目安**: 0.25d

### F23-S3. Channels リンク表示名統一

- **元 Sprint**: 3 (Reviewer)
- **問題**: ナビメニューでは「Channels」、画面タイトルでは「チャンネル設定」など揺れ
- **対応**: 仕様書側で表示名統一
- **工数目安**: 0.25d

### F24-S5. lib/messages.ts さらなる集約

- **元 Sprint**: 5 (Reviewer F3 informational)
- **問題**: platform 推論ロジックが InboxPage と lib/messages.ts に散在
- **対応**: lib/messages.ts に `inferPlatform(lead)` ヘルパー追加して DRY 化
- **工数目安**: 0.5d

---

## 4. 廃止予定 / Phase 1-E 着手時に対応

### F25-S6. META_PAGE_ID 環境変数の削除

- **元 Sprint**: spec §14 Q6
- **問題**: Phase 1-D 完了後の fallback として残置中
- **対応**: Phase 1-E 着手時に webhook.py / meta_inbox.py の参照を削除、.env.example からも削除
- **工数目安**: 0.25d

---

## 5. 集計

| 優先度 | 件数 | 工数目安合計 |
|---|---|---|
| high | 5 | 5-6d |
| medium | 11 | 8-9d |
| low | 8 | 4-5d |
| 廃止予定 | 1 | 0.25d |
| **合計** | **25** | **17-20d** |

Phase 1-E は 4 週間（20 営業日）程度を想定。優先度 high のみ着手しても 1 週間で完了可能。

---

## 6. 関連ドキュメント

- 仕様書本体: `.claude-pipeline/spec.md`
- Phase 1-D 全体ドキュメント: `docs/PHASE_1D_META_INBOX_OVERVIEW.md`
- 各 Sprint の Reviewer レポート: `.claude-pipeline/sprint-N-reviewer-report.md`
- 各 Sprint の Evaluator レポート: `.claude-pipeline/sprint-N-evaluator-report.md`

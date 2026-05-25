# ADR-009: Discord 連携 Bot 常駐アーキテクチャ

| 項目 | 内容 |
|------|------|
| ステータス | **Accepted**（2026-04-28 しんごさん確認完了、Q1/Q2/Q4/Q5 確定） |
| 起草者 | 開発パートナー（Claude Code 経由） |
| 起草日 | 2026-04-27 |
| 受諾日 | 2026-04-28 |
| 関連 ADR | ADR-007 データ階層化戦略、ADR-008 Supplier Intelligence |
| 関連設計書 | `salesanchor_system_overview.docx` 第8章 8-2、`salesanchor_staff_roles_bots_design.docx` 第4章、`migrate_staff_roles_bots.md` 第3-5節 |
| 関連実装 | `backend/app/routers/bots.py`、`backend/app/services/tenant.py`、`migrations/020_create_bots_and_senders_view.sql`、`migrations/022_staff_bots_rls_policies.sql`、`migrations/024_add_staff_bots_permissions.sql` |
| 対象フェーズ | Phase 3（リード・会話・商談 / Discord インバウンド受信開始時） |

---

## 1. 背景 / Context

### 1-1. 現状

Sales Anchor はマルチテナント B2B SaaS として、海外顧客との DM ベース営業を扱う。インバウンドメッセージング基盤は **Phase 2 で Meta Messenger（Facebook Messenger / Instagram DM）が稼働済み**で、`raw_webhook_events` → `meta_messages` → `leads` 自動登録のフローが確立している（`backend/app/routers/webhook.py`）。

仕様書 8-2 ADR-009 として、Discord 連携の常駐アーキテクチャを起草することが求められている（仕様書原文：1段落）。

### 1-2. Discord 固有の要件

Meta Webhook と異なり、Discord のメッセージ受信には **Gateway API（WebSocket）への常時接続**が必須である（HTTP webhook 受信は「Interactions」用途に限定され、通常 DM/ギルドメッセージの取得には使えない）。これにより以下の論点が発生する：

- **常駐プロセス必須**: backend の FastAPI とは別に、WebSocket セッションを維持し続けるワーカーが必要。再起動時の session resume・heartbeat 管理が要る。
- **既製 Bot との共存**: HIGH LIFE JPN の Discord ギルドには **Tickets Bot**（チケット起票・カスタマーサポート用）と **John-Bot**（自社運用の汎用 Bot、用途未確定）が既に常駐している。Jarvis 側 Bot を投入する際、役割重複・コマンド衝突を避ける必要がある。
- **マルチテナント運用形態**: テナントごとに別 Bot を運用するか、Jarvis 全体で 1 Bot を共有するかは、Bot 数の Discord 側上限・運用コスト・テナント間データ隔離リスクに直結する設計判断。
- **Sharding**: Discord は Bot が 2,500 ギルド超で sharding を強制するが、現状 Jarvis のテナントは 1 件（HIGH LIFE JPN）でギルドも 1 つ。当面は単 shard 運用で問題ないが、設計上は将来拡張可能としておく。

### 1-3. 顧客マスタ・スタッフ管理との連携

Phase 1-B の `bots` テーブルには既に `discord_user_id` 列があり、bot を Discord 側のユーザーとして見せる前提の DB 設計になっている（`v_senders` ビューで staff と UNION）。本 ADR はこの DB 構造を**前提**として活かし、Gateway 接続の常駐プロセスをどこに配置するかを定める。

---

## 2. ゴールと非ゴール

### 2-1. ゴール（G）

- **G1**: Discord ギルド／DM の双方向メッセージング（受信・送信）を、Meta Messenger と同じ抽象（`raw_webhook_events` 経由 → `conversations` への永続化）に流し込めること。
- **G2**: 既製 Bot（Tickets Bot / John-Bot）と Jarvis Bot の役割分担を明文化し、運用上の衝突を排除すること。
- **G3**: マルチテナント運用において、Bot トークンの漏洩・テナント越境を構造的に防ぐこと。
- **G4**: 2 GB メモリ VPS（available ~418 MB、2026-04-28 実測）の制約下で、安定稼働できる軽量プロセス構成にすること。
- **G5**: 既存 `bots` テーブル / `v_senders` ビュー / `bots.discord_user_id` の設計を**変更せず**そのまま活用すること。

### 2-2. 非ゴール（NG）

- **NG1**: Discord OAuth2 によるユーザー側ログイン（Discord アカウントを Jarvis のログイン手段にする機能）は本 ADR のスコープ外。Jarvis は引き続き Google Identity Platform を一次認証とする。
- **NG2**: Sharding の本実装は**設計記載のみ**。実装は 2,500 ギルド到達時に再検討（現状 1 ギルド以下）。
- **NG3**: Voice / Stage / Slash Command 開発フレームワーク的機能は対象外。Jarvis Bot は**メッセージ授受**にのみ責務を持つ。
- **NG4**: 既製 Bot（Tickets / John-Bot）の置き換えは行わない。役割分担で共存する。
- **NG5**: Discord メッセージへの AI 自動返信機能（Claude API 経由など）は別 ADR（ADR-008 系列）で扱う。

---

## 3. 検討した代替案

### 案 A: 既製 Bot のみ利用、Jarvis 自前 Bot なし

Tickets Bot / John-Bot のチャネル webhook 出力を Jarvis の HTTP エンドポイントに転送し、Jarvis 側は受信だけ行う。

| 観点 | 評価 |
|------|------|
| 実装コスト | 低（既製 Bot に webhook 設定するだけ） |
| 双方向送信 | **不可**（既製 Bot 経由で Jarvis から DM 送信できない） |
| 既存 `bots.discord_user_id` 設計との整合 | 非整合（Jarvis 自体が Discord ユーザーを持たないため `v_senders` のメリットが消える） |
| 拡張性 | 低（Tickets Bot 機能の範囲に縛られる） |
| **採否** | **不採用**：双方向通信が必須要件のため |

### 案 B: Jarvis 自前 Bot を Gateway 接続して全機能内製化

Tickets Bot / John-Bot を撤去し、Jarvis Bot 1 つで全機能（チケット起票・FAQ 応答・営業 DM など）を提供する。

| 観点 | 評価 |
|------|------|
| 実装コスト | **高**（チケット管理 UI / SLA タイマー / FAQ などを再実装） |
| 機能空白期間 | 大（既製 Bot 廃止 → Jarvis 側完成までサポート停止） |
| 既製 Bot の運用知見廃棄 | あり（Tickets Bot の運用ノウハウが無駄になる） |
| **採否** | **不採用**：投資対効果が悪い |

### 案 C: ハイブリッド（既製 Bot + 自前 Bot を役割分担）【採用】

- **Tickets Bot / John-Bot**: 既存の役割（チケット管理・FAQ 等）を継続。Sales Anchor とは独立。
- **Jarvis Bot（新規）**: 営業 DM の送受信・ステータス通知・bots テーブル経由の自動送信のみを担当。既製 Bot のコマンド名と衝突しない prefix を採用。

| 観点 | 評価 |
|------|------|
| 実装コスト | 中（Gateway 接続 + メッセージ授受のみ） |
| 既存運用への影響 | 最小（Tickets Bot 設定変更不要） |
| 双方向通信 | 可 |
| 既存 DB 設計との整合 | **完全整合**（`bots.discord_user_id` がそのまま使える） |
| 拡張性 | 高（Jarvis Bot に slash command や AI 機能を後から追加可能） |
| **採否** | **採用** |

---

## 4. 採用案と理由

**案 C（ハイブリッド：既製 Bot + Jarvis Bot 役割分担）** を採用する。

理由：

1. **設計原則「同じ情報を 2 箇所に書かない」を満たす**：Tickets Bot のデータは Jarvis に取り込まず、Jarvis は営業 DM のみを保持する。
2. **段階的着手が可能**：M2（接続のみ）から M6（監視）まで小刻みにマイルストーン化でき、内部テスト計画への影響が予測しやすい。
3. **既存 `bots.discord_user_id` / `v_senders` 設計が活きる**：Phase 1-B で実装済みの DB 設計（migration 020）を**そのまま**使える。
4. **VPS 2 GB メモリ制約と整合**：Gateway worker は単一の WebSocket + asyncio タスクで動作し、120-180 MB 程度に収まる想定（discord.py 公式ベンチマーク + 1 ギルド規模）。available 418 MB に対し十分な余裕。

---

## 5. アーキテクチャ詳細

### 5-1. プロセス構成

```
さくらVPS（2 GB）
├── myapp-nginx-1
├── myapp-frontend-1
├── myapp-backend-1     : FastAPI（HTTP API）
├── myapp-postgres-1
├── myapp-redis-1       : Celery / pub-sub 兼用
├── myapp-celery-worker-1
├── myapp-celery-beat-1
└── myapp-discord-gateway-1  ★ 新規（本 ADR の対象）
```

**配置方針**: backend コンテナ内で asyncio タスクとして同居させる**のではなく、独立コンテナ（`myapp-discord-gateway-1`）として分離する**。

理由：
- WebSocket 切断時の再接続が backend のリクエスト処理に影響を与えない
- Bot トークン環境変数を backend と分離（漏洩面の縮小）
- メモリ制約の見積もりが容易（gateway 単独で約 150-200 MB 上限を想定）
- backend デプロイ（10 秒以上の停止）時に Discord 接続が切れない

**コンテナ構成例（参考、HOW のメモ）**:
- `command: python -m app.discord_gateway.main`
- backend と同じ Python image をベースに、エントリーポイントだけ差し替え
- `depends_on: [postgres, redis]`、`backend` には依存しない

### 5-2. 接続管理（WebSocket Gateway）

| 項目 | 設計 |
|------|------|
| ライブラリ | discord.py（Python、公式ライブラリ準拠の最も成熟したクライアント。1 ADR で固定はせず、起草段階の推奨） |
| Heartbeat | Discord Gateway 仕様に準拠（41.25 秒）。ライブラリが自動 |
| 切断検出 | WebSocket close → 5 秒後に自動再接続。3 回連続失敗で `last_resume_failed_at` を bots テーブル拡張列に記録（M5 で検討） |
| Session resume | `RESUME` op を最優先で試行、`INVALID_SESSION` 時は `IDENTIFY` フォールバック |
| Intents | `MESSAGE_CONTENT`、`DIRECT_MESSAGES`、`GUILD_MESSAGES`、`GUILD_MEMBERS` のみ（最小権限原則） |
| Privileged Intents 申請 | `MESSAGE_CONTENT` は Bot 100 ギルド以下なら申請不要、超過時は Discord 開発者ポータルで申請必須 |

### 5-3. マルチテナントモデル

**採用方針: Per-Tenant Bot（テナントごとに別 Bot トークン）**

仕様書 8-2 では「マルチテナントでの 1 Bot 運用」と記載されているが、以下の理由で **per-tenant bot** を推奨する：

| 観点 | 1 Bot Multi-tenant | Per-Tenant Bot【採用】 |
|------|--------------------|------------------------|
| トークン漏洩時の被害範囲 | 全テナント | 単一テナントのみ |
| Discord ユーザーとしての見え方 | 全テナント共通の表示名 | テナントごとに独自の表示名・アイコン |
| `bots.discord_user_id` の値 | 全テナント同じ | テナントごとに異なる（理想的） |
| Discord 開発者アカウント分離 | 不可（1 アカウント1 Bot） | 可（テナント独自の開発者アカウント可能） |
| ギルド招待リンク管理 | 中央集権 | テナント自治 |
| 運用コスト | 低 | 中（テナント増加時にトークン管理が増える） |

**現状（テナント 1 件 = HIGH LIFE JPN）**: HIGH LIFE JPN 専用の Bot を 1 つ作成し、そのトークンを `bots.api_key_hash` ではなく**新規に Bitwarden / GCP Secret Manager** で管理する。テーブル `bots` の `api_key_hash` は**Sales Anchor 側 API への認証用**であり、**Discord Gateway トークンは別系統で保存**する（混同しない）。

- 仕様書原文「マルチテナントでの 1 Bot 運用」については、**しんごさんに案 C 推奨で再確認**したい（ADR レビュー時の確認事項）。

### 5-4. Sharding 発動条件

| 状態 | 設計 |
|------|------|
| 単 shard 運用（現状） | shard 数を明示的に指定せず、ライブラリのデフォルト（1）に任せる |
| 2,000 ギルド到達時 | アラート発火（`bots.guild_count`（拡張列）監視） |
| 2,500 ギルド到達時 | Discord が sharding を強制。再起動時に自動 shard 検出に切替 |
| 設計上の sharding 戦略 | テナント単位で shard を分けるのではなく、Discord 推奨の自動 shard 数（`gateway/bot` エンドポイント問い合わせ）に従う |

**実装は M5 以降。現時点では「sharding に対応可能なライブラリを選択」だけが要件**。

### 5-5. 認証とトークン管理

```
[Discord トークン: Gateway 接続用]
└── Bitwarden で保管 → 環境変数 DISCORD_BOT_TOKEN_<TENANT_ID> として注入
    （per-tenant bot のため、テナント数だけ環境変数が増える）

[bots.api_key_hash: Jarvis API 呼び出し用]
└── 既存設計のまま。bot から Jarvis backend を呼ぶ場合の認証
```

**重要**: `bots.api_key_hash` と Discord Bot Token は**用途が完全に別**。混同すると設計が崩れる。

---

## 6. セキュリティ考慮

| 項目 | 対策 |
|------|------|
| Bot トークン漏洩 | コンテナ環境変数経由で注入。コードリポジトリ・ログ・監査ログにトークンを出さない（既存 `record_audit_log` に redaction 拡張） |
| トークンローテーション | Discord 側で Reset Token → Bitwarden 更新 → コンテナ再起動の手順をrunbook化（B-11 credential management policy 参照） |
| テナント越境 | 受信メッセージは `discord_user_id` から `bots.tenant_id` を逆引きし、書き込み先 `tenant_id` を厳格に決定。**自テナント以外のチャネルから受信したメッセージは破棄してログ記録** |
| Rate Limit | Discord Gateway の Rate Limit（`5 requests / 5 seconds` per identify、メッセージ送信 `5 / 5s` per channel）に準拠。送信は Redis 経由のキュー直列化 |
| Abuse 対策 | bot 自身が DDoS 対象になる可能性は低い（Discord Gateway 経由のため）。ただし spam DM 対策として「同一 author から 10 sec 内 5 メッセージ超」をログ記録 |
| Privileged Intents | `MESSAGE_CONTENT` のみ申請。`PRESENCE` `GUILD_MEMBERS`(全件取得) は不要であれば取らない |
| ID 重複検出 | Discord メッセージ ID（`event_id` 列）に UNIQUE 制約。再起動時のリプレイ防止 |
| 監査ログ | `bots` 経由の操作はすべて `audit_logs` に actor_type=bot で記録（既存 `record_audit_log` 互換） |

---

## 7. データフロー

### 7-1. 受信（Inbound）

```
Discord ユーザー
   │ DM / ギルドメッセージ
   ▼
Discord Gateway（WebSocket）
   │ MESSAGE_CREATE event
   ▼
myapp-discord-gateway-1（常駐コンテナ）
   │ event 受信 → JSON シリアライズ
   ▼
PostgreSQL: raw_webhook_events
   │ source='discord', event_id=<message.id>, payload=<json>
   ▼
Celery タスク: ingest_discord_event（既存 messenger と同じパターン）
   │
   ├─ 送信者 lookup: leads (source='discord', external_id=<author.id>)
   ├─ 新規なら lead 作成
   └─ conversations に書き込み（sender_type='external', sender_id=lead.id）
   ▼
フロントエンド（リードチャット画面）
```

**設計判断**: Gateway worker は `raw_webhook_events` への INSERT までを担当し、その後の処理は Celery タスクに移譲する。これにより：
- WebSocket セッションを長く待たせない
- 既存 Messenger の ingestion path（`backend/app/routers/webhook.py`）と同じパターンになる
- メッセージ ID（`event_id`）に UNIQUE 制約 → 再起動時のリプレイ吸収

### 7-2. 送信（Outbound）

```
Sales Anchor フロントエンド
   │ 「Discord で送信」ボタン押下
   ▼
backend API: POST /api/v1/conversations/{id}/send-discord
   │ permission='discord.send' チェック
   │ sender = staff or bot から選択
   ▼
PostgreSQL: outbox_discord_messages（新規テーブル、M4 で追加）
   │ status='pending', sender_type, sender_id, recipient_discord_id, body
   ▼
Redis Pub/Sub: channel='discord:outbox'
   │
   ▼
myapp-discord-gateway-1: subscribe
   │ Discord Gateway 経由で送信
   │ 成功時 status='sent' / message_id 記録
   │ 失敗時 status='failed' + retry_count++（最大 3 回）
   ▼
PostgreSQL: conversations 更新
```

**設計判断**: backend → gateway worker は **Redis Pub/Sub（既存 Redis を流用）** で疎結合化。Bot 宛の send 命令は backend から直接 Gateway に書き込まないことで、backend と Gateway の起動順序依存を排除する。

### 7-3. v_senders ビューとの整合

既存の `v_senders` ビュー（migration 020）は staff と bots を UNION して送信元を統一している。Discord メッセージ送信時、`conversations.sender_type` と `sender_id` は以下のように設定される：

| シーン | sender_type | sender_id |
|--------|-------------|-----------|
| 営業担当が Discord で手動返信 | `staff` | `staff.id` |
| 請求書送付 bot が Discord 通知 | `bot` | `bots.id` |
| Discord 側ユーザーから受信 | `external`（新規追加。lead/customer の出自を示す） | `leads.id` または `customers.id` |

→ `external` 区分の追加が必要なら migration を追記（M3 で対応）。

---

## 8. 実装計画 / マイルストーン

| ID | マイルストーン | 含む範囲 | 工数目安 | 完了条件 |
|----|---------------|---------|---------|---------|
| **M1** | ADR レビュー + 設計確定 | 本 ADR のレビュー、しんごさん確認事項クリア、Discord 開発者アカウント・Bot Token 取得 | **0.5 日**（設計議論）+ 別途インフラ準備（しんごさん側 1〜2 日） | ADR ステータス Accepted、Bot Token が Bitwarden に格納 |
| **M2** | Skeleton Worker | `myapp-discord-gateway-1` コンテナ追加（docker-compose 編集）、Gateway 接続のみ、heartbeat ログ吐き、READY イベント受信ログ、コンテナ再起動で session resume 確認 | **1 日** | VPS で docker compose up → 5 分以上接続維持、ログに heartbeat 出力 |
| **M3** | Inbound Ingestion | MESSAGE_CREATE event → `raw_webhook_events` 投入、Celery `ingest_discord_event` タスク追加、conversations への書き込み、event_id UNIQUE 制約、`v_senders` の `external` 区分対応 | **2 日** | テスト Discord ギルドから DM → Jarvis のリードチャット画面に表示される |
| **M4** | Outbound Dispatch | `outbox_discord_messages` テーブル追加（migration 038 想定）、Redis Pub/Sub 購読、staff / bot 単位の送信元切替、送信失敗時のリトライ（最大 3 回・指数バックオフ）、`bots.execution_count` インクリメント | **2 日** | Jarvis から Discord ユーザーへ DM 送信が成功し、conversations に sender_type='bot' で記録される |
| **M5** | Multi-tenant 拡張 | per-tenant bot のトークン管理仕組み、テナント追加時の Bot 招待フロー文書化、`bots.guild_count`（拡張列）追加、テナント越境拒否ロジック実装、テスト | **1.5 日** | 2 テナント分の Bot を別ギルドに招待し、相互不可視を確認 |
| **M6** | 運用監視 | Prometheus metrics（接続状態 gauge、heartbeat latency histogram、reconnect カウンタ）、Grafana ダッシュボード、Discord Gateway 切断時の Discord webhook 通知（既存 `send_discord_notification` 流用）、runbook（再起動・トークン rotate 手順） | **1 日** | 切断 5 分継続で Slack/Discord に alert 通知 |
| **合計** | | | **8 日**（しんごさん側のインフラ作業除く） | |

### マイルストーン依存関係

```
M1 ─→ M2 ─→ M3 ─→ M4 ─→ M5 ─→ M6
                    │              │
                    └──────────────┘
              （M4 と M5 は M3 完了後に並行可能）
```

### 着手前提

- **しんごさん側で M1 完了**（Bot Token 取得、Bitwarden 格納、開発者アカウント整備）が他マイルストーンの前提。
- Phase 1-B-2 の VPS 適用が完了済みであること（既に 2026-04-23 で完了）。
- VPS のメモリ余剰確認（**2026-04-28 計測完了：2 GB プラン、available 418 MB**。Gateway worker 200 MB 確保可能）。

---

## 9. リスクと未確定事項

| ID | リスク / 未確定事項 | 影響度 | 発生確率 | 対策 |
|----|---------------------|--------|---------|------|
| R1 | Discord API rate limit 超過 | 中 | 低 | Redis 直列化キューで送信制御。受信は Gateway 側 buffer に依存 |
| R2 | 接続切断時のメッセージロスト | 高 | 中 | Discord Gateway は session resume で 24 時間以内のメッセージを再送する。それ以上の長期切断時は Discord 側で履歴喪失。M6 で alert 必須 |
| R3 | Bot トークン漏洩 | 致命 | 低 | 環境変数管理 + Bitwarden + コンテナ分離 + 監査ログ redaction。Reset Token 手順を runbook 化 |
| R4 | 既製 Bot とのコマンド名衝突 | 低 | 低 | Jarvis Bot は slash command を当面提供しない（DM/メッセージ受発信のみ）。将来追加時は `/jarvis-` prefix 強制 |
| R5 | VPS メモリ不足（2 GB プラン、swap 無効） | 中 | 中 | 2026-04-28 計測で available 418 MB 確認済（Gateway 200 MB 確保可）。burst 時の OOM 対策で M2 着手前に 2 GB swap ファイル追加を実施 |
| R6 | Privileged Intents 申請拒否 | 中 | 低 | 100 ギルド以下なら申請不要。HIGH LIFE JPN は 1 ギルドのため当面問題なし |
| R7 | discord.py / nextcord / py-cord ライブラリ選定 | 低 | 低 | M2 着手時に最終決定。ADR は固定しない（HOW を leak しない方針） |
| R8 | 「マルチテナントでの 1 Bot 運用」仕様書記述との乖離 | 中 | - | **しんごさんに per-tenant bot 案で再確認必須**（本 ADR レビュー時） |
| R9 | Tickets Bot との同時運用時の DM 重複応答 | 中 | 低 | Tickets Bot は DM ではなくチャネル動作。Jarvis Bot は DM 中心で住み分け可能。M3 で実機確認 |
| R10 | Discord メッセージ ID の重複検出（再起動時のリプレイ） | 中 | 中 | `raw_webhook_events.event_id` に UNIQUE 制約 + INSERT ON CONFLICT DO NOTHING |
| R11 | 開発環境での local Bot 起動方法 | 低 | - | M2 で開発用 Bot Token を別途用意し、`docker-compose.dev.yml` で `myapp-discord-gateway-1` のみ起動可能にする |

---

## 10. 次のアクション

### 10-1. しんごさんに確認すべき質問

| Q | 内容 | 回答 / ステータス |
|---|------|-----------------|
| **Q1** | per-tenant Bot 案（5-3）を採用してよいか？仕様書原文「マルチテナントでの1 Bot運用」との整合は？ | **✅ 採用確定（2026-04-28）**。仕様書原文は per-tenant Bot に上書き。理由: トークン漏洩時のテナント越境防止、開発者アカウント分離、`bots.discord_user_id` がテナントごとに独自値となり整合性◎ |
| **Q2** | Discord 開発者アカウントは誰が管理するか？（しんごさん個人 / HIGH LIFE JPN 法人 / 開発パートナー） | **✅ しんごさん個人（Treasure Island JP メールアドレス）で確定（2026-04-28）**。将来 HIGH LIFE JPN 法人化が望ましいが当面は個人運用で M1 着手 |
| **Q3** | Tickets Bot / John-Bot の運用責任者と機能範囲を再確認したい | 未確認（M3 実機確認時に確定）。R4 / R9 関連 |
| **Q4** | VPS のメモリ余剰量（200 MB 確保可能か） | **✅ 確保可能（2026-04-28 計測）**。VPS は実際 2 GB プラン（**1 GB 記載は誤認、本 ADR・関連ドキュメント要修正**）。available 418 MB / Gateway 想定 200 MB → 余剰 218 MB。swap 0 のため burst 対策で 2 GB swap ファイル追加を M2 着手前に実施推奨 |
| **Q5** | Discord 連携の優先度（Phase 3 前半 / 後半 / Phase 4 以降） | **✅ Phase 3 前半で確定（2026-04-28）**。リード・会話機能と並行着手 |
| **Q6** | Bot Token のローテーション頻度ポリシー（B-11 既存ポリシーに準拠でよいか） | M1 で確認継続（B-11 準拠を default 想定） |
| **Q7** | 営業 Bot が DM で実行できるアクションの範囲（送信のみか、ステータス更新も含めるか） | M4 のスコープ確定時に再確認 |

### 10-1-A. 確定事項に基づく更新メモ（2026-04-28）

- **G4 修正**: 「1 GB メモリ VPS の制約下で」→「**2 GB メモリ VPS（available ~418 MB）の制約下で**」に修正対象。本 ADR 内の 1 GB 記載は将来一括置換が必要。
- **5-1 補足**: VPS が実 2 GB のため、Gateway worker メモリ上限を 200 MB → 220-256 MB に余裕を持って設定可能。
- **R5 緩和**: 「VPS メモリ不足（1 GB 制約）」→ 緩和されたが、swap 無効のため burst 時の OOM リスクは残存。M2 着手前に swap 2 GB 追加を実施。

### 10-2. 仕様書の追加更新提案

- `salesanchor_system_overview.docx` 第8章 8-2 の ADR-009 段落を、本 ADR の Accept 後に「ADR-009 採用済み（案 C ハイブリッド）」と1行更新すること。
- `salesanchor_staff_roles_bots_design.docx` 第4章末尾に「Discord トークンは `bots.api_key_hash` とは別系統で管理（ADR-009 5-5 参照）」を追記すること（現状記述が紛らわしい）。

### 10-3. 実装着手前の前提条件（チェックリスト）

- [x] 本 ADR のステータスが Accepted に遷移（2026-04-28）
- [x] Q1, Q2, Q4, Q5 に回答（2026-04-28）
- [ ] Q3, Q6, Q7（着手後の各マイルストーン時に確認継続）
- [ ] Discord Bot Token が取得され Bitwarden に格納（**しんごさん側 M1 タスク**）
- [ ] **Discord Developer Portal で Privileged Intents を ON**（Bot 設定画面の `MESSAGE CONTENT INTENT` と `SERVER MEMBERS INTENT`）。100 ギルド以下なら申請不要だが、Portal トグル自体は guild 数無関係に必須。OFF のまま接続すると `PrivilegedIntentsRequired` で READY が出ない
- [x] VPS メモリ余剰 200 MB 確保確認（available 418 MB、2026-04-28 計測）
- [ ] swap 2 GB ファイル追加（M2 着手前、burst 時 OOM 対策）
- [ ] テスト Discord ギルド（HIGH LIFE JPN とは別）の準備（**しんごさん側 M1 タスク**）
- [ ] Phase 3 conversations / raw_webhook_events のテーブル設計が確定（現状 Phase 2 に meta_messages のみで、Discord 用カラムがない可能性あり → M3 着手前に確認）

---

## 11. 監査ノート（spec audit による補強点）

仕様書 8-2 の ADR-009 段落（1 段落）から本 ADR を起草する過程で、以下の観点が**仕様書では明示されていない**ため本 ADR で初出となった。しんごさん追認が必要。

| 補強点 | 仕様書での扱い | 本 ADR での扱い |
|--------|---------------|-----------------|
| プロセス分離（独立コンテナ vs backend 内 asyncio） | 言及なし | 独立コンテナ採用（5-1） |
| マルチテナント形態（per-tenant vs 1 bot） | 「1 Bot 運用」と1行のみ | per-tenant 推奨（5-3）→ Q1 で要確認 |
| Bot Token と `api_key_hash` の混同回避 | 言及なし | 別系統管理を明示（5-5） |
| 既製 Bot との具体的な役割分担 | 言及あり（抽象的） | 案 C で具体化（4 章） |
| 受信時の重複検出 | 言及なし | event_id UNIQUE で吸収（7-1） |
| 開発環境での Bot 起動方法 | 言及なし | docker-compose.dev.yml 案（R11） |
| Sharding の自動／手動切替 | 「2500ギルド到達時」のみ | 自動 shard 検出採用（5-4） |
| メッセージ送信のキュー設計 | 言及なし | Redis Pub/Sub で疎結合（7-2） |
| 監視メトリクス | 言及なし | Prometheus + Grafana（M6） |

---

## 12. 関連ドキュメント

- `salesanchor_system_overview.docx` 第4-4「外部連携サービスの全体マップ」、第8-2「緊急で起草すべき ADR」
- `salesanchor_staff_roles_bots_design.docx` 第4章「bot 管理（bots）」
- `migrate_staff_roles_bots.md` 第3-5節「bots テーブル定義」
- `salesanchor/migrations/020_create_bots_and_senders_view.sql`
- `salesanchor/migrations/022_staff_bots_rls_policies.sql`
- `salesanchor/migrations/024_add_staff_bots_permissions.sql`
- `salesanchor/backend/app/routers/bots.py`
- `salesanchor/backend/app/routers/webhook.py`（Meta Messenger ingestion の参考実装）
- `salesanchor/docs/B-11_credential_management_policy.md`（トークンローテーション）

---

**本 ADR は設計のみ。実コード変更は M2 以降の別セッションで着手する。**

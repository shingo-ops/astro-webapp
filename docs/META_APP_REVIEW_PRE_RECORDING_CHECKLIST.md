# Meta App Review — Pre-Recording Checklist

| 項目 | 内容 |
|---|---|
| ステータス | v1.1（ADR-041 で 6→7 permission に拡張、tenant_006 撮影テナント運用反映） |
| 作成日 | 2026-04-30 |
| 最終更新 | 2026-05-21 |
| 対象 | スクリーンキャスト撮影者（しんごさん想定） |
| 関連 | `meta-app-review/META_APP_REVIEW_SCREENCAST_SCRIPT.md` (v3.1), `PHASE_1D_META_INBOX_OVERVIEW.md`, ADR-041 / ADR-045 |

> このチェックリストは撮影開始前に **すべて ✅** にしないと撮影本番に入らないこと。1 つでも未対応だと撮影やり直しになる可能性大。

---

## 0. 概要

撮影の流れ：

```
[A] Meta Developer Portal 設定
       ↓
[B] VPS 環境変数 / コンテナ稼働確認
       ↓
[C] テストアカウント / テストデータ準備
       ↓
[D] 撮影機材セットアップ (OBS, ブラウザ, マイク)
       ↓
[E] リハーサル 1 回
       ↓
[F] 撮影本番
       ↓
[G] 編集 + アップロード
       ↓
[H] Master Checklist v1.1 更新 + Meta App Review 提出
```

このドキュメントは **[A]〜[E]** までのチェック項目を扱う。撮影台本本体は `META_APP_REVIEW_SCREENCAST_SCRIPT.md` を参照。

---

## A. Meta Developer Portal 設定

### A-1. App 基本設定

- [ ] App ID: `META_APP_ID` を VPS 設定値と一致させて控える
- [ ] App Secret: `META_APP_SECRET` を GitHub Secrets に保管（撮影中に絶対画面に映さない）
- [ ] App Mode: **Test Mode** で進める（撮影は Test Mode で OK、本番モードは審査通過後）
- [ ] App Domain: `salesanchor.jp`, `app.salesanchor.jp`
- [ ] Privacy Policy URL: `https://salesanchor.jp/privacy`（Phase 5 で稼働中）
- [ ] Terms of Service URL: `https://salesanchor.jp/terms`
- [ ] Data Deletion Request URL: `https://api.salesanchor.jp/api/v1/meta/data-deletion`（B1-B7 で本番稼働中、`api.salesanchor.jp` サブドメインに注意）
- [ ] User Data Deletion Status URL Pattern: `https://salesanchor.jp/deletion-status?code={confirmation_code}`（confirmation code 形式: `DEL-YYYYMMDD-xxxx`）

### A-2. Facebook Login 設定

- [ ] **Valid OAuth Redirect URIs** に以下が登録済:
  - `https://app.salesanchor.jp/channels/oauth/callback`（本番）
  - `http://localhost:5173/channels/oauth/callback`（開発、必要なら）
- [ ] Client OAuth Login: **Yes**
- [ ] Web OAuth Login: **Yes**
- [ ] Force Web OAuth Reauthentication: No (デフォルト)
- [ ] Use Strict Mode for Redirect URIs: **Yes**（推奨）
- [ ] Allow logging in with Instagram Business: **Yes**

### A-3. Webhook 設定

- [ ] Object: `page` で subscribe 済（既存）
- [ ] Object: `instagram` で subscribe 済（Sprint 6 で対応）
- [ ] Subscription Fields (page): `messages`, `messaging_postbacks`, `messaging_optins`, `message_deliveries`, `message_reads`
- [ ] Subscription Fields (instagram): `messages`, `messaging_postbacks`
- [ ] Callback URL: `https://api.salesanchor.jp/api/v1/webhook/messenger`（Phase 5 で `api.salesanchor.jp` サブドメインに切替済）
- [ ] Verify Token: `META_VERIFY_TOKEN` と VPS 設定値が一致

### A-4. Permission 申請対象（7 permission — ADR-041 で `business_management` 追加）

- [ ] `pages_show_list`（Standard、即承認）
- [ ] `pages_manage_metadata`（Standard）
- [ ] `pages_messaging`（Advanced、要審査）
- [ ] `pages_read_engagement`（Advanced、要審査）
- [ ] `instagram_basic`（Advanced、要審査）
- [ ] `instagram_manage_messages`（Advanced、要審査）
- [ ] `business_management`（Advanced、要審査）— **Business Manager 経由で管理する Page を `/me/businesses` から取得するために必須**

各 Permission について、Use Case Description が記載済（Master Checklist v1.1 §A）。

**実装上の正準リスト**: `backend/app/routers/meta_inbox.py` の `_OAUTH_SCOPE`（変更時は本リストと同期）。

> ⚠️ **既存接続テナント**（ADR-041 以前に 6 permission で接続済）には UI に「再認証してください」バナーが出る（`granted_scopes` に `business_management` を含まない接続が判定対象）。撮影テナントは A-5 の新規接続で 7 permission をすべて取得すること。

### A-5. 撮影用 Facebook / Instagram アカウント

> ADR-028 以降、撮影は **専用テナント `tenant_006` (tenant-review)** で実施する。本番テナント（`tenant_004` highlife-jpn）には触らない。

- [ ] **Facebook Page**: `Shingo Tanizawa` Page（しんごさん個人運用、Business Manager 配下）
  - Page ID: `664490526747447`
  - Admin: しんごさん（Business Manager Admin 必須 — `business_management` scope で取得するため）
- [ ] **Instagram Business Account**: `@treasureislandjapan`
  - IG ID: `17841466869358023`
  - 上記 Page にリンク済（Meta Business Suite → Instagram → アカウントの連携）
- [ ] **Sender 用アカウント**（撮影で DM を送る側）: しんごさんの私用 FB/IG アカウント or テスト用アカウント。撮影テナントの Page と過去履歴がないアカウント推奨
- [ ] **Business Manager Admin 権限**: OAuth 同意画面で `business_management` を許可するには接続者が Business Manager の Admin である必要あり。`review@salesanchor.jp` でログイン後の OAuth ボタン押下時は **しんごさん自身の Facebook セッション** で同意する流れ（forced_account_switch 注意 → D-2 参照）

---

## B. VPS 環境変数 / コンテナ稼働確認

### B-1. .env 設定値（VPS `/home/ubuntu/salesanchor/.env`）

- [ ] `METADATA_FERNET_KEY=<32 bytes urlsafe base64>` 注入済（GitHub Secrets に同値あり）
- [ ] `META_APP_ID=<App ID>` 注入済
- [ ] `META_APP_SECRET=<App Secret>` 注入済
- [ ] `META_OAUTH_REDIRECT_URI=https://app.salesanchor.jp/channels/oauth/callback` 注入済
- [ ] `META_GRAPH_API_VERSION=v19.0` 注入済
- [ ] `META_VERIFY_TOKEN=<token>` 注入済（Webhook と一致）
- [ ] `PUBLIC_BASE_URL=https://salesanchor.jp` 注入済（B1-B7 Status URL 用）
- [ ] `FRONTEND_BASE_URL=https://app.salesanchor.jp` 注入済
- [ ] `ENFORCE_METADATA_FERNET_KEY=1`（推奨、本番では fail-fast）

### B-2. コンテナ稼働確認

```bash
# VPS 側
ssh ubuntu@49.212.137.46
cd /home/ubuntu/salesanchor

# 全コンテナ Healthy 確認
docker compose ps

# backend が起動時 Fernet 鍵を読めているか
docker compose logs backend | grep -i "fernet\|encryption" | tail -10

# meta_inbox router が登録されているか
docker compose exec backend curl -s http://localhost:8000/openapi.json | jq '.paths | keys[] | select(test("meta|conversations|messages"))'
```

期待出力（抜粋）:
```
/api/v1/conversations
/api/v1/leads/{lead_id}/messages
/api/v1/leads/{lead_id}/messages/mark-read
/api/v1/meta/channels
/api/v1/meta/connect/callback
/api/v1/meta/connect/start
/api/v1/meta/connect/{page_id}
```

### B-3. Migration 適用確認

```bash
# VPS 側（撮影テナント tenant_006 を確認）
docker compose exec postgres psql -U jarvis -d jarvis_db \
  -c "SELECT schemaname, tablename FROM pg_tables WHERE tablename IN ('tenant_meta_config', 'meta_messages') AND schemaname IN ('tenant_006','tenant_004') ORDER BY schemaname;"

# tenant_006 / tenant_004 両方で tenant_meta_config と meta_messages が並ぶことを確認

# tenant_006 の tenant_meta_config に granted_scopes 列があるか（ADR-041 / migration 055）
docker compose exec postgres psql -U jarvis -d jarvis_db \
  -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='tenant_006' AND table_name='tenant_meta_config' AND column_name IN ('granted_scopes','scope_count') ORDER BY column_name;"
```

期待:
- `tenant_006.tenant_meta_config` / `tenant_006.meta_messages` あり（migration 040〜041、ADR-045 で新規テナント自動適用）
- `tenant_006.tenant_meta_config` に `granted_scopes` (jsonb) と `scope_count` (int) 列あり（migration 055）
- `tenant_004.meta_messages` の `recipient_id`, `messaging_type`, `message_tag`, `sent_by_staff_id`, `error_code`, `error_message`, `message_id`, `seen_at`, `seen_by_staff_id` 列あり（migration 041）
- `tenant_004.meta_messages.message_id` が `text` 型（ADR-026 / migration 052 で IG 157 文字対応）
- `public.permissions` に `channels.view`, `channels.manage`, `messaging.view`, `messaging.send` の 4 件 + Owner/Admin role に付与あり（migration 042）

### B-4. Webhook 受信疎通

```bash
# VPS 側
# Meta Developer Portal の "Test" ボタンで page object に POST テスト送信
# その直後ログを確認
docker compose logs backend | grep -i "webhook" | tail -20
```

期待: `200 OK` + meta_messages に行が INSERT される（テストデータが入って構わない、後で消す）

---

## C. テストアカウント / テストデータ準備

### C-1. Sales Anchor アカウント（撮影テナント tenant_006）

- [ ] `review@salesanchor.jp` (Owner ロール) を `tenant_006.staff` に作成済（ADR-028 `setup_review_tenant.py` で投入）
  ```sql
  -- VPS 上の psql で
  -- 既存 staff の場合は確認のみ
  SELECT id, email, role_id FROM tenant_006.staff WHERE email = 'review@salesanchor.jp';
  ```
- [ ] パスワードを VPS ホスト側の永続ファイルに保管（コンテナ `/tmp` は再起動で消えるため必須）:
  ```bash
  # スクリプト実行直後に以下を実行してホスト側に保存する
  docker compose exec -T backend cat /tmp/review_tenant_setup_*.txt \
    > /home/ubuntu/salesanchor/review-tenant-password.txt
  chmod 600 /home/ubuntu/salesanchor/review-tenant-password.txt
  # 確認
  cat /home/ubuntu/salesanchor/review-tenant-password.txt
  ```
  **注意**: デプロイ（`docker compose up --build`）でコンテナが再起動するたびに `/tmp` は消える。保存前に再起動した場合はスクリプトを再実行すること（Firebase・DB 両方が更新される）。
- [ ] Firebase Auth で同 Email を 1 アカウント作成 + 当該 `tenant_006.staff.id` と紐付け済
- [ ] tenant_006 ログイン後の URL 末尾が `?tenant_code=tenant-review` 等で識別できることを確認

### C-2. Facebook Page / IG 接続

- [ ] A-5 完了済
- [ ] `review@salesanchor.jp` ログイン後、`https://app.salesanchor.jp/channels` で 7 permission OAuth 通しが成功する（リハ済）
  - **失敗ケース**: redirect_uri 不一致 / scope 不一致 / state 期限切れ / `forced_account_switch`（既存 FB セッションが別アカウント → D-2 別プロファイル分離で回避）/ Business Manager Admin 未付与
  - 接続成功時、`/channels` に Page カードが Active 表示され `IG linked='@treasureislandjapan'` / `scope_count=7` / `has_business_management=True` を満たす
- [ ] Page の `subscribed_apps` に App が登録済（OAuth 成功時に自動）
- [ ] tenant_006 に既存の inactive レコード（過去 6 permission 接続分など）がある場合、撮影で映る場合は事前に整理判断（Channels ページに残る場合あり）

### C-3. 24h 経過済会話の準備（シーン 7 用）

撮影前日に以下を実施：

```
[D-1 = 撮影前日]
1. Test User 2 (Sender) → Test Page Messenger で DM 送信: "Test message for human agent tag scene"
2. Sales Anchor Inbox に着信確認
3. 何もしないで放置

[D = 撮影当日 / 25h 経過後]
4. Inbox を開き、当該会話の 24h バナーが切替済（"Standard window expired. Replying with Human Agent Tag"）であることを確認
5. これでシーン 7 の素材完成
```

または DB 直接いじる手段（やむを得ない場合）：

```sql
-- 撮影直前に当該 lead の最新 inbound created_at を 25h 前に書き換え
UPDATE tenant_006.meta_messages  -- 撮影テナント
SET created_at = NOW() - INTERVAL '25 hours'
WHERE lead_id = <target_lead_id> AND direction = 'inbound'
ORDER BY id DESC LIMIT 1;
```

ただし審査担当に「実機シナリオでない」と取られるリスクがあるため、**撮影前日からの実時間経過** を推奨。

### C-4. Data Deletion テストペイロード（シーン 8 用）

- [ ] Meta Developer Portal の `Data Deletion Callback` 設定が正しい
- [ ] curl テスト用の signed_request サンプルを安全な場所に保管
- [ ] テスト送信 → Status Page が `https://salesanchor.jp/deletion-status?code=<confirmation_code>` で開けるか事前確認（confirmation_code は `DEL-YYYYMMDD-xxxx` 形式、レスポンスの `confirmation_code` フィールドをそのまま利用）
- [ ] SMTP 設定済（任意）。設定済なら完了メールも撮影に含められる

---

## D. 撮影機材セットアップ

### D-1. PC / OS

- [ ] PC スペック: 録画 + ブラウザ複数同時動作に耐えるメモリ 16GB 以上
- [ ] OS の自動アップデート無効（撮影中の再起動を防ぐ）
- [ ] 通知センター OFF（macOS: 集中モード ON / Windows: フォーカスアシスト ON）
- [ ] 不要アプリ全終了（Slack, Discord, メール, etc.）

### D-2. ブラウザ（Chrome 推奨）

- [ ] 別プロファイル「`MetaReview`」を作成し、撮影専用に
- [ ] ブックマークバー非表示（Cmd+Shift+B / Ctrl+Shift+B）
- [ ] 拡張機能すべて無効（特に翻訳系・パスワード系）
- [ ] ズーム 100%（Cmd+0）
- [ ] DevTools 閉じる
- [ ] 履歴・自動入力候補をクリア（撮影中に Email 候補ポップアップを防ぐ）
- [ ] **既存 Facebook セッションは事前ログアウト** — OAuth で `forced_account_switch` 画面を回避するため、撮影プロファイルにはしんごさんの FB アカウント（Business Manager Admin 持ち）でログイン状態を作っておく
- [ ] 開く必要のあるタブ:
  - Sales Anchor (`https://app.salesanchor.jp/login`)
  - Messenger Web (`https://www.messenger.com`)
  - Instagram Web (`https://www.instagram.com`)
  - Meta Developer Portal (撮影中に開く前提)

### D-3. OBS Studio 設定

- [ ] バージョン 30.x 以上（古いと NVENC 安定しない）
- [ ] 解像度: ベース 1920×1080 / 出力 1920×1080
- [ ] FPS: 60
- [ ] エンコーダ: x264 (CRF 20, preset medium) または NVENC (CQ 20)
- [ ] 音声: 48kHz / ステレオ / AAC 128kbps
- [ ] 音声ソース:
  - マイク: USB コンデンサマイク or AirPods Pro マイク（最低限）
  - デスクトップ音声: **OFF**（通知音漏洩防止。Messenger/Instagram の通知音だけ別途欲しい場合は事前検討）
- [ ] シーン: 「画面全体」1 つで OK（複雑な編集不要）
- [ ] 録画フォーマット: mp4 (推奨) または mkv → ffmpeg で mp4 変換

### D-4. マウス強調ツール

- [ ] macOS: `MousePosé` または `Highlight` アプリ
- [ ] Windows: `Mouseposé` または `KeyCastr` 同梱
- [ ] 設定: クリック時に黄色いリング、ポインタの周囲に半透明ハイライト

### D-5. キー入力強調ツール

- [ ] macOS: `KeyCastr`（無料）
- [ ] Windows: `Keyviz` または `Carnac`
- [ ] 設定: テキスト入力時のみ表示、修飾キー単独は非表示（Cmd, Ctrl 単独は雑音になる）

### D-6. マイク・音声リハ

- [ ] テスト録音 30 秒
- [ ] 再生して音割れなし、聞き取れる音量
- [ ] 環境音（ファン、エアコン、街路ノイズ）が小さい
- [ ] Krisp などの AI ノイズリダクションを ON にする（推奨）

---

## E. リハーサル

### E-1. 通しリハーサル（撮影日当日）

- [ ] 全 8 シーンを台本通りに **2 回** 通しで実演（録画なしでも OK）
- [ ] 各シーンで時間が短すぎ / 長すぎないか確認
- [ ] OAuth ダイアログが想定通りに開くか
- [ ] Webhook 着信が 10 秒以内か
- [ ] 24h 経過済会話の状態確認（シーン 7）
- [ ] Data Deletion Callback の動作確認（シーン 8）
- [ ] ナレーションが間に合うペースか

### E-2. リハ後トラブル対応

| 問題 | 対処 |
|---|---|
| Webhook 着信が遅い | docker compose logs backend で 502 / 429 がないか確認、polling 周期を一時的に 5s に短縮（撮影後戻す） |
| OAuth で `URL_NOT_REGISTERED` | A-2 redirect_uri を再確認 |
| OAuth で `Permissions Error` | A-4 Permission 申請 status 確認、特に `business_management` が承認/取得済か |
| OAuth で `Security token mismatch` | フロー途中離脱の signal、再試行で解消することが多い |
| OAuth で `forced_account_switch` 画面 | 既存 FB セッションと別アカウントで OAuth 必要 → D-2 別 Chrome プロファイル分離で回避 |
| Page カードに「再認証してください」バナー | `granted_scopes` に `business_management` を含まない（ADR-041 以前の接続）→ 新規 OAuth でやり直し |
| Page 一覧に対象 Page が出ない | BM Admin でないか、`business_management` 拒否、または FB 側 Page Role 未付与 |
| Page Access Token 復号失敗 | METADATA_FERNET_KEY が VPS と DB で一致しているか確認 |
| Inbox 描画崩れ | ブラウザのズームを 100% に戻す、ハードリロード (Cmd+Shift+R) |
| 24h 経過会話がない | C-3 の手順で前日に DM 送信、または DB 操作（推奨しない） |
| Meta UI の Webhooks「テスト」ボタンが効かない | Meta UI 側の CSP バグ。Graph API Explorer か Live フローで疎通確認（撮影には影響しない） |

### E-3. リハ完了基準

- [ ] 全 8 シーン、ノーミスで通しできた
- [ ] 録画ファイル容量の見積もり: 60fps 1080p で約 15 MB/分 → 7 分で 105 MB 程度（圧縮で半減）
- [ ] ナレーション原稿を印刷 or タブレットに表示しておく（撮影中の参照用）

---

## F. 撮影本番

- [ ] OBS 録画開始
- [ ] 5 秒の沈黙を入れてからシーン 1 開始（編集の取り回し用）
- [ ] 各シーン間で 1.5 秒の沈黙（編集でカット可能に）
- [ ] 撮影後 OBS 録画停止
- [ ] ファイル保存 → `recording_<timestamp>.mp4`
- [ ] 直後に再生して全シーン確認

---

## G. 編集 + アップロード

詳細は `META_APP_REVIEW_SCREENCAST_SCRIPT.md` §10 を参照。

- [ ] 不要部分カット
- [ ] 字幕焼き込み（英語ハードサブ）
- [ ] BGM は **入れない**（Meta は不要、ナレーション優先）
- [ ] 最終ファイル名: `salesanchor_meta_app_review_v1.mp4`
- [ ] Google Drive アップロード
- [ ] 共有リンク生成（Meta 審査担当が再生できるよう、リンクを知っている全員に閲覧権限）

---

## H. Meta App Review 提出

- [ ] Master Checklist v1.1 §A の動画 URL 欄に共有リンク貼付
- [ ] Use Case Descriptions §2 の各 Permission の動画タイムスタンプを更新（例: `pages_show_list: 0:36-0:50`）
- [ ] Privacy Policy URL / Terms URL / Data Deletion URL の最終確認
- [ ] App Review → Submit ボタンを押す前に Master Checklist v1.1 の全項目 ✅ を確認

---

## I. 撮影後フォロー

- [ ] 撮影で投入した `subscribed_apps` を切断（`/channels` で「切断」ボタン）— **撮影テナント tenant_006 限定**、本番 tenant_004 は無関係
- [ ] 撮影で送受信したテスト DM を DB から削除（任意）
  ```sql
  -- 撮影日に作った meta_messages を削除（tenant_006）
  DELETE FROM tenant_006.meta_messages WHERE created_at >= 'YYYY-MM-DD' AND lead_id IN (<test_lead_ids>);
  ```
- [ ] 24h 経過用に作った lead の archive
- [ ] 撮影記録を `docs/INTERNAL_TEST_RECORD.md` の形式で残す（任意）
- [ ] **本番 tenant_004 (highlife-jpn) の再認証バナーテスト**は別途実施（granted_scopes 6 permission の既存接続が判定通り再認証要求されるか）

# Meta App Review — Screencast Recording Script

| 項目 | 内容 |
|---|---|
| ステータス | Sprint 7 完成版（撮影リハーサル前最終） |
| 作成日 | 2026-04-30 |
| 作成者 | Phase 1-D Sprint 7 Generator |
| 対象 | Meta App Review 提出用スクリーンキャスト |
| 想定尺 | 7 分 30 秒（7 シーン × 平均 1 分） |
| 想定言語 | ナレーション英語 / UI 日本語 / 字幕英語焼き込み |
| 関連ドキュメント | `META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`, `PHASE_1D_META_INBOX_OVERVIEW.md` |

## 0. 撮影上の共通ルール（全シーン共通）

### 0-1. 動画フォーマット要件（Master Checklist v1.1 §0.4 準拠）

| 項目 | 値 | 備考 |
|---|---|---|
| 解像度 | **1920 × 1080**（Full HD） | 1280×720 でも可だが Meta は 1080p 推奨 |
| フレームレート | **60 fps**（30 fps でも可） | OBS 既定 60 fps 推奨 |
| コーデック | H.264 (mp4) | x264, CRF 18-22 推奨 |
| 音声 | AAC 128kbps、英語ナレーション | 必須（Meta は無音動画を不可と明記） |
| 字幕 | 英語字幕焼き込み（ハードサブ） | 推奨。SRT 別添も可 |
| 尺 | 30 秒以上、7 分以下 / シーンあたり | 全体 7 分 30 秒前後を狙う |
| ファイルサイズ | 50 MB 以下推奨（最大 1 GB） | 500 MB 超で Drive リンク併用 |
| ファイル名 | `salesanchor_meta_app_review_v1.mp4` | 単一動画で全 7 シーン連続再生 |

### 0-2. OBS 推奨設定

```
出力モード: 詳細
エンコーダ: x264 (CPU) または NVENC H.264
レート制御: CRF
CRF 値: 20
キーフレーム間隔: 2 秒
プロファイル: high
プリセット: medium
解像度: 出力 1920x1080 / キャンバス 1920x1080
FPS: 60
音声: 48kHz / ステレオ / 128kbps
音声入力: マイク（ナレーション） + デスクトップ音声 OFF（通知音漏洩防止）
```

### 0-3. ブラウザ・OS 共通設定

- 通知センター: **すべて Do Not Disturb / 集中モード ON**
- ブックマークバー: **非表示**（Cmd+Shift+B）
- 拡張機能: **すべて無効**（特に翻訳系・パスワード系）
- ズーム: **100%**（Cmd+0 でリセット）
- タブ: **撮影に必要なタブのみ**（不要タブを閉じる）
- ウィンドウサイズ: 1920x1080 を完全に占有（フルスクリーン推奨）
- マウスポインタ: **ハイライト表示 ON**（macOS は MousePosé / Windows は Mouseposé / KeyCastr 等）
- キー入力: **KeyCastr で表示**（テキスト入力時のみ表示、UI キーは非表示推奨）

### 0-4. テストアカウント

撮影前に以下が準備済であること（詳細は `META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`）：

- Sales Anchor: `review@salesanchor.jp` (Owner ロール) + 仮パスワード
- Test Facebook User: Meta Developer Portal の Test Mode で作成（Page admin 権限）
- Test Facebook Page: `HIGH LIFE JPN Test Page`（リアルな Page 名）
- Test Instagram Business Account: 上記 Page にリンク済
- Sender Side（メッセージ送信側）アカウント: 別 Facebook / Instagram テストユーザー 1 名

### 0-5. ナレーション収録のコツ

- **読み上げ速度**: 1 分 130-140 単語が目安（ゆっくり目）
- **発音**: アメリカ英語ベース、専門用語は明瞭に（"OAuth" は "オウオース"、"Messenger" は "メッセンジャー"）
- **句切り**: 文末で 0.5 秒、シーン切替で 1.5 秒の間
- **ノイズ**: USB コンデンサマイク + ポップフィルタ推奨、Krisp 等の AI ノイズ除去 OK

---

## 1. シーン構成サマリー

| # | 開始 | 終了 | 長さ | テーマ | 申請 Permission |
|---|---|---|---|---|---|
| 1 | 0:00 | 0:30 | 30 秒 | Intro: Sales Anchor dashboard overview | (前提) |
| 2 | 0:30 | 1:30 | 60 秒 | Connect Facebook Page via OAuth | `pages_show_list`, `pages_manage_metadata` |
| 3 | 1:30 | 2:30 | 60 秒 | Incoming Messenger message arrives in inbox | `pages_read_engagement` |
| 4 | 2:30 | 3:30 | 60 秒 | Sales rep replies to Messenger message | `pages_messaging` |
| 5 | 3:30 | 4:30 | 60 秒 | Connect Instagram Business account | `instagram_basic` |
| 6 | 4:30 | 5:30 | 60 秒 | Instagram DM received and replied | `instagram_manage_messages` |
| 7 | 5:30 | 6:30 | 60 秒 | Reply outside 24-hour window using Human Agent Tag | Human Agent Tag |
| 8 | 6:30 | 7:30 | 60 秒 | Data Deletion Callback demonstration | (Required by Meta) |

**カバー Permission**: `pages_show_list` / `pages_manage_metadata` / `pages_messaging` / `pages_read_engagement` / `instagram_basic` / `instagram_manage_messages` + Human Agent Tag + Data Deletion = **6 Permission + Human Agent Tag + Data Deletion 全カバー**。

---

## 2. シーン 1: Intro — Sales Anchor Dashboard Overview

**時間**: 0:00 - 0:30（30 秒）
**目的**: Sales Anchor が B2B SaaS CRM であり、Messenger/Instagram の受信箱（Inbox）が CRM のリードと紐づいて統合管理されることを冒頭で示す。

### 2-1. 画面操作

| 秒 | 操作 |
|---|---|
| 0:00 | ブラウザに `https://app.salesanchor.jp/login` を表示済の状態で開始（事前にロード） |
| 0:02 | Email 欄に `review@salesanchor.jp` を入力（KeyCastr で表示） |
| 0:06 | Password 欄に仮パスワードを入力（KeyCastr は伏字） |
| 0:10 | 「ログイン」ボタンをクリック |
| 0:12 | Dashboard 画面が表示される（リード件数、商談件数、最新通知などのサマリー） |
| 0:18 | 左サイドバーをマウスでなぞり、「Inbox」「Channels」「Leads」「Customers」の項目を順にハイライト |
| 0:25 | カーソルを画面中央に戻す |

### 2-2. 英語ナレーション

> "Welcome to Sales Anchor, a B2B SaaS CRM platform for Japanese small and mid-sized businesses. Sales reps manage leads, deals, and customer conversations all in one place. In this video, we will demonstrate how Sales Anchor integrates Facebook Messenger and Instagram Direct Messages into the CRM inbox, so sales reps can reply to customer inquiries from a single screen."

(約 55 単語 / 25 秒)

### 2-3. 撮影上の注意

- ログイン直後は若干ローディングが入るので、Dashboard が完全に描画されてからナビ操作に入る
- サイドバーの項目ハイライトはマウスを **ゆっくり** 動かす（1 項目あたり 1 秒以上停止）
- DevTools / 開発者向け表示（左下の "Logged in as ..." 等）は事前に消しておく

### 2-4. テストデータ要件

- `review@salesanchor.jp` アカウントが Owner ロールで作成済
- Dashboard に最低限のリードが数件表示されていること（空っぽは説得力に欠ける）
- 最新通知欄に Meta 関連通知が出ていないことを確認（Inbox シーンで初出にしたい）

---

## 3. シーン 2: Connect Facebook Page via OAuth

**時間**: 0:30 - 1:30（60 秒）
**目的**: `pages_show_list` と `pages_manage_metadata` を実演。Facebook Login で Page 一覧を取得し、選択 → `subscribed_apps` 登録までを通す。

### 3-1. 画面操作

| 秒 | 操作 |
|---|---|
| 0:30 | サイドバーの「Channels」をクリック → `/channels` へ遷移 |
| 0:33 | Channels 画面が表示される（接続済 Page 0 件の状態） |
| 0:36 | 「Facebook ページを接続」ボタンをハイライト → クリック |
| 0:38 | 別タブ／同タブで Facebook OAuth ダイアログが開く（`facebook.com/v19.0/dialog/oauth`） |
| 0:44 | Test User がすでにログイン済として表示される。「許可するもの」を確認: |
|  | - Pages Show List |
|  | - Pages Manage Metadata |
|  | - Pages Messaging |
|  | - Pages Read Engagement |
|  | - Instagram Basic |
|  | - Instagram Manage Messages |
| 0:50 | 「次へ」をクリック → Page 選択画面 |
| 0:54 | `HIGH LIFE JPN Test Page` を選択 → 「次へ」 |
| 0:58 | Instagram Business Account 連携確認画面（IG アカウント選択） → 「次へ」 |
| 1:02 | アクセス許可確認画面で「完了」 |
| 1:06 | Sales Anchor の `/channels/oauth/callback` にリダイレクト |
| 1:10 | コールバック処理中ローディング → Channels 一覧に `HIGH LIFE JPN Test Page` が表示される |
| 1:18 | Page カードの「Active」バッジ、`page_token_expires_at`（2 ヶ月後）を確認 |
| 1:25 | 完了 |

### 3-2. 英語ナレーション

> "Here in the Channels settings, an admin can connect their Facebook Pages. Clicking 'Connect Facebook Page' starts the standard Facebook Login flow. The user grants the six permissions our app needs: pages_show_list to fetch the Page list, pages_manage_metadata to subscribe to webhooks, pages_messaging and pages_read_engagement for Messenger conversations, plus instagram_basic and instagram_manage_messages for Instagram DMs. After selecting the Page and Instagram account, the app exchanges the short-lived token for a long-lived Page Access Token, registers webhook subscriptions on subscribed_apps, and stores the encrypted token in our database. The Page now appears as Active in the channels list."

(約 105 単語 / 55 秒)

### 3-3. 撮影上の注意

- Facebook OAuth ダイアログのレイアウトは Meta 都合で変わる可能性がある。撮影直前に同じ Test User で素振りしておく
- 6 Permission の一覧が画面に映り込む瞬間を **必ず 2 秒以上** 静止させる（審査担当が確認できるように）
- redirect_uri エラー（`URL_NOT_REGISTERED`）が出た場合は撮影中止 → Meta Developer Portal の Valid OAuth Redirect URIs を確認
- callback 後の Channels 一覧で **Page Access Token が一切表示されていない** こと（plaintext 露出 NG）を画面上で確認できるよう、要素検査を一瞬だけ表示すると審査の安心度が上がる（任意）

### 3-4. テストデータ要件

- Meta Developer Portal で本番 App の **Test Mode 有効** + Test User を 1 名作成
- Test User が `HIGH LIFE JPN Test Page` の Admin ロール
- Test User が Test Instagram Business Account の連携済
- VPS .env に `META_APP_ID`, `META_APP_SECRET`, `META_OAUTH_REDIRECT_URI=https://app.salesanchor.jp/channels/oauth/callback` が設定済
- Meta Developer Portal の **Valid OAuth Redirect URIs** に上記 redirect_uri を登録済

---

## 4. シーン 3: Incoming Messenger Message Arrives in Inbox

**時間**: 1:30 - 2:30（60 秒）
**目的**: `pages_read_engagement` を実演。送信側（別 Test User）から Messenger DM を送り、Sales Anchor Inbox に届くまでを示す。

### 4-1. 画面操作（画面分割: 左 Sales Anchor / 右 Messenger）

| 秒 | 操作 |
|---|---|
| 1:30 | Sales Anchor のサイドバーで「Inbox」をクリック → `/lead-chat` 遷移 |
| 1:34 | Inbox 画面が表示される（左ペイン: 会話リスト、右ペイン: メッセージ表示エリア） |
| 1:38 | カーソルを Messenger ウィンドウ（別画面）に移動。Messenger Web で `HIGH LIFE JPN Test Page` 宛にメッセージを書く: `Hello, I'd like to ask about your products.` |
| 1:50 | 送信ボタンクリック |
| 1:53 | Sales Anchor 側に戻る。10 秒以内（最大 polling 周期）に左ペインに新しい会話が出現 |
| 2:03 | 会話に未読バッジ（"1"）が表示される |
| 2:06 | 会話をクリック → 右ペインに `Hello, I'd like to ask about your products.` が inbound バブルで表示 |
| 2:12 | platform バッジ「Messenger」が確認できる |
| 2:16 | 24h バナー「You can reply for 23h 59m」が表示される |
| 2:22 | 既読バッジが消える（mark-read API 呼出後） |
| 2:28 | 完了 |

### 4-2. 英語ナレーション

> "Now let's see an incoming message. The Inbox shows all Messenger and Instagram conversations on the left, and message history on the right. When a customer sends a message to our connected Page, our webhook receives it, persists it to the database, and the inbox polls every ten seconds to refresh. As soon as the message arrives, an unread badge appears. Clicking the conversation marks it read and shows the full message thread. The 'Messenger' platform badge confirms which channel this conversation came from, and the 24-hour reply window is displayed at the top."

(約 100 単語 / 55 秒)

### 4-3. 撮影上の注意

- Messenger Web を別ウィンドウで開いておき、ウィンドウ切替を **Cmd+Tab で素早く** 行う（編集で切替部分は 0.3 秒程度に詰める）
- Polling は 10 秒間隔。送信から到着まで最大 10 秒待つので、ナレーションでこの「待ち」を埋める
- 未読バッジの数字が確認できる程度にズームしてキャプチャ
- 受信メッセージのタイムスタンプが「数秒前」になっていることを確認させる

### 4-4. テストデータ要件

- Sender 側 Facebook テストユーザー 1 名（Test User とは別、**Page Fan として登録済**）
- Sender が Page と過去にやり取りしていない（クリーン状態を撮影に使う）
- Webhook が Meta Developer Portal で `messages` フィールド subscribe 済
- VPS Discord 通知 worker は撮影中は止めるか、撮影に映らないテナント設定にする

---

## 5. シーン 4: Sales Rep Replies to Messenger Message

**時間**: 2:30 - 3:30（60 秒）
**目的**: `pages_messaging` を実演。Inbox 右ペインの返信フォームから Messenger 返信送信、相手側 Messenger に届くまでを示す。

### 5-1. 画面操作（画面分割: 左 Sales Anchor / 右 Messenger）

| 秒 | 操作 |
|---|---|
| 2:30 | シーン 3 から続けて、選択中の会話の右ペイン下部「返信を入力」フォームをハイライト |
| 2:35 | 入力欄に `Hi! Thank you for reaching out. Our products are listed on our website. Could you share which category interests you?` を入力 |
| 2:50 | 「送信」ボタンクリック |
| 2:52 | 送信中ローディングのバブル → 1 秒以内に成功 outbound バブルに切り替わる |
| 2:56 | バブル下に `RESPONSE` ラベルが表示される（24h 以内 → Standard Messaging） |
| 3:00 | 送信者（"You" or staff name）と送信時刻が表示 |
| 3:04 | カーソルを Messenger ウィンドウに切替 |
| 3:08 | Sender 側 Messenger に同じテキストの新着メッセージが表示される |
| 3:14 | 配信時刻が Sales Anchor 側送信時刻とほぼ一致することを示す |
| 3:22 | Sales Anchor に戻り、メッセージ履歴に inbound と outbound が時系列で並んでいることを確認 |
| 3:28 | 完了 |

### 5-2. 英語ナレーション

> "Now the sales rep replies. The reply composer at the bottom of the conversation lets the rep type a response and click Send. Because we are within 24 hours of the customer's last message, the messaging type is automatically RESPONSE — standard messaging under Meta's policy. The message is sent through the Send API using the encrypted Page Access Token, persisted as an outbound entry in our database, and immediately delivered to the customer on Messenger. The customer sees the reply in real time, and the sales rep sees a complete conversation thread."

(約 95 単語 / 55 秒)

### 5-3. 撮影上の注意

- Sender 側 Messenger ウィンドウは **撮影前に既読状態にしておく**（送信前は何もない状態）
- 送信ボタンクリックから outbound バブル表示まで、ネットワーク遅延次第。リハーサルで時間を計測しナレーションを調整
- `RESPONSE` ラベル表示部はズームレベルが必要なら拡大（虫眼鏡ハイライト）
- 失敗時のリトライは撮影外。事前リハで成功率 100% を担保

### 5-4. テストデータ要件

- シーン 3 から継続したセッション（同一会話）
- 24 時間以内の inbound メッセージあり（シーン 3 の受信を流用）
- staff `review@salesanchor.jp` が `messaging.send` permission を持つ Owner ロール

---

## 6. シーン 5: Connect Instagram Business Account

**時間**: 3:30 - 4:30（60 秒）
**目的**: `instagram_basic` を実演。シーン 2 で接続した Page にリンクされた Instagram Business Account が Sales Anchor に表示されることを示す。

### 6-1. 画面操作

| 秒 | 操作 |
|---|---|
| 3:30 | サイドバーの「Channels」をクリック |
| 3:33 | シーン 2 で接続した `HIGH LIFE JPN Test Page` カードを表示 |
| 3:38 | カードの Instagram セクションを拡大ハイライト: |
|  | - `instagram_username: @highlifejpn_test` |
|  | - `instagram_business_account_id: 17841...` |
| 3:46 | 「ℹ️」アイコン or 「詳細」リンクをクリック → 詳細パネルが開く |
| 3:52 | 詳細パネルで Instagram 連携状態を確認: |
|  | - Active: TRUE |
|  | - Subscribed Fields: `messages`, `messaging_postbacks` |
|  | - Connected At: 撮影日 |
| 4:02 | パネルを閉じる |
| 4:06 | カードの右上「切断」ボタンをマウスで指す（クリックはしない、シーン 8 で扱う） |
| 4:14 | カーソルを「Inbox」へ移動 → クリック準備（次シーンへの導入） |
| 4:25 | 完了 |

### 6-2. 英語ナレーション

> "When we connected the Facebook Page, we also gained access to its linked Instagram Business Account through the instagram_basic permission. Sales Anchor automatically discovered the Instagram username and business account ID, and stored them alongside the Page. The connected channel card shows both Messenger and Instagram details in one place. Admins can see when each channel was connected, which subscribed fields are active, and disconnect at any time. This unified view is the foundation for Instagram messaging."

(約 80 単語 / 55 秒)

### 6-3. 撮影上の注意

- Instagram Business Account ID は数字 17 桁前後。データ的に映って構わない（公開情報）
- Page の Test Account は事前に IG Business Account を **Page Roles** から正式リンク済（OAuth 中で初リンクは挙動が安定しない）
- 詳細パネルが UI 仕様にない場合は、カードの表示要素のみで完結させて構わない（過剰実装 NG）

### 6-4. テストデータ要件

- シーン 2 で接続した Page に IG Business Account がリンク済
- IG Business Account がプロアカウント（個人アカウント不可）

---

## 7. シーン 6: Instagram DM Received and Replied

**時間**: 4:30 - 5:30（60 秒）
**目的**: `instagram_manage_messages` を実演。Instagram DM 受信→ Inbox 表示 → 返信送信 → Instagram 側受信までを示す。

### 7-1. 画面操作（画面分割: 左 Sales Anchor / 右 Instagram モバイル風 UI）

| 秒 | 操作 |
|---|---|
| 4:30 | サイドバーで「Inbox」 → クリック |
| 4:33 | 別ウィンドウで Instagram Web/Mobile を Sender 側で開いておき、`@highlifejpn_test` 宛に DM 送信: `Hi, do you ship internationally?` |
| 4:44 | Sales Anchor Inbox 左ペインに新しい会話が出現（最大 10 秒）。**platform バッジが「Instagram」** であることを強調表示 |
| 4:52 | 会話をクリック → 右ペインに inbound バブルで `Hi, do you ship internationally?` 表示 |
| 4:56 | 24h バナー表示確認 |
| 5:00 | 返信フォームに `Yes! We ship to over 30 countries. Please share your country and we'll provide shipping options.` を入力 |
| 5:14 | 送信ボタンクリック |
| 5:16 | outbound バブル表示 → `RESPONSE` ラベル |
| 5:20 | Instagram ウィンドウに切替 → Sender 側に同じメッセージが届いていることを確認 |
| 5:28 | 完了 |

### 7-2. 英語ナレーション

> "Now the same flow happens for Instagram. A customer sends a Direct Message to our Instagram Business account. Our webhook receives the Instagram object payload, identifies the tenant by the Instagram business account ID lookup, and stores the message with the platform tag set to Instagram. The Inbox lists Messenger and Instagram conversations side by side, distinguished by a platform badge. The sales rep can reply using the same composer — instagram_manage_messages permission allows us to deliver the reply through the Instagram Messaging API. The customer receives the reply in their Instagram inbox immediately."

(約 100 単語 / 55 秒)

### 7-3. 撮影上の注意

- Instagram の DM 受信は端末の通知許可が必要。Sender 側端末で「メッセージを受け取る」設定済か事前確認
- platform バッジが Messenger と Instagram で **色分けされている** か、テキストで明確に「Instagram」と表示されていることを画面で確認
- iOS の Instagram アプリ画面はキャプチャ困難なので、PC ブラウザの instagram.com で再現するのを推奨
- DM スレッドのタイトル（`@highlifejpn_test`）が映るとよりわかりやすい

### 7-4. テストデータ要件

- Sender 側 Instagram テストアカウント（IG Business 不要、個人アカウント可）
- 過去 7 日以内に Sender → Page DM の履歴がない（クリーン状態）
- VPS Webhook が Instagram object 受信に対応済（Sprint 6 で実装済）

---

## 8. シーン 7: Reply Outside 24-Hour Window using Human Agent Tag

**時間**: 5:30 - 6:30（60 秒）
**目的**: Human Agent Tag を実演。24h 経過後に Standard Messaging では送信できないが、Human Agent Tag で送信できることを示す。

### 8-1. 画面操作

| 秒 | 操作 |
|---|---|
| 5:30 | Inbox を開いた状態で、**24h を経過した会話**（事前に用意）をクリック |
| 5:34 | 右ペインに過去の inbound メッセージが表示される（25-30h 前のタイムスタンプ） |
| 5:38 | 24h バナーが切替: 「Standard window expired. Replying with Human Agent Tag (valid up to 7 days).」 |
| 5:48 | 返信フォームに `Sorry for the late reply! Our team had a one-day off. Are you still interested in our products?` を入力 |
| 6:02 | 送信ボタンクリック |
| 6:04 | outbound バブル表示。**`MESSAGE_TAG` + `HUMAN_AGENT`** ラベルがバブル下に表示される |
| 6:10 | Sender 側 Messenger / Instagram で同メッセージ受信を確認（任意で画面切替） |
| 6:18 | バブルを再選択して詳細パネル: `messaging_type=MESSAGE_TAG, message_tag=HUMAN_AGENT` |
| 6:26 | 完了 |

### 8-2. 英語ナレーション

> "Sometimes a sales rep replies later than 24 hours after the customer's last message. Standard messaging would be blocked, but Meta provides the Human Agent Tag for cases where a real person needs to respond outside the standard window. Sales Anchor detects the elapsed time, automatically updates the banner, and applies messaging_type MESSAGE_TAG with the HUMAN_AGENT tag when the rep clicks Send. The customer receives the reply within Meta's allowed timeframe, and the message metadata clearly records that the Human Agent Tag was used. After 7 days, even Human Agent Tag cannot be used, and the send button becomes disabled."

(約 105 単語 / 55 秒)

### 8-3. 撮影上の注意

- **24h 経過済の会話を事前に用意するのが最大のポイント**。撮影前日に inbound DM を受け取り、24h 待ってから撮影する or DB の `created_at` を直接いじって 25h 前にする（後者は審査担当に「実機シナリオでない」と取られるリスクあり、できれば前者）
- バナー表示の切替（24h 内 → 24h-7d）が画面で確実に見えるよう、ハイライト or 矢印アノテーション推奨（編集時挿入）
- `HUMAN_AGENT` ラベルがバブル下に表示されない場合は、UI 改修が必要 → Phase 1-E

### 8-4. テストデータ要件

- 25-30h 前の inbound meta_message が DB にある会話を 1 件用意
- 当該 lead のテナントが本撮影アカウントと同じ
- staff が `messaging.send` permission を持つ

---

## 9. シーン 8: Data Deletion Callback Demonstration

**時間**: 6:30 - 7:30（60 秒）
**目的**: Meta が必須要件としている Data Deletion Callback（B1-B7 で実装済、Phase 5 で稼働中）の動作を示す。Meta 審査担当はこれを必ず確認するため、必須シーン。

### 9-1. 画面操作（画面分割: 左 Meta Developer Portal / 右 Sales Anchor Status Page）

| 秒 | 操作 |
|---|---|
| 6:30 | Meta Developer Portal を開く（`developers.facebook.com/apps/<APP_ID>/settings/basic/`） |
| 6:34 | 「Data Deletion Request URL」設定欄を表示。値: `https://api.salesanchor.jp/api/v1/meta/data-deletion` |
| 6:42 | Meta が公開している Data Deletion テストツール（あるいは curl で代替）から POST を送信: |
|  | ```bash``` |
|  | ```curl -X POST https://api.salesanchor.jp/api/v1/meta/data-deletion \``` |
|  | ```  -d "signed_request=..."``` |
|  | ```  ``` |
| 6:54 | レスポンスとして `{"url": "https://salesanchor.jp/deletion-status?code=DEL-YYYYMMDD-xxxx", "confirmation_code": "DEL-YYYYMMDD-xxxx"}` が返る（`DEL-YYYYMMDD-xxxx` は実装の confirmation code 形式 `_CONFIRMATION_CODE_RE`） |
| 7:00 | 上記 URL をブラウザで開く |
| 7:04 | Status Page が表示される: |
|  | - Confirmation Code: `DEL-YYYYMMDD-xxxx`（例: `DEL-20260430-a3f2`） |
|  | - Status: `pending` → `processing` → `completed`（リアルタイム更新） |
|  | - 削除予定データの説明（Meta 経由で受信した DM、紐づく lead 情報） |
| 7:18 | Status が `completed` になり、削除完了メールが発行されたことを示す（事前に SMTP 設定済の場合） |
| 7:26 | 完了 |

### 9-2. 英語ナレーション

> "Meta requires every app to provide a Data Deletion Callback. Sales Anchor's callback URL is registered in the Meta Developer Portal. When a user requests data deletion, Meta sends a signed request to our endpoint. We validate the signature, log the request, asynchronously delete all data associated with that user — Messenger and Instagram messages, leads, and audit log entries — and return a confirmation code with a public status page. The status page lets the user track the deletion in real time, and we send a completion email when finished. This complete flow is required by Meta's Platform Terms and is fully implemented in our app."

(約 105 単語 / 55 秒)

### 9-3. 撮影上の注意

- Meta Developer Portal のスクショは Test Mode を維持（本番アプリの設定値が映ってもよいが、API Secret は **絶対に映さない**）
- curl コマンドの `signed_request` は前後を伏せる（編集時にぼかし）
- Status Page に削除済データが映る場合は **PII を含まないテストデータ** にしておく（Sender 側 Test User の名前なら可）
- 完了メールの from address (`support@salesanchor.jp`) が映ると好印象

### 9-4. テストデータ要件

- Phase 5 で実装済の B1-B7 が VPS で稼働中（撮影日 = 2026-04-30 時点で稼働中）
- `PUBLIC_BASE_URL=https://salesanchor.jp` が VPS .env に設定済
- SMTP 設定（任意、推奨）
- テスト用 Facebook User の PSID で削除可能なデータが DB に存在
- 削除中の processing 表示が見たい場合は、Celery worker のキューを意図的に遅延させる（任意）

---

## 10. クロージングおよび編集後処理

### 10-1. クロージング（オプション）

- 動画の最後に 5 秒ほど Sales Anchor のロゴ + テキスト「Thank you for reviewing.」を表示する案
- 字幕焼き込み: 全シーンの英語ナレーションを SRT で別途用意し、ハードサブで焼き込む

### 10-2. 編集ツール候補

- macOS: iMovie（無料）、Final Cut Pro
- Windows: DaVinci Resolve（無料）、Adobe Premiere Pro
- 字幕焼き込み: ffmpeg + .srt（コマンド一発）
  ```bash
  ffmpeg -i recording.mp4 -vf "subtitles=script.srt:force_style='Fontsize=18'" -c:a copy salesanchor_meta_app_review_v1.mp4
  ```

### 10-3. アップロード前チェック

- ファイル名: `salesanchor_meta_app_review_v1.mp4`
- 解像度: 1920x1080
- 尺: 7-8 分
- 音声: 全シーンでナレーションが入っている
- 字幕: 英語ハードサブ
- ファイルサイズ: 1 GB 以下（推奨 500 MB 以下）
- Google Drive にアップロード → 共有リンク生成 → Master Checklist v1.1 に貼付

### 10-4. リハーサル必須項目

撮影本番前に **必ず通しリハ 1 回以上**：

- [ ] OBS の録画スタート/ストップが意図通り動く
- [ ] マイク音量が適切（音割れせず、聞こえないこともない）
- [ ] ブラウザがフリーズしない（Polling や OAuth で重くなる可能性）
- [ ] Sender 側の Messenger/Instagram からのメッセージが 10 秒以内に届く
- [ ] 24h 経過済の会話が Inbox に残っている
- [ ] Data Deletion Callback がローカル環境ではなく **VPS の本番** に向いている

---

## 11. 補足: 撮影で映してはいけないもの（PII / Secret）

- `META_APP_SECRET`、`METADATA_FERNET_KEY` の **生値**
- Page Access Token の **生値**
- 実顧客（HIGH LIFE JPN の本物の顧客）の名前・メール・電話番号
- 開発者個人の本名・メール（Test User の表示名は OK）
- VPS の SSH 鍵、IP アドレス（IP は OK だが、ポート番号と一緒に出すと攻撃面拡大）
- DevTools の Network タブで Authorization ヘッダ（Bearer token）

撮影中にうっかり映ってしまった場合は **編集で必ずぼかす**。1 か所でも残ると審査でリジェクトの可能性。

---

## 12. リハーサル＆撮影成功判定

- [ ] 全 8 シーン（Intro 含む）が連続して 7 分 30 秒前後で撮れた
- [ ] 申請 6 Permission すべてが、シーン 2-7 のいずれかで実演されている
- [ ] Human Agent Tag がシーン 7 で明示されている
- [ ] Data Deletion Callback がシーン 8 で動作確認できている
- [ ] PII / Secret が一切映っていない
- [ ] 英語ナレーションが全シーンで聞き取れる
- [ ] 字幕（英語ハードサブ）が焼き込まれている
- [ ] ファイル名・解像度・尺の最終チェック完了

すべて満たしたら **Master Checklist v1.1** にアップロード URL を記載 → Meta App Review 提出。

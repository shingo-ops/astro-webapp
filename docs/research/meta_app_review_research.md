# Meta API App Review 調査レポート

**作成日**: 2026-05-13  
**調査目的**: Sales Anchor の Meta App Review 通過に向けた情報収集  
**調査範囲**: YouTube 動画（transcript 解析）+ 技術ブログ・公式ドキュメント

---

## 発見した YouTube 動画

### 動画 1（Meta 公式）
- **タイトル**: Get started with the Messenger API for Instagram
- **URL**: https://www.youtube.com/watch?v=Pi2KxYeGMXo
- **チャンネル**: Meta for Developers
- **内容**: Instagram Messaging API の初期セットアップ手順（Conversations Conference 講演）
- **字幕**: 英語（手動）あり

### 動画 2（実践系）
- **タイトル**: n8n + Facebook Messenger: Full Setup Guide (Meta App, Graph API, Webhook Testing)
- **URL**: https://www.youtube.com/watch?v=CIKyqsg_jeE
- **公開**: 2025年5月
- **内容**: Meta App 作成から Webhook テストまでのフルセットアップ
- **字幕**: 英語（自動生成）

> **注**: 日本語の専用チュートリアル YouTube 動画は検索で発見できず。日本語コンテンツは Zenn・Qiita・ClassMethod などのテキスト記事が中心。

---

## Section 1: Meta 公式動画から得た知見（Pi2KxYeGMXo）

### テストモードに必要な標準アクセス権限（3種）

```
1. instagram_basic
2. instagram_manage_messages
3. pages_manage_metadata
```

- テストモードでのみ有効
- アプリに Role を持つユーザー、かつ Instagram テストアカウントに紐づくユーザーのみ動作

### 本番公開（Advanced Access）に必要なこと

同じ 3 パーミッションで **Advanced Access** を申請する（= App Review 必要）

### 自社ビジネス向けアプリのトークン取得方法

Facebook Login 実装なしで Graph API Explorer からトークンを発行できる:
1. Graph API Explorer で Facebook Page を指定
2. 3 つのパーミッションにアクセス付与
3. Instagram アカウントを接続
4. トークンをキャプチャ

### Webhook セットアップ手順（動画から抜粋）

1. Meta Developer Dashboard でアプリを開く
2. Webhook 製品を追加
3. Instagram オブジェクトを選択
4. Callback URL（自サーバー）と Verify Token を設定
5. `messages` をサブスクライブ
6. Page に対して page subscriptions を有効化（API 呼び出し必要）

---

## Section 2: App Review 申請手順（Chatwoot / Meta 公式ドキュメントより）

### Instagram API with Instagram Login（新 API）の場合

必要なパーミッション:
```
1. instagram_business_basic
2. instagram_business_manage_messages
3. human_agent（任意: 7日間返信ウィンドウが必要な場合）
```

### 申請ステップ（10 ステップ）

```
Step 1:  アプリ設定 → Website プラットフォームを追加
Step 2:  Instagram 製品 → "Go to App Review" をクリック
Step 3:  "Continue" でドキュメント確認
Step 4:  申請するパーミッション 3 つを選択 → "Continue to App Review"
Step 5:  Business Account であることを確認（必須）
Step 6:  データハンドリングの質問に全て回答
Step 7:  アプリ設定を完成（アイコン・プライバシーポリシー URL・カテゴリ）
Step 8:  審査手順を記入（ダッシュボードへのログイン方法・操作手順）
Step 9:  各パーミッションの使用理由・テストアカウント情報を記入
Step 10: "Submit for Review" をクリック
```

---

## Section 3: スクリーンキャスト要件（最重要）

### 基本要件

| 項目 | 要件 |
|------|------|
| 音声またはキャプション | **必須** |
| 粒度 | できるだけ詳細に記録 |
| マウス操作 | はっきりキャプチャ |
| ポップアップ・ブラウザ操作 | 全て記録 |
| 認証情報 | **非表示**（スーパー管理者 NG、テスト用アカウントを使用） |
| パーミッション数 | 各パーミッションごとに個別動画が必要 |

### 各パーミッションで示すべきもの

**instagram_business_basic 用**:
- ユーザーログイン（OAuth フロー）
- Instagram Business アカウント認証
- ユーザー名・ID・プロフィール画像の表示確認
- メッセージ受信時のメタデータ表示

**instagram_business_manage_messages 用**:
- メッセージ受信 → インボックスへの表示
- 返信機能の動作
- リアルタイム同期の実証

**human_agent 用**:
- 24 時間以上経過した会話を開く
- 現在の Meta 制限の説明
- 7 日間ウィンドウでの対応可能性の説明

**instagram_manage_messages（旧 API）用**:
- Bot Manager でのインスタンス作成
- メッセージ受信から返信まで

**pages_messaging（Messenger）用**:
- Messenger からの受信確認
- 返信の送信
- Webhook イベントの受信ログ

### 「unsend」対応の実証（2026 年プライバシー要件）

**2026 年からの新要件**: ユーザーが DM を unsend した場合の処理を動画で示すこと。

推奨デモ内容:
> 「ユーザーがメッセージを unsend した場合、当システムはメッセージを保存しない。unsend テンプレートに基づく返信を送信する。」

---

## Section 4: よくある却下理由と対策

| 却下理由 | 発生頻度 | 対策 |
|----------|----------|------|
| **スクリーンキャストの不完全** | 最多（2026年） | パーミッションごとに個別動画、完全なフローを示す |
| **過剰なパーミッション申請** | 多い | 現時点で実際に使うものだけ申請 |
| **プライバシーポリシーの不備** | 多い | 即時読み込み・ビジネス名・データ利用方法を明記 |
| **使用目的の不明確** | 多い | 英語で約 2,500 文字、具体的なユースケースを記述 |
| **テストユーザーの問題** | 中程度 | Meta 審査官専用アカウントを活用（実テスト情報不要） |
| **Facebook Login 未実装** | 中程度 | 他者のビジネス向けなら必須、自社向けなら不要 |
| **PC/モバイル両方の動画なし** | 中程度 | 多プラットフォーム対応アプリは両方の動画が必要 |
| **アプリ設定の不完全** | 低い | アイコン・ポリシー URL・カテゴリを全て登録 |

---

## Section 5: 「自社ビジネス向け」申請の特別ルール

Sales Anchor が申請するケースは「複数テナント（他社のビジネス向け）アプリ」なので以下が適用される。

### 他社のビジネス向け（ISV・SaaS）の場合

- **Facebook Login の実装が必須**（各テナントが自社 Instagram/Facebook Page を接続するため）
- `business_management` パーミッションが依存権限として必要
- 申請フォームで「他のビジネスが自社の Instagram アカウントを接続する」ことを明示
- スクリーンキャスト: テナントが OAuth フローで接続する様子を示す

### 自社ビジネスのみ向けの場合

- Facebook Login 不要（Graph API Explorer でトークン直接生成）
- Primary Experience を Automated または Live Agent で選択

---

## Section 6: 審査通過のコツ（実践者の知見まとめ）

### 言語

**申請書類は必ず英語で記述**。日本語は審査通過率が下がる（複数の日本語ブログで言及）。

### テスト認証情報の提供

- Meta 審査官は「開発者アカウントを持つ特別なレビューアー」を使用する
- テストユーザー情報を提供する場合は「スーパー管理者ではないテスト用アカウント」を使う
- 2 要素認証が必要な場合：AWS Lambda 等で動的 OTP 提供ページを構築した事例あり（Medium 記事）

### スクリーンキャスト

- "Loom" などの録画ツールを使用（ナレーション付き）
- 「このパーミッションはここで使っている」と明示しながら操作
- 審査官が「このアプリを初めて見る人」として理解できる粒度で説明

### 説明文

- 「なぜこのパーミッションが必要か」を論理的に説明
- アクセス頻度・具体的な処理フローを含める
- 依存パーミッションは「〇〇のための依存権限である」と明示

### 審査期間の目安

| 状況 | 期間 |
|------|------|
| 標準アクセス | 2〜4 日 |
| 高度なアクセス | 4〜7 日 |
| 却下後の再申請 | 3〜5 日追加 |
| AI 関連の場合 | さらに 1 ラウンド追加 |

---

## Section 7: Sales Anchor への直接適用

### 必要なパーミッション（推定）

Sales Anchor は「他社テナントの Facebook Page / Instagram アカウントを管理する SaaS」なので:

```
必須:
- pages_messaging          ← Messenger DM 受信・送信
- instagram_manage_messages ← Instagram DM 受信・送信（旧 API）
  OR instagram_business_manage_messages ← 新 API 使用時
- pages_manage_metadata    ← Webhook サブスクリプション管理
- pages_show_list          ← テナントが接続する Page の一覧

依存:
- business_management      ← Facebook Login での Page 管理権限
- instagram_basic          ← Instagram プロフィール情報
```

### スクリーンキャスト撮影のチェックリスト

```
Scene 1: Meta App Developer Dashboard でのアプリ設定確認
Scene 2: テナントが Facebook Login で接続するフロー（OAuth）
Scene 3: Instagram Business Account と Facebook Page の接続確認
Scene 4: Webhook 設定画面（subscribed_fields: messages）
Scene 5: テスト DM 送信 → Sales Anchor Inbox に届く様子
Scene 6: 担当者が返信 → 送信者の Messenger/Instagram に届く確認
Scene 7: Unsend 処理のデモ（2026 年必須）
```

### 現在の障害（ADR-024 / ADR-025 参照）

1. **subscribed_apps 未登録**: PR #335 (ADR-024) でコードは修正済み、再接続が必要
2. **METADATA_FERNET_KEY 不一致**: PR #337 (ADR-025) でデプロイ済み、VPS 復旧後に確認
3. **VPS SSH 停止中**: Sakura コンソールから `sudo systemctl start ssh` で復旧

→ これらを解消してから撮影再開

---

## 参考リソース

### YouTube 動画
- [Get started with the Messenger API for Instagram (Meta Official)](https://www.youtube.com/watch?v=Pi2KxYeGMXo)
- [n8n + Facebook Messenger: Full Setup Guide](https://www.youtube.com/watch?v=CIKyqsg_jeE)

### 公式ドキュメント
- [App Review - Messenger Platform](https://developers.facebook.com/docs/messenger-platform/app-review/)
- [Apps For Your Own Business - Instagram Messaging](https://developers.facebook.com/docs/messenger-platform/instagram/app-review/apps-for-your-own-business/)
- [App Review - Instagram Platform](https://developers.facebook.com/docs/instagram-platform/app-review/)

### 実践ガイド
- [Chatwoot: Instagram App Review 手順](https://developers.chatwoot.com/self-hosted/instagram-app-review)
- [BotSailor: How to Submit for Instagram App Permission Approval](https://botsailor.com/blog/how-to-submit-for-instagram-app-permission-approval-for-botsailor-whitelabel-agency-users)
- [Meta App Approval Guide: Avoid Rejections (2025)](https://www.saurabhdhar.com/blog/meta-app-approval-guide)
- [ClassMethod: Instagram Graph API の審査を申請して承認されるまで](https://dev.classmethod.jp/articles/instagram-graph-api-approved-for-review/)
- [Zenn: Instagram API の Meta 申請方法の調査](https://zenn.dev/manase/scraps/7cae094951683c)
- [Medium: How to Get Your Meta App Approved (without test users)](https://medium.com/@chriscouture/how-to-get-your-meta-facebook-app-approved-in-2023-tips-code-snippets-for-navigating-reviews-c1305da5f929)

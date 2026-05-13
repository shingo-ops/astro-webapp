# インシデントレポート: Meta Webhook 受信停止 (2026-05-11 16:38 JST ～ 継続中)

**作成日**: 2026-05-13 03:50 JST  
**作成者**: Claude Code (Terminal セッション)  
**ステータス**: 調査中・VPS SSH 停止中・Meta 側 webhook POST 未再開  
**関連 ADR**: ADR-024, ADR-025  

---

## Section 1: タイムライン（5W2H 形式）

### 全イベント時系列（UTC / JST 対照）

| UTC | JST | Who | What | How | 確定度 |
|-----|-----|-----|------|-----|--------|
| 5/11 01:52 | 5/11 10:52 | shingo-ops | PR #328 (ADR-022 UI刷新) → main マージ、deploy 実行 | GitHub Actions | [確定] |
| 5/11 02:09 | 5/11 11:09 | shingo-ops | PR #330 (サイドバーロゴ修正) → main、deploy | GitHub Actions | [確定] |
| 5/11 02:17 | 5/11 11:17 | shingo-ops | PR #331 → main、deploy | GitHub Actions | [確定] |
| 5/11 02:31 | 5/11 **11:31** | shingo-ops | PR #332 → main → **BLACKOUT前の最終デプロイ** | GitHub Actions | [確定] |
| 5/11 07:38:25 | 5/11 **16:38:25** | Meta (173.252.127.22) | `POST /api/v1/webhook/messenger` 200 → Sales Anchor **最後の受信成功** | nginx log | [確定] |
| 5/11 07:38:25 〜 | 5/11 16:38〜 | Shingo | Meta App Dashboard で何らかの操作（Instagram 設定変更？Page Role/Test User/Permission？） | Meta Dashboard UI | [推定・要後日確認] |
| 5/12 01:00 | 5/12 **10:00** | Shingo | "Hello / Test" を送信 → Sales Anchor Inbox 未着を確認（**blackout 確認時刻**） | Meta Messenger | [確定] |
| 5/12 03:00 | 5/12 12:00 | Celery cron | `meta_token_refresh_failed` audit_log 記録 (`EncryptionConfigurationError: decrypt_failed`) | audit_logs | [確定] |
| 5/12 04:38 | 5/12 13:38 | Claude Max | ADR-024 実装: PR #335 作成 (`claude-impl/20260512-043851`) | claude-pipeline.yml | [確定] |
| 5/12 05:01 | 5/12 **14:01** | Shingo | PR #335 → develop マージ | GitHub | [確定] |
| 5/12 05:28 | 5/12 14:28 | Claude Max | ADR-025 実装: PR #336 作成 (`claude-impl/20260512-052856`) | claude-pipeline.yml | [確定] |
| 5/12 05:36 | 5/12 **14:36** | Shingo | PR #336 → develop マージ | GitHub | [確定] |
| 5/12 05:43 | 5/12 **14:43** | shingo-ops | PR #337 (release) → main、**deploy 実行** → ADR-024+025 本番適用 | GitHub Actions | [確定] |
| 5/12 05:43〜 | 5/12 14:43〜 | deploy.yml | METADATA_FERNET_KEY を GitHub Secrets 現在値で VPS .env に上書き (ADR-025 効果) | deploy.yml sed 方式 | [確定] |
| 5/12 ~05:57 | 5/12 **~14:57** | Shingo | OAuth 再接続フロー実行（connect_callback → subscribe_page_to_app → ig_subscribe_error） | Sales Anchor UI | [推定・要確認] |
| 5/12 08:33:08 | 5/12 **17:33:08** | Meta (173.252.79.113) | `GET /api/v1/webhook/messenger?hub.challenge=134465499 → 200` (**Meta が webhook URL を再確認**) | nginx log | [確定] |
| 5/12 11:01 | 5/12 **20:01** | Shingo | "Hi, I have a question..." DM 送信（Meta Inbox に着信、Sales Anchor 未着） | Meta Messenger | [確定] |
| 5/12 11:57-11:59 | 5/12 **20:57-20:59** | Shingo | "Test Messenger webhook..." DM 送信 → Sales Anchor nginx に POST なし | Meta Messenger | [確定] |
| 5/12 ~12:25 | 5/12 **~21:25** | Claude Code (Terminal) | Graph API `POST /664490526747447/subscribed_apps` を curl で手動実行 → `{"success":true}` | Graph API curl | [確定] |
| 5/12 ~12:25〜 | 5/12 ~21:25〜 | Claude Code (Terminal) | Graph API `GET /664490526747447/subscribed_apps` で subscribed_fields 確認 | Graph API curl | [確定] |
| 5/12 17:37 | 5/13 **02:37** | Shingo | "Test after curl re-subscribe" DM 送信 → 依然 Sales Anchor 未着 | Meta Messenger | [確定] |
| 5/12 17:02 | 5/13 **02:02** | GitHub Actions | PR #339 (ADR-021 J1/J2 fix) deploy 成功 | GitHub Actions | [確定] |
| ~5/13 03:xx | ~5/13 03:xx | 不明 | **VPS SSH ポート 22 停止**（Connection Refused）→ 原因未特定 | nc port check | [確定・原因推定中] |
| 5/13 03:45 | 5/13 **03:45** | Claude Code (Terminal) | PR #340 (ADR-025 再実装) 作成・push →**後述の矛盾あり** | git push | [確定] |

### WHY: webhook が止まった推定トリガー

[推定] 5/11 16:38 JST の最終受信以降、**Shingo が Meta App Dashboard で何らかの操作**を行い、Meta 内部で Page 664490526747447 の subscribed_apps エントリが無効化または削除された。具体的操作内容は後日 Dashboard 変更履歴で確認要。

---

## Section 2: git / GitHub 完全履歴（5/10-5/13）

```
6dd4abc 2026-05-13 03:45 +0900  fix: ADR-025 deploy.yml環境変数注入を常時上書きに修正 + 運用ガイドライン整備  ← PR #340 (Claude Code 今夜、重複実装)
bef80ba 2026-05-12 14:20 +0900  docs: ADR-025: Meta連携の運用整備強化（deploy.yml修正・ガイドライン強化）
7cdc227 2026-05-12 14:01 +0900  feat(meta): ADR-024 Meta連携の構造的不整合修正 (#335)
1affbb3 2026-05-12 13:38 +0900  feat(meta): ADR-024 Meta連携の構造的不整合修正
b78d64f 2026-05-12 13:22 +0900  docs: ADR-024: Meta連携の構造的不整合の修正
d36b554 2026-05-11 16:29 +0900  docs: ADR-023: スタッフライフサイクルの3層同期化  ← docs only (no deploy)
2240a1e 2026-05-11 11:31 +0900  Merge pull request #332 (BLACKOUT前の最終デプロイ)
9dd35dd 2026-05-11 11:31 +0900  fix(ui): サイドバーロゴをHTMLテキストからlogo.png画像に変更
aaa3224 2026-05-11 11:30 +0900  Add files via upload
2857ebc 2026-05-11 11:17 +0900  Merge pull request #331
841802b 2026-05-11 11:09 +0900  Merge pull request #330
05cbe8d 2026-05-11 11:02 +0900  fix(ui): サイドバーロゴをアイコン常時表示+HTMLテキスト方式に修正
62b4079 2026-05-11 10:55 +0900  Merge pull request #329
3ffc460 2026-05-11 10:52 +0900  Merge pull request #328 (ADR-022 UI刷新)
565677a 2026-05-11 10:48 +0900  Add files via upload
5d137d5 2026-05-11 10:28 +0900  feat(ui): UIをMeta Business Suite風に刷新 (ADR-022)
7353eca 2026-05-11 07:43 +0900  feat(ui): UIをMeta Business Suite風に刷新 (ADR-022)
b4abcce 2026-05-11 07:23 +0900  Merge pull request #327
...（5/10以前略）
```

**重要確認**: 5/11 11:31 JST（PR #332）以降から 5/12 13:38 JST（ADR-024 作業開始）まで約 26 時間、main への**コードコミット・デプロイはゼロ**。デプロイが blackout の原因ではないことが確定。

---

## Section 3: PR 状態の真実（矛盾の説明）

### PR 一覧

| PR | タイトル | 作成日時 (JST) | マージ日時 (JST) | 状態 |
|----|---------|--------------|-----------------|------|
| #334 | Claude Max ADR implementation (ADR-023) | 5/11 16:49 | — | **OPEN（未マージ）** |
| #335 | Claude Max ADR implementation (ADR-024) | 5/12 13:38 | 5/12 14:01 | MERGED → develop |
| #336 | Claude Max ADR implementation (ADR-025) | 5/12 14:28 | 5/12 14:36 | MERGED → develop |
| #337 | release: ADR-024 + ADR-025 Meta integration fixes | 5/12 14:36 | 5/12 **14:43** | MERGED → **main** (DEPLOYED) |
| #338 | feat: ADR-021 J1+J2 fix | 5/12 16:06 | 5/12 16:38 | MERGED → develop |
| #339 | release: ADR-021 J1+J2 fix | 5/12 16:40 | 5/13 02:02 | MERGED → **main** (DEPLOYED) |
| #340 | fix: ADR-025 deploy.yml環境変数注入バグ修正 | 5/13 03:45 | — | **OPEN（今夜 Claude Code が作成）** |

### 矛盾の解明

**PR #336（Claude Max）vs PR #340（Claude Code）の重複**

- PR #336 は Claude Max が claude-pipeline.yml で自動生成。ADR-025 を完全実装（deploy.yml sed 方式・CLAUDE.md 3 セクション・key rotation doc）。PR #337 経由で **5/12 14:43 JST に本番デプロイ済み**。
- 今夜の Terminal セッション（Claude Code）では「VPS SSH が使えない、ローカルの develop が古いまま」の状態で ADR-025 が未実装と誤認し、PR #340 を作成した。
- **PR #340 は PR #336 の重複実装**。内容は本質的に同じだが、deploy.yml の書き方が微妙に異なる（#336 は `sed -i.bak + heredoc`、#340 は `sed -i + 個別 echo`）。
- 明日朝の対応: PR #340 は **クローズ（CLOSE）** が適切。origin/develop をベースに既に #336 の内容が入っている。

### PR #335（ADR-024）の実装内容

コミット `7cdc227` が main に入っている。変更ファイル:

```
backend/app/routers/meta_inbox.py               (+40行)
backend/app/services/meta_graph.py              (+100行)
backend/app/tasks/verify_meta_subscriptions.py  (新規・360行)
backend/tests/test_meta_graph.py                (+117行)
backend/tests/test_meta_oauth_endpoints.py      (+151行)
backend/tests/test_verify_meta_subscriptions.py (新規・383行)
backend/app/celery_app.py                       (+6行)
```

実装された機能:
- `subscribe_ig_user_to_app()`: IG Business Account への subscribe（ただし Messenger Platform では OAuthException #3 で必ず失敗）
- `get_page_subscribed_apps()`: GET で登録済み App を確認
- `verify_meta_subscriptions` Celery タスク（毎日 04:30 JST）
- meta_inbox.connect_callback に IG subscribe + 登録後 verification を統合

**残存バグ（ADR-026 起案根拠）**: connect_callback の verification は `our_app_id in app_ids` だけを確認。`subscribed_fields` の内容を検証しない。Meta の GET レスポンスが `subscribed_fields` なしで `id/name` のみ返すケースで false-positive になる。

---

## Section 4: GitHub Actions deploy 履歴（直近 20 件から関連抜粋）

```
Run ID         | 結論    | 実行日時 (UTC)          | 対象コミット・タイトル
---------------|---------|------------------------|----------------------------------------
25749658420    | success | 2026-05-12T17:02:24Z   | release: ADR-021 J1+J2 fix (#339)         ← 最新
25715887171    | success | 2026-05-12T05:43:37Z   | PR #337: ADR-024+025 Meta fixes            ← ADR-025 初デプロイ
25647250477    | success | 2026-05-11T02:32:31Z   | PR #333: develop→main (サイドバーロゴ)
25647192101    | success | 2026-05-11T02:30:19Z   | Add files via upload
25646848691    | success | 2026-05-11T02:17:22Z   | PR #331: develop→main
25646270366    | success | 2026-05-11T01:55:04Z   | PR #329: ADR-022 UI刷新
25646110963    | success | 2026-05-11T01:48:52Z   | Add files via upload                       ← PR #328 直後
25641393744    | success | 2026-05-10T22:23:14Z   | PR #327: develop→main
```

**重要**: 5/11 02:32 UTC（11:32 JST、PR #333）〜 5/12 05:43 UTC（14:43 JST、PR #337）の間、**deploy は 26 時間ゼロ**。Blackout は deploy 無関係。

---

## Section 5: 今夜のセッションで実行した変更操作

### SSH セッション（sudo 系コマンド）

セッション開始〜終了にかけて以下を実行（詳細タイムスタンプは JSONL ログ参照）:

1. **診断クエリ系（読み取りのみ）**
   - `docker compose exec postgres psql -U jarvis -d jarvis_db` 複数回（meta_messages, audit_logs, tenant_meta_config）
   - `docker compose logs nginx backend` 各種 grep
   - `docker compose exec backend python3 -c "decrypt(page_access_token)"` → Page Access Token を復号

2. **Meta Graph API 操作（書き込みあり）**
   - `curl POST https://graph.facebook.com/v25.0/664490526747447/subscribed_apps` with `subscribed_fields=messages,messaging_postbacks,message_reactions,message_reads,messaging_handovers` → **`{"success":true}`**
   - 実行時刻: ~5/12 21:25 JST（Shingo 承認済み）

3. **ローカル git 操作（今夜作成）**
   - `git checkout -b feature/morimoto/adr-025-meta-operational-hardening`
   - `.github/workflows/deploy.yml` 修正（sed 方式）
   - `docs/operations/meta_encryption_key_rotation.md` 新規作成
   - `CLAUDE.md` 3 セクション追加
   - `git commit` + `git push` + `gh pr create` → PR #340（後述の矛盾あり）

### 実行しなかった操作

- VPS .env の直接編集: **なし**（SSH 停止前も実施せず）
- docker compose restart / down: **なし**
- DB の書き込み（INSERT/UPDATE/DELETE）: **なし**（読み取りのみ）
- Meta Dashboard の変更: **なし**（操作は Shingo のみ）

---

## Section 6: VPS SSH 停止のタイミング特定

### 最後の SSH 成功

セッション中の最後に SSH 経由で docker logs を取得していた時刻はセッション要約から「5-phase investigation」の最中。具体的には `[4.1] Meta IP access history 72h` の nginx log 取得が最後の SSH 成功確認操作。

### Connection Refused 確認

- ローカルから `nc -z -w5 49.212.137.46 22` → exit code 1（Connection Refused）
- ポート 2222, 22022 も同様に Connection Refused
- `ssh -v` 出力: `connect to address 49.212.137.46 port 22: Connection refused`（timeout ではなく即 refused）

### SSH 停止の原因候補

[推定 A] fail2ban が Claude Code の SSH セッション（多数の短時間接続）を攻撃と誤認してブロック  
[推定 B] UFW の設定が一部のコマンドで変更された（ただし Claude Code は UFW 変更コマンドを実行していない）  
[推定 C] sshd サービスが何らかの理由でクラッシュ / 停止  
[推定 D] PR #339 deploy（5/13 02:02 JST）時に `docker compose up -d --build` でホストのネットワーク設定が一時変化し、sshd が影響を受けた  

### 復旧方法

Sakura VPS コントロールパネル → コンソール接続 → `sudo systemctl start ssh` および `sudo fail2ban-client unban <IP>` で復旧可能。

---

## Section 7: Meta 側エビデンス

### 7-1. Page Inbox に存在するメッセージ（全件）

Meta Graph API `GET /664490526747447/conversations?fields=messages` で取得（セッション中 Shingo が実行）:

```
メッセージ1: 2026-05-11 16:38 JST  "Hello"         sender=26628309676818465  → Sales Anchor 受信 ✓
メッセージ2: 2026-05-12 10:00 JST  "Hello"         （送信者同一？）            → Sales Anchor 未着 ✗
メッセージ3: 2026-05-12 10:01 JST  "Test"          （送信者同一？）            → Sales Anchor 未着 ✗
メッセージ4: 2026-05-12 20:58 JST  "Hi, I have a question..."                → Sales Anchor 未着 ✗
メッセージ5: 2026-05-12 20:58 JST  "Test Messenger webhook..."               → Sales Anchor 未着 ✗
メッセージ6: 2026-05-13 02:37 JST  "Test after curl re-subscribe"           → Sales Anchor 未着 ✗（curl後）
```

**`subscribed_apps` 再購読前後の状態変化**:

```
Before (GET 確認):
  {"data": [{"id": "<app_id>", "name": "Sales Anchor"}], "paging": {...}}
  → subscribed_fields キーなし（= name のみ登録、fields未購読）

After (curl POST → GET 確認):
  {"data": [{"id": "<app_id>", "name": "Sales Anchor",
    "subscribed_fields": ["messages","messaging_postbacks","message_reactions","message_reads","messaging_handovers"]}]}
  → subscribed_fields 確認 ✓
```

### 7-2. nginx Meta IP アクセス履歴（直近 72h）

```
69.171.231.28  2026-05-10 16:36 UTC  GET  /robots.txt                          206  facebookexternalhit/1.1
173.252.127.22 2026-05-11 07:38:25 UTC  POST /api/v1/webhook/messenger          200  facebookexternalua  ← 最後のPOST
173.252.79.113 2026-05-12 08:33:08 UTC  GET  /api/v1/webhook/messenger?hub.challenge=134465499...  200  facebookplatform/1.0
```

**空白**: 5/11 07:38:25 UTC から 5/12 08:33:08 UTC まで **約 25 時間** Meta からの POST が完全に消えている。

### 7-3. Sales Anchor DB で確認した状態

```sql
-- tenant_004.meta_messages（5/12 調査時点）
id=1, created_at=2026-05-11 16:38:25+09, direction='inbound', platform='messenger',
message_id='m_XqdJ91KLC54En5TObDWUfsnb3j-PisMPBjRYGF_eegZrENAMijpdW8xSbX3JTRU8ekcaNH9hawojXho7AjsSMg',
message_text='Hello', lead_id=1, page_id='664490526747447', sender_id='26628309676818465'

-- tenant_004.audit_logs（5/12 調査時点）
2026-05-12 03:00 JST  action='meta_token_refresh_failed'
  new_data={"reason":"decrypt_failed","page_id":"664490526747447","error":"EncryptionConfigurationError"}

2026-05-12 08:31 JST  action='mark_messages_read'
  new_data={"lead_id":1,"staff_id":7,"marked_count":1}

-- public.tenant_meta_config（5/12 調査時点）
subscribed_fields=NULL  ← DBに「接続済み」レコードあるがMeta側subscribeなし
```

---

## Section 8: Sales Anchor 側の状態（各レイヤー確認）

全レイヤーで **Sales Anchor 側に問題なし** を確認。

```
UFW:
  443/tcp    ALLOW IN    Anywhere      ← Meta からの HTTPS 通信許可
  22/tcp     ALLOW IN    自宅IP等      

iptables:
  Meta IP レンジ (173.252.0.0/16, 69.171.0.0/16 等) のブロックなし [確定]

fail2ban:
  Meta IP アドレス なし [確定]

nginx:
  HTTPS 443 → upstream backend:8000 → /api/v1/webhook/messenger
  rate limit: 30r/s (zone=api) + burst=50 → 問題なし
  TLS: 有効 (Let's Encrypt)

エンドポイント確認:
  curl -X POST https://api.salesanchor.jp/api/v1/webhook/messenger → 403
  （HMAC 検証失敗 = 正常動作）

GET verify:
  Meta が hub.challenge 送信 → Sales Anchor が 200 + challenge 文字列返却
  5/12 08:33 UTC に nginx log で確認済み [確定]

backend コンテナ:
  起動中、health check OK [確定（診断時）]
```

---

## Section 9: 確定した真因と推定メカニズム

### [確定] Sales Anchor 側の全レイヤーは正常

webhook を「受け取れない」状態ではない。Meta が「送ってこない」状態。

### [確定] METADATA_FERNET_KEY 不一致は別の障害

`meta_token_refresh_failed` (EncryptionConfigurationError) が 5/12 03:00 JST から発生。これはトークン自動リフレッシュの失敗であり、webhook 受信の直接阻害要因ではない。（webhook 受信にページアクセストークンの復号は不要）

ただし: 2026-05-01 の鍵ローテーション以降、暗号化されたトークンが復号不能 → トークン有効期限切れ（約 60 日）までに再接続しないと Meta 連携全停止リスクがあった。

### [確定] curl による subscribed_apps 再購読後も webhook が届かない

5/12 21:25 JST の curl POST → `{"success":true}`  
5/13 02:37 JST の テスト DM → Sales Anchor 未着

これは以下のいずれかを示す:

**H1 [推定・有力]: Meta Development Mode でのテストユーザー制限**

Meta App が Development Mode の場合、webhook POST は**アプリ Role を持つテストユーザーからの DM にのみ**送信される。samuraisoul_katana の Test User 承認が 5/11 以降に期限切れまたは無効化された可能性。

**H2 [推定]: Messenger Platform vs Instagram Graph API の混同**

- 最終受信（5/11 16:38）は `platform=messenger`（Facebook Page への Messenger DM）
- その後の失敗テストが Instagram DM の場合は別 subscription が必要
- `subscribe_ig_user_to_app()` が OAuthException #3 で失敗（Messenger Platform app では対応外）
- Instagram DM を受信するには Instagram Graph API の `/{ig_user_id}/subscribed_apps` が機能する App Type が必要

**H3 [推定]: Meta Dashboard 操作による subscribed_apps の自動無効化**

5/11 16:38〜5/12 10:00 の間に Shingo が Dashboard で Page Role / Permission / Test User 設定を変更した際、Meta 内部で接続済み App の subscription が再検証され、何らかの理由で無効化された。

### [確定] git log から判明したこと

5/11 11:31 JST（最終デプロイ）〜 5/11 16:38 JST（最終 webhook 受信）の間に 5 時間のタイムラグがあり、デプロイが直接の引き金ではない。最終 webhook 受信後にのみ Meta 側で何かが変わった。

---

## Section 10: 明日への引き継ぎ事項

### 優先度 S: 即時対応（VPS 復旧次第）

**[S-1] VPS SSH 復旧**（Shingo が Sakura VPS コンソールから実施）

```bash
# Sakura コンソールで直接ログイン後
sudo systemctl status ssh
sudo systemctl start ssh
sudo fail2ban-client status sshd
sudo fail2ban-client unban --all  # 必要なら
```

**[S-2] PR #340（ADR-025 重複実装）のクローズ**

PR #336（Claude Max）が既に ADR-025 を実装・デプロイ済み。PR #340 は重複。  
対応: `gh pr close 340` またはコメントを付けてクローズ。

**[S-3] PR #334（ADR-023）のレビュー判断**

5/11 16:49 JST 作成、OPEN のまま。ADR-023（スタッフライフサイクル 3 層同期）の実装。Blackout 調査と無関係だが積み残し。

### 優先度 A: Meta App Review 撮影再開前に必須

**[A-1] VPS の METADATA_FERNET_KEY 整合確認**

ADR-025（PR #337）で deploy.yml が sed 方式に変わり、PR #337 デプロイ（14:43 JST）以降は GitHub Secrets の値が .env に書かれているはず。VPS 復旧後に確認:

```bash
ssh ubuntu@49.212.137.46
grep METADATA_FERNET_KEY /home/ubuntu/salesanchor/.env
```

**[A-2] Channels 画面から Page 664490526747447 を切断 → 再接続**

DB の tenant_meta_config レコードが手動 INSERT で不正な状態。正規 OAuth フローで再接続すれば:
- Page Access Token が新しい METADATA_FERNET_KEY で再暗号化
- subscribed_apps が正しく登録（ADR-024 のコードが実行される）

**[A-3] Meta App Dashboard での確認**（Shingo 操作）

- Webhook Subscriptions: `messages`, `messaging_postbacks` が有効か
- Test Users: samuraisoul_katana が有効なテストユーザーとして登録されているか
- App Mode: Development Mode になっているか（Production Mode では webhook 制限が異なる）
- 5/11 16:38 以降の Dashboard 変更履歴を確認（Page Role / Permission変更）

### 優先度 B: ADR 起案（来週以降）

**[B-1] ADR-026: subscribe_page_to_app の検証ロジック強化**

現在の ADR-024 実装（PR #335 の verification）が `app_id in app_ids` のみチェックで `subscribed_fields` の内容を確認していない。修正が必要:

```python
# 現在（バグ）
verification = {
    "self_app_subscribed": our_app_id in app_ids,  # True でも subscribed_fields=[] の可能性
}

# 修正後
apps_with_fields = {str(a.get("id")): a.get("subscribed_fields", []) for a in apps}
our_fields = apps_with_fields.get(our_app_id, None)
verification = {
    "self_app_subscribed": our_fields is not None,
    "subscribed_fields": our_fields,
    "required_fields_present": all(f in (our_fields or []) for f in ["messages", "messaging_postbacks"]),
}
```

**[B-2] ADR-027: polling fallback（撮影用暫定措置）**

Meta App Review 撮影のために、webhook が届かない場合のフォールバックとして `GET /{page-id}/conversations` の定期ポーリング（1-5分間隔）を一時実装。撮影後に廃止予定。

**[B-3] Meta Developer Support 問い合わせ**（必要な場合）

以下のエビデンスを添付:
- nginx log の 3 イベント（最終 POST / ゼロ期間 / GET re-verify）
- subscribed_apps 状態（name のみ → curl で fields あり）
- Sales Anchor 側ネットワーク正常証明（UFW/iptables/fail2ban/nginx 設定）
- IG の OAuthException #3 の発生（Messenger Platform でのサポート可否確認）

問い合わせ内容:
> "Messenger Platform app で Instagram DM を受信するための正しい subscribed_apps 設定方法を確認したい。`/{page_id}/subscribed_apps` POST で `messages` を設定しても Instagram DM が届かない。`/{ig_user_id}/subscribed_apps` は OAuthException #3。"

---

## 付録: 技術仕様メモ

### Webhook を受信するための Meta 側要件（確認済み）

```
1. Meta App Dashboard: Webhook URL 設定 + Verify Token 一致
2. Meta App Dashboard: Webhook 購読フィールド (messages, messaging_postbacks) 有効
3. API: POST /{page_id}/subscribed_apps with subscribed_fields ← Sales Anchor が connect_callback で実行
4. Development Mode: テスト送信者が App の Test User として登録・承認済
```

### Sales Anchor の暗号化の流れ

```
1. OAuth connect 時: Meta から受け取った page_access_token を Fernet.encrypt(METADATA_FERNET_KEY) で暗号化 → DB 保存
2. Token refresh 時: DB から暗号化トークンを読み込み → Fernet.decrypt(METADATA_FERNET_KEY) → Meta API 呼び出し
3. METADATA_FERNET_KEY が変わると: 既存の暗号化トークンが復号不能になる
```

### 現在の本番 .env 状態（推定）

deploy.yml の PR #337（14:43 JST）以降:
```
METADATA_FERNET_KEY=<GitHub Secrets の現在値>  ← sed 方式で書き直し済みのはず
```

ただし tenant_meta_config のトークンは:
- OAuth が最後に成功した時刻の METADATA_FERNET_KEY で暗号化
- 手動 DB INSERT のため、そもそも正規の OAuth フロー経由でない可能性
- → 正規 OAuth 再接続が必要

---

**このレポートは Terminal Claude Code セッション（2026-05-13 未明）で収集したデータを元に作成。**  
**VPS SSH が停止中のため、VPS 上の現在状態（.env 値、コンテナログ等）は確認不可。**  
**上記 [A-1] VPS 復旧後に現状確認を行うこと。**

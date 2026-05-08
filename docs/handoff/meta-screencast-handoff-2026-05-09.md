# Meta App Review スクリーンキャスト 引き継ぎノート

**作成**: 2026-05-09  
**作成元**: Hitoshi-side Claude Code session（Hikky-dev の Mac で稼働中）  
**引き継ぎ先**: しんごさん側 Claude Code session  
**目的**: Meta App Review 録画作業に必要な context・既存資産・運用ルールを統合提示  
**原則**: しんごさんの Claude Code が **このファイル 1 つ** で Meta App Review screencast の現状を把握できること

---

## 1. 録画作業の現状（2026-05-09 時点）

| 項目 | 内容 |
|---|---|
| 作業ブランチ | `recording/english-ui`（しんごさん作業中、origin に push 済 / SHA `40d289cc9` 時点）|
| 方針 | Meta リジェクト事例調査により **UI 英語化が必要**と判明したため、英語化版で撮影 |
| スコープ | テキスト置換のみ、機能は不変 |
| ライフサイクル | 録画完了 → ブランチ削除 |
| 本番コード（develop/main）への影響 | **ゼロ** |
| PR / merge | **なし** |
| CLAUDE.md | しんごさんが運用ルール追記中 |

---

## 2. 既存資産（リポジトリ内、main ブランチに存在）

### 2-1. 撮影台本・チェックリスト

| ファイル | 行数 | 用途 |
|---|---|---|
| **`docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md`** | 499 | Sprint 7 完成版の撮影台本。8 シーン × 操作指示 / 英語ナレーション原稿 / 撮影注意点 / テストデータ要件 |
| `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` | 354 | 撮影直前に確認すべき項目チェックリスト |
| `docs/USE_CASE_DESCRIPTIONS_v1.1_DRAFT.md` | 517 | Meta 申請フォーム素材（v1.1 ドラフト）|
| `docs/data_deletion_callback_design.md` | 266 | B1-B6 Data Deletion 実装の設計ドキュメント |

### 2-2. 8 シーン構成（既存台本より）

| # | 時間 | テーマ | 申請 Permission |
|---|---|---|---|
| 1 | 0:00-0:30 | Intro: Sales Anchor dashboard overview | (前提) |
| 2 | 0:30-1:30 | Connect Facebook Page via OAuth | `pages_show_list`, `pages_manage_metadata` |
| 3 | 1:30-2:30 | Incoming Messenger message arrives in inbox | `pages_read_engagement` |
| 4 | 2:30-3:30 | Sales rep replies to Messenger | `pages_messaging` |
| 5 | 3:30-4:30 | Connect Instagram Business account | `instagram_basic` |
| 6 | 4:30-5:30 | Instagram DM received and replied | `instagram_manage_messages` |
| 7 | 5:30-6:30 | Reply outside 24-hour window using Human Agent Tag | Human Agent Tag |
| 8 | 6:30-7:30 | Data Deletion Callback demonstration | (Required by Meta) |

**合計 7 分 30 秒、6 Permission + Human Agent Tag + Data Deletion 全カバー**

> ⚠️ **シーン番号についての注意**: 上記は 8 行（Intro + 7 Permission/Feature）構成。既存台本 (`META_APP_REVIEW_SCREENCAST_SCRIPT.md`) のヘッダは「7 シーン × 平均 1 分」表記だが、本文の節は §2-§9 で 8 シーン構成。録画する側は **本文の 8 セクション** を基準に。
>
> ⚠️ **Scene 7 (Human Agent Tag) の運用**: Master Checklist では Human Agent Tag は **Business Verification 通過後の追加申請**となっている。初回 Meta App Review 提出時に録画含めるかは、しんごさんと申請戦略を擦り合わせて判断。BV 完了前の初回提出では Scene 7 を skip する選択肢もある。

### 2-3. バックエンド実装（参考、既に本番反映済）

| ファイル | 機能 |
|---|---|
| `backend/app/routers/meta.py` | Data Deletion Callback (B1-B4) |
| `backend/app/routers/meta_inbox.py` | Inbox API（Messenger/Instagram 統合受信箱）|
| `backend/app/routers/webhook.py` | Meta Webhook 受信 |
| `backend/app/services/meta_graph.py` | Meta Graph API クライアント |
| `backend/app/services/oauth_state.py` | OAuth state 管理（CSRF 対策）|
| `backend/app/tasks/data_deletion.py` | Celery 削除タスク（B5-B6）|
| `migrations/039_create_data_deletion_logs.sql` | data_deletion_logs テーブル |

### 2-4. LP（既に本番反映済）

| URL | ファイル | 用途 |
|---|---|---|
| https://salesanchor.jp/ | `lp/src/pages/index.astro` | LP ヒーロー、機能紹介 |
| https://salesanchor.jp/privacy | `lp/src/pages/privacy.astro` | Privacy Policy（バイリンガル）|
| https://salesanchor.jp/terms | `lp/src/pages/terms.astro` | Terms of Service |
| https://salesanchor.jp/data-deletion | `lp/src/pages/data-deletion.astro` | Data Deletion Instructions |
| https://salesanchor.jp/deletion-status?code=DEL-... | `lp/src/pages/deletion-status.astro` | 削除状況確認ページ |

### 2-5. E2E テスト（参考、Playwright で 8 シーン分用意済）

`frontend/tests-e2e/scene[1-8]-*.spec.ts`

注意: モック使用のため Meta 提出には不向き。**本番録画は本物の Sales Anchor + 本物の Test Facebook Page で実施**する想定。

---

## 3. Google Drive 上の資産

| ファイル | Drive File ID | 用途 |
|---|---|---|
| **Master Checklist v1.1** | `1ZsI_Q_U6z2P4L6lpxsmfc2bisdygMbOnrhyHWCgDpkA` | 全 6 セクション（A-F）の Master Checklist |
| `data_deletion_instructions` v1.0 | `1dCf77semO4ioZ_Sp3hhFGz-Zp9-qfMwkDp53jOPnuWI` | B1-B6 実装の元仕様（HMAC、unquoted JSON 等） |
| `privacy_policy_v12` v1.2 | `1mHy_pcXrlZ41MUMSy9e5MIzJgvY0oLwzwQ45na9wsWw` | LP /privacy 元仕様（既に LP 反映済）|
| `terms_of_service` v1.0 | `1NWp-kHGHUYj7s7VLTspjbb6B97ZR4_BGhJzSJMyHPd4` | LP /terms 元仕様（既に LP 反映済）|
| `use_case_descriptions` v1.0 | `14wJpu80wRxM8T5q7JLeHARfeRmXgKD54niij-NOTHFM` | E1-E5 申請フォーム素材 |

検索方法: `mcp__claude_ai_Google_Drive__search_files` で `title contains 'use_case'` 等

---

## 4. 提出進捗（2026-05-09 時点、しんごさん報告ベース）

### ✅ 完了済み

- **§A LP/公開ページ**: A1-A12 全完了
- **§B バックエンド**: B1-B6 完了
- **B7**: Data Deletion Callback の動作確認完了（400 Invalid signed_request を正常応答）
- **C2**: App Settings (Privacy/Terms/Data Deletion URL、Category) 入力済
- **C3**: Webhook (Messenger/Instagram) 設定済
- **C4**: Permissions 選択済（6 Permission: instagram_basic / instagram_manage_messages / pages_manage_metadata / pages_messaging / pages_read_engagement / pages_show_list）
- **C5**: Data Deletion Callback URL 登録済
- **ドメイン認証**: salesanchor.jp Verified
- **D1**: シナリオ設計（Use Case Descriptions §2 で 7 シーン構成確定）
- **E1-E5**: 素材完了（use_case_descriptions.docx v1.0 ベース）

### ⏳ 残タスク

- **D2-D6**: スクリーンキャスト録画（**しんごさん作業中、recording/english-ui ブランチ**）
- **E3**: Test Password・Test Instagram の確定
- **C6**: Business Verification 審査中（Meta 側 1-2 週間）
- **Human Agent Tag**: Business Verification 通過後に追加申請予定
- **E6**: 提出前最終チェック
- **E7**: 申請提出

---

## 5. 録画用ブランチの運用ルール（しんごさん設定）

```
ブランチ名: recording/english-ui
基底: develop (or main)
内容: 日本語 UI を英語に置き換えただけ、機能は本物
ライフサイクル: 撮影完了 → ブランチ削除
PR: 作成しない
merge: しない
本番反映: 一切しない
```

**Why**: Meta リジェクト事例で UI 英語化が必要と判明したため、録画専用環境を一時的に作成。本番運用への影響を完全分離する設計。

CLAUDE.md にも同内容がしんごさんにより追記される予定（または既に追記済の可能性あり）。

---

## 6. 関連自動化基盤

### 6-1. Claude Max Auto-Pipeline

- Workflow: `.github/workflows/claude-pipeline.yml`
- 起動方法:
  - ADR push → ADR-016 で自動起動
  - `gh workflow run "Claude Max Auto-Pipeline (Partner Subscription)" --ref develop -f adr_files=docs/adr/ADR-NNN.md`（手動）
- 実行環境: self-hosted runner `Hikky-dev-Mac`（Hitoshi の Mac）
- PAT: `secrets.PIPELINE_PAT`（Issue #300 で 90 日 rotation 管理、失効目安 2026-08-05）

### 6-2. フィードバックフォーム

- Form: `Sales Anchor フィードバック`（Drive File ID `1_qHnLX-annJM7Zo1GblY34VD3TOEitexGT88DAtzXX0`）
- 連携 Spreadsheet: `Sales Anchor フィードバック（回答）` (`1vO2ywIdhCez7pyabVn3U0aGkVqtyqqohn-haVV0hutw`)
- GAS: フォーム送信 → GitHub Issue 自動作成（labels: `bug/enhancement/question` + `from-form` + `priority:*`）+ Discord 通知
- Phase α workflow（`.github/workflows/feedback-issue-triage.yml`）: `from-form` ラベル付き Issue → `triage-needed` ラベル + メンション付きトリアージ要請コメント自動投稿
- Phase β/γ ロードマップ: PR #313 (PROPOSAL-002) で起案中

### 6-3. develop / main の関係

- 機能 PR は develop 向け、リリース PR develop → main で main 反映
- main は default branch
- GitHub Actions の `issues` event triggers は **main の workflow から読まれる**ため、新 workflow は main にも展開要

---

## 7. しんごさん Claude Code が私（Hitoshi-side Claude）に依頼できる作業候補

撮影周辺で、私（Hitoshi-side）が並行で着手できるタスクリスト。録画は触れないが、補助成果物は出せる。

| 候補 | 内容 | 工数目安 |
|---|---|---|
| **SRT 字幕ファイル**（英語、タイムコード付き）| 録画後に YouTube 等で字幕として焼き込み可 | 1h |
| **日本語ナレーション原稿** | 英語ナレーション避けたい場合の代替（日本語音声 + 英語字幕で reviewer 対応）| 1h |
| **撮影直前 checklist 補強** | 既存 `META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` を拡充 | 30m |
| **撮影後の品質検証スクリプト** | ffprobe で Meta 要件（1920×1080 / 60fps / H.264 / 字幕 / 尺）適合チェック | 30m |
| **OBS scene 設定 JSON** | OBS にインポートで 8 シーン構成を自動セット | 1h |
| **Master Checklist §9（提出前最終チェック）の検証** | API で各 URL を叩いて 200 OK 確認、画面ロード時間計測等 | 1h |
| **Test User credentials 管理（E3）** | Test Password・Test Instagram の placeholder を実値に置換するための整理 | 30m |

依頼方法: しんごさん Claude Code に「Hitoshi-side Claude に SRT 字幕作って欲しい」「品質検証スクリプト作って」等を伝えれば、私（Hitoshi-side）に作業依頼が転送される想定。

---

## 8. 録画前後の実務的な注意事項

### 録画前のテスト環境準備（PRE_RECORDING_CHECKLIST 参照）

- Sales Anchor: `review@salesanchor.jp` (Owner ロール) + 仮パスワード
- Test Facebook User: Meta Developer Portal の Test Mode で作成（Page admin 権限）
- Test Facebook Page: `HIGH LIFE JPN Test Page`
- Test Instagram Business Account: 上記 Page にリンク済
- Sender 側 Facebook / Instagram テストユーザー 1 名（Test User とは別、Page Fan として登録済）

### 撮影品質要件（Master Checklist v1.1 §0.4 準拠）

| 項目 | 要件 |
|---|---|
| 解像度 | 1920×1080（推奨）/ 1280×720（最低）|
| フレームレート | 60 fps（推奨）/ 30 fps（最低）|
| コーデック | H.264 (mp4) |
| 音声 | AAC 128kbps、英語ナレーション（**必須、無音は不可**）|
| 字幕 | 英語字幕焼き込み（推奨、SRT 別添も可）|
| 尺 | 30 秒以上、7 分以下 / シーンあたり、全体 7 分 30 秒前後 |
| ファイルサイズ | 50 MB 以下推奨（最大 1 GB）|
| ファイル名 | `salesanchor_meta_app_review_v1.mp4` |

### 推奨録画ツール

- **OBS Studio** (無料、業界標準): https://obsproject.com/
- 代替: ScreenFlow（macOS 有料、編集機能強力）/ QuickTime + iMovie（macOS 標準、後付け編集要）

### Meta レビュー期間と再申請

- 通常 2-7 日で結果
- リジェクトは普通（統計的に 1-2 回はあり得る）
- リジェクト時は `Master Checklist §6 (F1-F3)` で原因分析 → 修正 → 再申請

### 不可逆操作のガード

しんごさん側で進める作業の中で、以下は **必ず PO（しんごさん本人）確認**:
- Meta App の本番モード切替（Test Mode → Live）
- Permission の Standard/Advanced 切替申請
- Business Verification 書類提出
- 申請フォーム最終提出（E7）

---

## 9. 参考リンク・パス一覧

### 内部資産
- 撮影台本: `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md`
- 撮影 checklist: `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`
- Use Case (v1.1 ドラフト): `docs/USE_CASE_DESCRIPTIONS_v1.1_DRAFT.md`
- Data Deletion 設計: `docs/data_deletion_callback_design.md`
- このファイル: `docs/handoff/meta-screencast-handoff-2026-05-09.md`

### 本番 URL
- LP: https://salesanchor.jp/
- App: https://app.salesanchor.jp/
- API: https://api.salesanchor.jp/
- Privacy: https://salesanchor.jp/privacy
- Terms: https://salesanchor.jp/terms
- Data Deletion: https://salesanchor.jp/data-deletion

### Drive
- Master Checklist: https://docs.google.com/document/d/1ZsI_Q_U6z2P4L6lpxsmfc2bisdygMbOnrhyHWCgDpkA/edit
- フォーム編集: https://docs.google.com/forms/d/1_qHnLX-annJM7Zo1GblY34VD3TOEitexGT88DAtzXX0/edit
- フォーム回答 Spreadsheet: https://docs.google.com/spreadsheets/d/1vO2ywIdhCez7pyabVn3U0aGkVqtyqqohn-haVV0hutw/edit

### GitHub
- Repo: https://github.com/shingo-ops/salesanchor
- 録画作業 branch: `recording/english-ui`（しんごさん作業中、push 予定）
- Phase α workflow: `.github/workflows/feedback-issue-triage.yml`（main にデプロイ済）

---

## 10. しんごさん Claude Code 起動時の最初のアクション（推奨手順）

1. **このファイルを読む**: `docs/handoff/meta-screencast-handoff-2026-05-09.md`
2. **撮影台本を開く**: `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md`
3. **作業ブランチ確認**: `git checkout recording/english-ui`（しんごさん作成済 or 作成予定）
4. **Master Checklist 確認**: 上記 Drive URL から最新進捗を確認
5. **しんごさんから具体的指示を待つ**:
   - 「英語化進めて」 → frontend テキスト置換
   - 「録画準備して」 → PRE_RECORDING_CHECKLIST 通り環境準備
   - 「Hitoshi-side に SRT 字幕お願い」 → Hikky-dev の Claude にタスク依頼

---

## 11. しんごさん Claude Code が知っておくべき協業ルール

### Claude Code 二人体制
- **Hitoshi-side**（私、Hikky-dev の Mac）: 機能実装、自動化基盤、文書整備、Meta 周辺ドキュメント等
- **しんごさん側**（このファイル受け取る側）: 録画環境構築、UI 英語化、Meta Dashboard 操作、申請提出

### 重複作業の回避
- 録画作業中は Hitoshi-side は **本番コードに大きな変更を入れない**（recording/english-ui の rebase が困難になるため）
- 緊急 hotfix が必要な場合は事前にしんごさんに connect

### コミュニケーション
- 重要な判断はしんごさん経由で両 Claude セッションへ伝言
- このファイル自身も「両 Claude セッション間の共通基盤」として、追記が必要なら develop に PR を投げる

---

**更新履歴**

| 日付 | 内容 |
|---|---|
| 2026-05-09 | 初版作成（Hitoshi-side Claude Code session by Hikky-dev）|

---

**End of handoff document**

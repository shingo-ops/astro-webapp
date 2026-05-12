# ADR-024: Meta 連携の構造的不整合の修正

- **Status**: Proposed
- **Date**: 2026-05-12
- **Deciders**: Shingo Tanizawa (PO)
- **関連 ADR**: ADR-009 (Discord Gateway / 認証基盤), ADR-022 (UI Meta Business Suite 風), ADR-023 (スタッフライフサイクル 3 層同期)

---

## Context

Meta App Review 申請のための撮影準備中、Sender (`samuraisoul_katana`) から Test Page (`@treasureislandjapan`) への Instagram DM が **Meta Business Suite の受信箱には届くが、Sales Anchor Inbox には届かない**事象が発覚した。

Test User の設定（ビジネスマネージャ経由の App Role 付与、Instagramテスター登録・承認）はすべて完了しており、Meta 側の Permission ステータスも全て「テスト準備完了」になっている。にもかかわらず webhook が来ない。

技術調査の結果、Sales Anchor 側に複数の構造的不整合が判明した：

1. `tenant_meta_config` レコードは「接続済み」状態として DB に存在するが、`audit_logs.meta_page_connected` が 0 件
2. `subscribed_fields = NULL`（どのフィールドも subscribe されていない）
3. `meta_token_refresh_failed` が 2026-04-30 から毎日発生（`EncryptionConfigurationError` / `decrypt_failed`）

つまり、Test Page の接続レコードは **OAuth API フローを経由せず DB に直接 INSERT された**ものであり、Meta 側では Sales Anchor アプリが Page の subscribed_apps として登録されていない状態である。同時に暗号化キー不一致により保存済み Page Access Token が復号不能となっており、API から `subscribed_apps` を呼び直すことすらできない。

このまま放置した場合、約 60 日後（2026 年 6 月下旬）にトークン期限切れにより Meta 連携が全停止する。

## What

以下の状態を実現する：

1. **接続状態の整合性**: `tenant_meta_config` の「接続済み」レコードが、Meta 側でも対応する `subscribed_apps` 登録を持つ
2. **トークン復号の正常化**: 保存済み Page Access Token / Instagram User Access Token が常に復号可能であり、自動リフレッシュが成功する
3. **Instagram webhook 受信**: Instagram Business Account に紐づく DM/Comment/Reaction イベントが Sales Anchor の webhook エンドポイントに到達する
4. **不整合検出**: 既存および将来の接続レコードについて、DB 状態と Meta 側状態の不整合を検出するメカニズム
5. **不整合の自動回復または明示的なエラー化**: 検出された不整合は、可能な範囲で自動修復、または UI 上で明示的な再接続を促す

## Why

- **Meta App Review 申請の前提条件**: Instagram DM webhook が正常受信できないと、App Review 用のスクリーンキャスト撮影が実施できない
- **本番運用上の致命的問題**: トークンリフレッシュ失敗が継続中。60 日後に Meta 連携全停止し、Facebook / Instagram の DM 受信機能（Sales Anchor のコア機能）が動かなくなる
- **テナント単位の影響**: 現在は tenant_004 のみだが、本番テナント追加時に同じ問題が再発する可能性が高い
- **データの信頼性**: 「DB 上は接続済み・Meta 上は未接続」という不整合状態を許容する設計は、運用上の盲点となる。検出・修復のメカニズムが構造として必要
- **Phase 2 への先送り不可**: トークン期限切れまでに時間的余裕がなく、Phase 1（App Review 通過）の遂行自体を阻害している

## Scope 外

- ADR-023（スタッフライフサイクル 3 層同期）の実装範囲
- Meta 以外の SNS 連携（LINE、WhatsApp、Discord 等）への影響
- Meta Graph API のバージョンアップ対応（v19 → 新版）
- UI の大幅な変更（既存の Channels 画面の機能維持で良い）
- Page Access Token から Instagram User Access Token への移行（Meta API リニューアル対応）
- 監査ログのスキーマ変更
- 暗号化方式自体の変更（Fernet 等から別アルゴリズムへ）

## 事業上の制約

- **self-hosted runner offline**: パートナー Claude Code のパイプラインが動作不可。runner 復旧後に実装着手
- **Suttan 対応不可**: runner 管理者が対応できないため、復旧時期未定
- **ENCRYPTION_KEY の取り扱い**: 本番運用への影響大。鍵を変更する場合は既存レコードの再暗号化または再接続の方針を明確にする必要
- **撮影日程の延期**: 本 ADR の実装完了まで Meta App Review 撮影は実施不可
- **緊急時 VPS 直接作業の禁止**: 通常運用ルールに従い、deploy.yml 経由でのみ本番反映
- **既存接続レコードの救済**: 現状 tenant_004 の 1 レコードのみ不整合。Test Page との接続なので、最悪削除して再接続でも事業影響なし

## 受け入れ条件（実装完了の判定基準）

1. Sales Anchor Channels 画面から Test Page を切断 → 再接続した結果、`tenant_meta_config.subscribed_fields` に `messages`, `messaging_postbacks`, および Instagram メッセージ用フィールドが保存される
2. Graph API `GET /{page-id}/subscribed_apps` で Sales Anchor アプリが返ってくる
3. `meta_token_refresh_failed` の audit_log が、新しい接続レコードについて発生しない
4. `samuraisoul_katana` → `@treasureislandjapan` の Instagram DM が、Sales Anchor Inbox に新規リードとして表示される
5. 暗号化キーまたはトークンに不整合が発生した場合、Sentry 等で検知可能、または定期ジョブで早期検出される
6. Phase 1 撮影台本の Scene 5（Instagram OAuth 接続）・Scene 6（Instagram DM 受信）が問題なく実演できる

## 関連する運用上の振り返り

このバグ群は「データを手動で DB INSERT した運用」が原因の一部である。Phase 2 で以下を検討する：

- データ手動投入の禁止（運用ガイドラインへの追記）
- 接続検証スクリプトの定期実行
- DB スキーマでの制約強化（例：`subscribed_fields IS NOT NULL` を required にする）

これらは本 ADR の Scope 外だが、関連事項としてバックログに記録する。

## 概要
<!-- 変更内容を簡潔に -->

## Design Review Evidence
<!-- design-review-gate は PR 本文ではなく、信頼済みレビュアーのコメント/Review を検証します。 -->

レビュー完了後、信頼済みレビュアーが PR コメントまたは GitHub Review に以下を投稿してください。

```text
Design Review: APPROVED
Reviewer:
Commit:
Scope:
Evidence:
```

## チェックリスト

### 共通
- [ ] テストを追加・更新した
- [ ] `ja.json` / `en.json` のキー数が一致している（UI テキスト変更時）

### DB スキーマ変更時（models.py に Column を追加・変更した場合）
- [ ] `migrations/` に SQL ファイルを作成した（`ADD COLUMN IF NOT EXISTS` で冪等）
- [ ] `scripts/` に Python 実行スクリプトを作成した
- [ ] `.github/workflows/deploy.yml` にマイグレーションステップを追記した ← **必須（CI でブロックされます）**

### デザイントークン変更時（tokens.css / index.css を変更した場合）
- [ ] 新しいトークンを追加した場合、その**理由**を概要欄に記載した
- [ ] 色トークンは `:root`（ライト）と `:root.force-dark`（ダーク）の両方に追加した
- [ ] `npm run check:dark-parity` でパリティ確認済み
- [ ] 既存トークンで代替できないか確認した（トークン重複防止）

### セキュリティ
- [ ] ハードコードされたシークレットがない
- [ ] ユーザー入力を適切にバリデーションしている

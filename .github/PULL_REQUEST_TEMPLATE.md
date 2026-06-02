## なぜ
<!-- この変更が必要な理由・背景 -->

## 何を変えたか
<!-- 変更したファイル・機能を箇条書きで -->

## 変更規模
<!-- 小（1〜2ファイル）/ 中（3〜5ファイル）/ 大（6ファイル以上） -->

## 概要
<!-- 上記3項目の補足があれば -->

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

### backend/app/routers/ 変更時（write エンドポイントを追加・変更した場合）
- [ ] `db.commit()` 直後に `await reset_tenant_context(db, tenant_id)` を呼んでいる（ADR-072）
- [ ] commit が複数ある場合、各 commit の直後に呼んでいる（詳細: `backend/tenant/CLAUDE.md`）

### セキュリティ
- [ ] ハードコードされたシークレットがない
- [ ] ユーザー入力を適切にバリデーションしている

### CLAUDE.md 変更時
- [ ] 行数上限を超えていないか（`npm run check:claude-size` で確認）
- [ ] 新規ファイルを作成した場合、`check-claude-size.js` の LIMITS 配列に登録した

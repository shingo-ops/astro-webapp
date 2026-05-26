# Meta 暗号化キーローテーション手順書

- **対象キー**: `METADATA_FERNET_KEY`（Fernet / urlsafe base64 32 bytes）
- **関連 ADR**: ADR-024（構造的不整合の修正）, ADR-025（運用整備強化）
- **影響範囲**: `tenant_meta_config.page_access_token_encrypted` 等、Fernet で暗号化された全カラム
- **最終更新**: 2026-05-12

---

## 1. なぜローテーションが「破壊的」なのか

たとえ話: **金庫の鍵を勝手に作り替えると、古い鍵で施錠した書類は二度と開かなくなる**。

- `METADATA_FERNET_KEY` は Fernet 対称鍵。暗号化時の鍵と復号時の鍵が一致しないと `InvalidToken` で復号失敗。
- DB に保存済みの `page_access_token_encrypted` は、暗号化された **その時点の鍵** でしか復号できない。
- そのため「GitHub Secrets を新しい鍵に差し替えるだけ」で旧データを残すと、毎日 03:00 JST の `refresh_meta_tokens` が **全テナント** で失敗し、Meta 連携が静かに停止する（2026-05-01 の事故と同じパターン）。

**結論**: 暗号化キーローテーションは「鍵更新」と「データ再暗号化または再接続」の **2 ステップが 1 セット**。片方だけ行うのは禁止。

---

## 2. ローテーションが必要になるケース

| ケース | 想定頻度 | 例 |
|---|---|---|
| 鍵が漏洩した | 緊急 | GitHub Actions ログに誤って印字、開発者端末から流出 |
| 計画的ローテーション | 1 年に 1 回程度 | コンプライアンス要件 |
| 鍵紛失 / `EncryptionConfigurationError` 多発 | 緊急 | GitHub Secrets およびバックアップ双方を喪失（このときは「再接続」一択） |

---

## 3. 事前準備（必須・順番厳守）

### 3.1 影響テナントの把握

```bash
# develop / Web Claude 経由で実行する場合の例
# 接続済テナント数と最終リフレッシュ時刻を確認
docker exec astro-webapp-postgres-1 \
  psql -U jarvis -d jarvis_db -c "
    SELECT t.tenant_code,
           tmc.platform,
           tmc.is_active,
           tmc.last_token_refresh_at,
           tmc.subscribed_fields IS NOT NULL AS has_subscription
    FROM public.tenants t
    JOIN public.tenant_meta_config tmc ON tmc.tenant_id = t.id
    WHERE tmc.is_active = true
    ORDER BY t.tenant_code;
  "
```

### 3.2 audit_log の現状確認

```bash
# 直近 24 時間の Meta 関連 audit を確認
docker exec astro-webapp-postgres-1 \
  psql -U jarvis -d jarvis_db -c "
    SELECT action, count(*), max(created_at)
    FROM public.audit_logs
    WHERE action LIKE 'meta_%'
      AND created_at > now() - interval '24 hours'
    GROUP BY action;
  "
```

### 3.3 PO 承認の取得（必須）

- ローテーションは不可逆操作（旧鍵で暗号化されたデータが復号不能になる）
- 必ずしんごさん（PO）に **書面（GitHub Issue / PR 本文）で確認** を取る
- 緊急性が低い場合は撮影・本番イベントを避けてスケジュール

### 3.4 旧鍵 / 新鍵のバックアップ

- 旧鍵: 復元用に別の安全なバックアップ場所へコピー（`METADATA_FERNET_KEY_PREV_<日付>` 形式で記録）
- 新鍵: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` で生成
- 新鍵を安全なバックアップに保存してから GitHub Secrets に登録（順序逆転禁止）

---

## 4. ローテーション手順

### Case A: 全テナントを「切断 → 再接続」させる方式（推奨）

**前提**: 接続テナント数が少ない（〜10 件程度）、または接続を維持する強い必要が無い場合。最も安全。

#### Step 1: GitHub Secrets を新鍵に差し替える

```bash
gh secret set METADATA_FERNET_KEY --body "<新しい Fernet 鍵>"
```

#### Step 2: 既存の暗号化レコードを無効化（is_active=false）

```sql
-- 接続済テナントを一旦すべて切断扱いにする
UPDATE public.tenant_meta_config
SET is_active = false,
    disconnected_at = now(),
    disconnect_reason = 'encryption_key_rotation'
WHERE is_active = true;
```

> このタイミングで `meta_page_disconnected` 系の audit_log が手動 INSERT で残らないよう、本処理は **必ず PO 立ち会いのもと** で実行する。

#### Step 3: deploy.yml 経由でデプロイ（=新鍵を VPS .env に反映）

```bash
# ADR-025 の deploy.yml 修正により、Secret 更新は次の main マージで .env に反映される。
# 確認のため develop → main の通常 PR フローでデプロイを発火させる。
```

デプロイ後、VPS で確認:

```bash
ssh ubuntu@<VPS> "cd /home/ubuntu/salesanchor && grep '^METADATA_FERNET_KEY=' .env"
# → 新鍵の先頭・末尾文字が GitHub Secrets の値と一致することを目視確認
```

#### Step 4: 各テナントが Sales Anchor UI から再接続

- Channels 画面 → Meta 連携 → OAuth フロー → 新鍵で暗号化保存
- 再接続完了後、`tenant_meta_config.is_active = true` かつ `subscribed_fields IS NOT NULL` を確認

#### Step 5: 検証

```bash
# 復号失敗 audit が新規発生していないことを確認（翌日 04:30 JST の verify cron 後）
docker exec astro-webapp-postgres-1 \
  psql -U jarvis -d jarvis_db -c "
    SELECT count(*)
    FROM public.audit_logs
    WHERE action = 'meta_subscription_decrypt_failed'
      AND created_at > now() - interval '6 hours';
  "
# 期待値: 0
```

---

### Case B: 旧鍵で復号 → 新鍵で再暗号化する方式（オンライン移行）

**前提**: 接続テナント数が多い、または UI 経由の再接続が事業上困難な場合。**未実装**（Phase 2 で検討）。

> 現時点では Case A のみサポート。Case B が必要になった場合は、ADR を起案して以下を含む再暗号化スクリプトを設計する:
>
> - 旧鍵での復号 → 新鍵での再暗号化を tenant_meta_config 全行に適用
> - トランザクション内で実行し、途中失敗時はロールバック
> - audit_log に `meta_encryption_key_rotated` を記録
> - `METADATA_FERNET_KEY_PREV` 環境変数による旧鍵参照を実装

---

## 5. ロールバック手順

新鍵に切り替えた直後にトラブルが発生した場合:

1. GitHub Secrets を **旧鍵に戻す**（バックアップの `METADATA_FERNET_KEY_PREV_<日付>` から復元）
2. 直近のデプロイを `gh run rerun` または手動 SSH で再実行し、.env を旧鍵に戻す
3. Case A の Step 2 で `is_active=false` にしたレコードを `is_active=true` に戻す（旧鍵で復号可能なので接続は復活する）
4. audit_log に手動で `meta_encryption_key_rotation_rolled_back` を記録（actor_id = PO）

---

## 6. 検証コマンド一覧

```bash
# 6.1 現行 .env のキー先頭/末尾だけ確認（フルダンプ禁止）
ssh ubuntu@<VPS> "cd /home/ubuntu/salesanchor && awk -F= '/^METADATA_FERNET_KEY=/ {print substr(\$2,1,4) \"...\" substr(\$2,length(\$2)-3)}' .env"

# 6.2 verify_meta_subscriptions Celery タスクを手動実行
docker exec -e TENANT_CODE=highlife-jpn -w /app astro-webapp-backend-1 \
  python -c "from app.tasks.verify_meta_subscriptions import verify_meta_subscriptions; verify_meta_subscriptions()"

# 6.3 暗号化サービスの自己診断
docker exec -w /app astro-webapp-backend-1 \
  python -c "from app.services.encryption import encrypt, decrypt; \
    c = encrypt('healthcheck'); print('encrypt ok'); \
    assert decrypt(c) == 'healthcheck'; print('decrypt ok')"
```

---

## 7. 不可逆操作チェックリスト（実行前に PO に提示）

- [ ] 影響テナント数を把握し、PO に書面で報告した
- [ ] 旧鍵を安全なバックアップ場所に `METADATA_FERNET_KEY_PREV_<日付>` として保存した
- [ ] 新鍵を安全なバックアップ場所に保存し、GitHub Secrets を更新した
- [ ] ローテーション中の Meta 連携停止許容時間を PO と合意した
- [ ] Meta App Review 撮影・本番デモ・新規顧客オンボーディングが当該期間と重ならない
- [ ] ロールバック手順を PO と共有済み
- [ ] `meta_subscription_decrypt_failed` の閾値アラート（手動監視で可）を設定した

---

## 8. 関連ファイル

| ファイル | 役割 |
|---|---|
| `backend/app/services/encryption.py` | Fernet ラッパ（暗号化・復号 API） |
| `backend/app/tasks/refresh_meta_tokens.py` | 毎日 03:00 JST のトークン自動リフレッシュ |
| `backend/app/tasks/verify_meta_subscriptions.py` | 毎日 04:30 JST の整合性検証（ADR-024） |
| `.github/workflows/deploy.yml` | Secret → VPS .env の同期（ADR-025） |
| `docs/adr/ADR-024_meta_integration_structural_fix.md` | 構造的不整合修正の経緯 |
| `docs/adr/ADR-025_meta_integration_operational_hardening.md` | 本ドキュメント起案 ADR |

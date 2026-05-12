# Meta 暗号化キーローテーション手順書

**対象キー**: `METADATA_FERNET_KEY`（`tenant_meta_config` の Page Access Token / Instagram User Access Token の暗号化に使用）

**最終更新**: 2026-05-12 | ADR-025 に基づき作成

---

## 概要

`METADATA_FERNET_KEY` は Fernet 対称暗号を使用する暗号化鍵。この鍵でDBに保存された Page Access Token / Instagram User Access Token を暗号化・復号している。

**鍵を変更すると既存の暗号化済みトークンが全て復号不能になる**（EncryptionConfigurationError / decrypt_failed）。必ずこの手順に従って慎重に実施すること。

---

## 影響範囲の確認

キーローテーション前に以下を確認する。

### 1. 接続済みテナント数を確認

```bash
ssh ubuntu@49.212.137.46
cd /home/ubuntu/salesanchor
sudo docker compose exec postgres psql -U jarvis -d jarvis_db -c \
  "SELECT t.name, c.page_id, c.instagram_user_id, c.subscribed_fields
   FROM public.tenants t
   JOIN public.tenant_meta_config c ON t.id = c.tenant_id
   WHERE c.page_access_token IS NOT NULL
   ORDER BY t.name;"
```

**接続済みテナントが存在する場合**: 方針 A（段階的移行）を選択。
**接続済みテナントが存在しない場合**: 方針 B（単純上書き）を選択。

---

## 方針 A: 接続済みテナントが存在する場合（標準手順）

### ステップ 1: 既存トークンのエクスポート（旧キーで復号）

```bash
# コンテナ内で実行
sudo docker compose exec backend python3 - <<'EOF'
import asyncio
from app.database import AsyncSessionLocal
from app.services.encryption import decrypt
from sqlalchemy import text

async def export_tokens():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT id, tenant_id, page_id, page_access_token, instagram_user_access_token "
            "FROM public.tenant_meta_config WHERE page_access_token IS NOT NULL"
        ))
        rows = result.fetchall()
        for row in rows:
            try:
                pt = decrypt(row.page_access_token)
                ig = decrypt(row.instagram_user_access_token) if row.instagram_user_access_token else None
                print(f"id={row.id} tenant={row.tenant_id} page={row.page_id} OK page_token_len={len(pt)} ig_token={'OK' if ig else 'None'}")
            except Exception as e:
                print(f"id={row.id} tenant={row.tenant_id} page={row.page_id} FAILED: {e}")

asyncio.run(export_tokens())
EOF
```

復号に失敗する行があれば、その行は既に旧キーで復号不能（障害状態）なので方針 C を参照。

### ステップ 2: 旧キーで復号 → 新キーで再暗号化

```bash
# 事前準備: OLD_KEY / NEW_KEY を環境変数で渡す
sudo docker compose exec -e OLD_FERNET_KEY="<旧キー>" -e NEW_FERNET_KEY="<新キー>" backend python3 - <<'EOF'
import asyncio, os
from cryptography.fernet import Fernet
from app.database import AsyncSessionLocal
from sqlalchemy import text

OLD_KEY = os.environ["OLD_FERNET_KEY"].encode()
NEW_KEY = os.environ["NEW_FERNET_KEY"].encode()
old_f = Fernet(OLD_KEY)
new_f = Fernet(NEW_KEY)

async def reencrypt():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT id, page_access_token, instagram_user_access_token "
            "FROM public.tenant_meta_config WHERE page_access_token IS NOT NULL"
        ))
        rows = result.fetchall()
        for row in rows:
            try:
                new_page_token = new_f.encrypt(old_f.decrypt(row.page_access_token.encode())).decode()
                new_ig_token = None
                if row.instagram_user_access_token:
                    new_ig_token = new_f.encrypt(old_f.decrypt(row.instagram_user_access_token.encode())).decode()
                await db.execute(text(
                    "UPDATE public.tenant_meta_config SET page_access_token=:pt, instagram_user_access_token=:igt WHERE id=:id"
                ), {"pt": new_page_token, "igt": new_ig_token, "id": row.id})
                print(f"id={row.id}: 再暗号化成功")
            except Exception as e:
                print(f"id={row.id}: FAILED - {e}")
        await db.commit()
        print("完了")

asyncio.run(reencrypt())
EOF
```

### ステップ 3: GitHub Secrets の更新

1. GitHub リポジトリ → Settings → Secrets and variables → Actions
2. `METADATA_FERNET_KEY` を新しい値に更新

### ステップ 4: デプロイ

```bash
# main へのデプロイで .env が自動更新される（ADR-025 修正済みの deploy.yml）
git push origin main
```

deploy.yml の Step 2 が `METADATA_FERNET_KEY` を GitHub Secrets の新値で上書きする。

### ステップ 5: 動作確認

```bash
# トークンリフレッシュが成功することを確認
ssh ubuntu@49.212.137.46
cd /home/ubuntu/salesanchor
sudo docker compose exec postgres psql -U jarvis -d jarvis_db -c \
  "SELECT action, new_data, created_at FROM tenant_004.audit_logs
   WHERE action = 'meta_token_refresh_failed'
   ORDER BY created_at DESC LIMIT 5;"
```

翌朝（token refresh cron 実行後）に `meta_token_refresh_failed` が出ていないことを確認。

---

## 方針 B: 接続済みテナントが存在しない場合（単純上書き）

1. GitHub Secrets の `METADATA_FERNET_KEY` を新しい値に更新
2. main へのデプロイ実行（deploy.yml が .env を自動更新）
3. 接続済みテナントがないため再接続不要

---

## 方針 C: 既存トークンが既に復号不能の場合（現在の障害状態）

ADR-025 作成時点（2026-05-12）の状態：METADATA_FERNET_KEY の不一致により既存トークンが復号不能。

**テストテナント（tenant_004）のみの場合の緊急対応**:

```bash
# 方針: 既存接続レコードを削除 → 再接続フローを実行
ssh ubuntu@49.212.137.46
cd /home/ubuntu/salesanchor
sudo docker compose exec postgres psql -U jarvis -d jarvis_db -c \
  "DELETE FROM public.tenant_meta_config WHERE tenant_id = (
     SELECT id FROM public.tenants WHERE code = 'highlife-jpn'
   );"
```

その後:
1. GitHub Secrets の `METADATA_FERNET_KEY` を現在の値（正しい値）に確認・更新
2. main へのデプロイ実行
3. Sales Anchor UI の Channels 画面から Facebook Page を再接続

---

## 新しい Fernet キーの生成方法

```python
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(key.decode())
```

または:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 二重保管の義務

`METADATA_FERNET_KEY` は以下の 2 か所に必ず保管すること:

| 保管場所 | 目的 |
|----------|------|
| GitHub Secrets (`METADATA_FERNET_KEY`) | デプロイ自動注入 |
| Bitwarden（PO 管理） | GitHub Secrets が失われた場合の復元 |

**どちらか一方のみでは鍵紛失リスクがある。** DB 内のトークンが永久に復号不能になる。

---

## 関連 ADR

- ADR-024: Meta 連携の構造的不整合の修正（token refresh 失敗の直接原因）
- ADR-025: Meta 連携の運用整備強化（本手順書の作成根拠）

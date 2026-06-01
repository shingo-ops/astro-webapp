# backend/scripts/CLAUDE.md

`backend/scripts/` 配下の作業時のみ適用。

---

## setup_review_tenant.py — Meta App Review テナントパスワード管理

実行するたびに新パスワードが生成され Firebase + DB 両方を更新する。
結果はコンテナ内 `/tmp/review_tenant_setup_*.txt` にしか書かれないため、
**実行直後に必ずホスト側へ保存**:

```bash
# VPS 上で実行（コンテナ再起動前に必須）
docker compose exec -T backend cat /tmp/review_tenant_setup_*.txt \
  > /home/ubuntu/salesanchor/review-tenant-password.txt
chmod 600 /home/ubuntu/salesanchor/review-tenant-password.txt
```

デプロイ（`docker compose up --build`）後にスクリプトがコンテナに存在しない場合:

```bash
# ローカルからコピー → コンテナへ転送 → 実行
scp -i ~/.ssh/id_ed25519 scripts/setup_review_tenant.py ubuntu@49.212.137.46:/tmp/
docker cp /tmp/setup_review_tenant.py astro-webapp-backend-1:/app/scripts/
docker compose exec -T -e ALLOW_REVIEW_TENANT_SETUP=1 backend python scripts/setup_review_tenant.py
```

再実行するとパスワードが変わるため、必ず取り出してから次の作業へ進むこと。
詳細: `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` C-1 セクション

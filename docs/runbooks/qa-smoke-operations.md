# QA Smoke Suite 運用 Runbook (ADR-038)

このドキュメントは **ADR-038** で導入した QA Smoke Suite (`tests/qa-smoke/` +
`scripts/qa/` + `.github/workflows/qa-smoke.yml`) の運用手順をまとめたもの。

> たとえ話: 飲食店で言うところの「毎朝の開店前点検」。
> ACS で指定された機能だけ確認するスプリント検証 (Evaluator) では拾えない
> 「店全体の照明・空調・看板」が動くかをチェックする。

---

## 1. 全体像

```
┌──────────────────────┐    weekly cron     ┌────────────────────────┐
│ .github/workflows    │ ─────────────────▶ │ self-hosted runner     │
│   /qa-smoke.yml      │   pull_request     │ (salesanchor-vps)      │
└──────────────────────┘   workflow_dispatch└────────────────────────┘
                                                       │
                          ┌────────────────────────────┼────────────────┐
                          ▼                            ▼                ▼
              scripts/qa/reset-tenant.sh   tests/qa-smoke/scene-*  cleanup-smoke-data.sh
                          │                            │                │
                          ▼                            ▼                ▼
              psql → seed-tenant.sql    Playwright → real            qa-/QA-接頭辞
              (TRUNCATE → seed → assert) https://app.salesanchor.jp   行のみ削除
```

- **対象テナント**: tenant_006 (tenant_code = `tenant-review`) 専用
- **対象 backend**: 実 VPS の本番 API (`https://api.salesanchor.jp`) + frontend
  (`https://app.salesanchor.jp`)
- **runner**: self-hosted (VPS 同等ネットワーク経路)。本番 DB に psql 接続する
  ため github-hosted runner では塞がれる前提

---

## 2. 仕組み (3 つのファイル + 8 シナリオ)

### 2-1. seed (`scripts/qa/seed-tenant.sql`)

tenant_006 を「実データ入りの known state」に冪等 reset する SQL。

| Entity | 件数 | 内訳 |
|--------|------|------|
| users | 3 | admin / staff / viewer 各 1、locale ja |
| companies | 5 | うち 2 件は Meta Channel 接続済 (QA-CO-001..005) |
| contacts | 5 | 各 company に 1 名 (QA-CT-001..005) |
| leads | 5 | status: 新規 / 対応中 / 評価済 / 失注 / 受注 (QA-LD-001..005) |
| orders | 3 | status: pending / shipped / canceled (QA-OR-001..003) |
| products | 5 | カテゴリ違い (QA-PR-001..005) |
| meta_messages | 10 | messenger 6 + instagram 4、100 字超 message_id 含む |
| tenant_meta_config | 2 | QA Test Page Alpha / Beta (dummy encrypted token) |
| public.meta_page_routing | 2 | tenant_006 ↔ page_id ↔ ig_account_id |
| tenants.settings | 1 | tenant_006 default JSONB |

接頭辞ルール: テナント schema 内のシード行は **`qa-`** (英小文字) または
**`QA-`** (英大文字)。cleanup スクリプトはこの接頭辞だけを対象に削除する。

### 2-2. reset (`scripts/qa/reset-tenant.sh`)

- `flock /tmp/qa-tenant-006.lock` で **撮影との時間衝突を排他** (撮影 / 別 reset
  と最大 10 分待機)
- tenant_code='tenant-review' を assert → 誤実行ガード
- `seed-tenant.sql` に Firebase UID / password hash を `psql -v` で注入
- 開始 / 完了 / 失敗を Discord webhook で通知 (`QA_DISCORD_WEBHOOK_URL` 未設定なら skip)

### 2-3. cleanup (`scripts/qa/cleanup-smoke-data.sh`)

- 接頭辞 (`qa-` / `QA-`) **のみ** 削除
- `DRY_RUN=1` で削除対象件数だけ表示 (CI safe)
- `audit_logs` は監査証跡として残す (cleanup 対象外)

### 2-4. 8 シナリオ (`tests/qa-smoke/scene-{01..08}.spec.ts`)

| # | Scenario | 重要 assert |
|---|----------|------------|
| 01 | Auth & Roles | admin/staff/viewer の login、viewer は admin menu なし |
| 02 | Dashboard | KPI 3 種描画、console.error 0 件 |
| 03 | Customers | seed company 5 件表示、検索、新規作成→DB +1 |
| 04 | Inbox & Channels | ADR-024/026/041 regression guard (DB 検証) |
| 05 | Leads & Orders | 売上 56,400 一致、status 5 種 |
| 06 | Staff & Permissions | seed role 表通り、viewer は変更不可 |
| 07 | i18n & Settings | ja↔en 切替、ハードコード grep ベースライン |
| 08 | Data Lifecycle | 顧客→channel→mock webhook→案件→受注→KPI 通し |

---

## 3. 日常運用

### 3-1. 手動で走らせる (Evaluator / Generator が使う)

```bash
# GitHub Actions UI から:
#   Actions → "QA Smoke Suite (ADR-038)" → Run workflow

# CLI から:
gh workflow run qa-smoke.yml
```

### 3-2. 週次 cron (自動)

毎週月曜 03:00 JST に走る (`schedule: cron: '0 18 * * 0'`)。
Discord 通知で結果が流れるので、月曜朝の最初のタスクは Discord 確認。

### 3-3. PR で走らせる (スコープ限定)

`tests/qa-smoke/**` または `scripts/qa/**` を変更する PR でのみ自動起動する。
**全 PR で走らせない理由**: 本番 backend に毎 PR で負荷をかけたくないため。

---

## 4. トラブルシュート

### 4-1. seed assert で停止 (`seed assert FAIL: ...`)

- 原因候補:
  - seed SQL を一部しか流せない状態 (DB 接続切れ、permission)
  - 既存 schema が破損 (migration 未適用)
- 対処:
  1. `psql "$DATABASE_URL" -At -c "SELECT version()"` で DB 疎通確認
  2. `bash scripts/qa/cleanup-smoke-data.sh DRY_RUN=1` で件数確認
  3. `bash scripts/qa/cleanup-smoke-data.sh` で手動 cleanup → reset-tenant.sh 再実行
  4. それでも駄目なら `setup_review_tenant.py` から再構築 (tenant_006 自体を作り直す)

### 4-2. flock timeout (`flock timeout — 撮影中 or 他 reset 実行中`)

- 原因: `/tmp/qa-tenant-006.lock` を別プロセスが保持
- 対処:
  1. `ps auxf | grep reset-tenant` で実行中プロセス確認
  2. 撮影中なら待機 → 撮影完了後に再実行
  3. ロックを保持するプロセスが既に死んでいたら `rm /tmp/qa-tenant-006.lock` で
     強制解放 (ただし他に reset が走っていないことを必ず目視確認)

### 4-3. scene-04 が FAIL (regression guard)

scene-04 は本 ADR-038 が「機械的に止めたい 3 件のバグ」の砦。失敗内容:

| 失敗 assert | 推測される回帰 |
|------------|---------------|
| `assertMessageIdIsText` | ADR-026 が剥がれた / 新 schema で VARCHAR(100) に戻った |
| `assertMetaPageRoutingInSync` | ADR-024 系の subscription drift |
| `migration 041 column missing` | catch-up migration 漏れ (ADR-034 系) |

→ まず ADR-034 (deploy.yml の migration loop) + ADR-036 (schema integrity check)
が落ちていないか確認。落ちていなければ scene-04 が真の不整合を捕まえている。

### 4-4. 認証 (login) が失敗する

- 原因: Firebase 上の 3 ユーザーが消えた / パスワードが変わった
- 対処:
  1. Firebase Console で `qa-admin@salesanchor.jp` 等 3 ユーザーの存在確認
  2. パスワードが secrets と一致しているか確認
  3. 必要なら `setup_review_tenant.py` 系を改造して 3 ユーザーを再生成
     (ADR-038 Scope 外 — 別 ADR で扱う)

### 4-5. cleanup 後に seed 行が残っている

- 原因: 接頭辞 (`qa-` / `QA-`) を付けない手動投入が混入
- 対処: `cleanup-smoke-data.sh DRY_RUN=1` で件数を見て、想定外の残骸が判明したら
  本人に確認の上、`tenant_006` 内で個別 DELETE

---

## 5. 拡張するときの指針

新シナリオを足したい場合:

1. `tests/qa-smoke/scene-NN.spec.ts` で新規追加 (NN >= 09)
2. seed が増えるなら `seed-tenant.sql` に **接頭辞ルール厳守** で追加
3. 行数 assert も `seed-tenant.sql` 末尾の DO ブロックを更新
4. ADR-038 §L1 の seed 表 (ドキュメントだけ) と本 runbook の表を同期更新
5. 30 秒以内に完走しない scene は分割するか、ADR-038 Business constraints
   (VPS 2GB, duration≤30s) を理由に reject

---

## 6. 関連 ADR / ドキュメント

- `docs/adr/ADR-038-qa-smoke-suite.md` — 本 ADR (起案 2026-05-15)
- `docs/adr/ADR-025_meta_integration_operational_hardening.md` — 3 点セット要件
- `docs/adr/ADR-026_meta_message_id_text.md` — scene-04 regression guard 根拠
- `docs/adr/ADR-024_meta_subscription_drift.md` — scene-04 regression guard 根拠
- `docs/adr/ADR-027_i18n.md` — scene-07 が守る境界
- `docs/adr/ADR-028-screencast-tenant-isolation.md` — tenant_006 (撮影/QA 兼用)
- `docs/adr/ADR-034-tenant-migration-automation.md` — migration loop
- `docs/adr/ADR-036-tenant-schema-integrity.md` — schema-check.yml 補完
- 既存 mock e2e: `frontend/tests-e2e/scene{1..8}-*.spec.ts` (Meta App Review 撮影用)

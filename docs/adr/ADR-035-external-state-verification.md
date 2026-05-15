# ADR-035: External State Verification — 6 system × 5-layer defense

| 項目 | 内容 |
|------|------|
| ステータス | Proposed |
| 作成日 | 2026-05-15 |
| 起案 | ひとし（森本） |
| 関連 ADR | ADR-024（Meta 連携構造的修正）/ ADR-025（Meta 運用 hardening）/ ADR-026（IG message_id TEXT 化）/ ADR-029（self-hosted runner 2 台体制、**memory 参照、docs/adr/ には未起案、別 PR で正式起案候補**）/ ADR-034（テナント migration 自動化）/ ADR-036（テナントスキーマ整合性）/ ADR-038（QA Smoke Suite）/ ADR-039（Generator codebase reconnaissance） |

## What

外部システム（Meta App / Firebase Auth / GitHub Secrets+Actions / Cloudflare DNS / Discord Webhook / GCP IAM）の状態が repo の宣言と乖離（drift）することを構造的に検出する **5 層防御 (L1-L5)** を導入する。Generator/Evaluator agent 定義側 (`~/.claude/agents/`) は既に self-check 0.6 (External state pre-flight) + Step 3.7 (External system verification) で先行更新済（本セッション 2 ラウンド目）、本 ADR で backend repo 側のスクリプト群と契約ファイルを実装させる。「自己適用第 1 号スプリント」候補。

### L1: Contract (`docs/external-state-contract.yml`)

6 system の「期待される状態」を yaml で宣言。**raw secret は書かず name / id / sha256 prefix のみ**:

```yaml
# docs/external-state-contract.yml
last_updated: 2026-05-15
systems:
  meta_app:
    app_id_env: META_APP_ID            # 値そのものではなく env reference
    page_id_env: META_PAGE_ID
    subscribed_fields:
      page: [messages, messaging_postbacks, message_echoes]
      instagram: [messages, mentions]
    test_users: ["...@example.com"]    # 名前のみ
    review_state: in_review            # in_review | live
    last_verified: 2026-05-15
  firebase:
    project_id: sales-ops-with-claude
    auth_domain: auth.salesanchor.jp
    auth_providers: [google.com, password]
    authorized_domains: [salesanchor.jp, app.salesanchor.jp, auth.salesanchor.jp]
    last_verified: 2026-05-15
  github:
    secrets:
      - name: PIPELINE_PAT
        sha256_prefix: "abcdef12"
        updated_at: 2026-05-08
        rotation_due: 2026-08-05
      - name: DISCORD_WEBHOOK_PLAN_REVIEW
        sha256_prefix: "..."
    branch_protection:
      develop:
        required_checks: [static-analysis, qa-smoke, schema-check]
        required_reviewers: 1
    last_verified: 2026-05-15
  cloudflare:
    zone: salesanchor.jp
    dns_records: [...]  # name + type + content sha256
    waf_rules_count: N
    last_verified: 2026-05-15
  discord:
    webhooks:
      - name: DISCORD_WEBHOOK_PR
        channel: "#pr-notifications"
      - name: DISCORD_WEBHOOK_PLAN_REVIEW
        channel: "#plan-review"
      - name: DISCORD_WEBHOOK_OWNER_PING  # 本 ADR で新規追加
        channel: "#owner-ping"
    last_verified: 2026-05-15
  gcp:
    project_id: sales-ops-with-claude
    service_accounts: [...]  # email 列挙
    enabled_apis: [...]
    iam_role_count: N
    last_verified: 2026-05-15
```

### L2: Smoke (`scripts/smoke/external-{system}.sh`、6 本)

各 system に対する end-to-end 疎通テスト。**3 mode 対応**:

- `--dry-run`: 設定だけ読んで表示、実行しない
- `--sandbox` (default): sandbox / test 環境に投げる (Meta sandbox app, Discord smoke-test channel など)
- `--live`: 本番に投げる、`PO_LIVE_OK=yes` env 必須 (Generator / Evaluator は default 禁止)

```bash
# scripts/smoke/external-meta.sh の構造
#!/usr/bin/env bash
set -euo pipefail
MODE="${1:---sandbox}"
case "$MODE" in
  --dry-run)
    echo "META_APP_ID=$META_APP_ID  (sandbox app expected)"
    echo "META_PAGE_ID=$META_PAGE_ID"
    ;;
  --sandbox)
    # Meta sandbox app に valid HMAC で POST → backend 200 + DB row 確認
    ;;
  --live)
    [[ "${PO_LIVE_OK:-}" != "yes" ]] && {
      echo "live mode requires PO_LIVE_OK=yes"
      exit 1
    }
    # Meta production app に valid HMAC で POST
    ;;
esac
```

### L3: Snapshot (`scripts/snapshot/{system}.sh`、6 本)

各 system の状態を API で取得して json として保存、prev snapshot との diff で drift 検出:

```bash
# scripts/snapshot/meta.sh の構造
#!/usr/bin/env bash
set -euo pipefail
OUT="external-state-snapshots/$(date +%Y-%m-%d)-sprint-NN"
mkdir -p "$OUT"

# Graph API version は env から読む（実体: backend/app/services/meta_graph.py:134 既定 "v19.0"）
GRAPH_VERSION="${META_GRAPH_API_VERSION:-v19.0}"

# App access token は META_APP_ID|META_APP_SECRET 形式（Meta 公式仕様）
# META_APP_TOKEN という env は存在しないため使わない
META_APP_ACCESS_TOKEN="${META_APP_ID}|${META_APP_SECRET}"

# Graph API
curl -s "https://graph.facebook.com/${GRAPH_VERSION}/${META_APP_ID}?access_token=${META_APP_ACCESS_TOKEN}" \
  | jq 'del(.access_token, .secret) | .secret_sha256 = (.secret_present // false)' \
  > "$OUT/meta_app.json"
curl -s "https://graph.facebook.com/${GRAPH_VERSION}/${META_APP_ID}/subscriptions?access_token=${META_APP_ACCESS_TOKEN}" \
  > "$OUT/meta_subscriptions.json"
curl -s "https://graph.facebook.com/${GRAPH_VERSION}/${META_PAGE_ID}/subscribed_apps?access_token=${META_PAGE_TOKEN}" \
  > "$OUT/meta_page_subscribed_apps.json"

# prev snapshot との diff
prev="$(ls -td external-state-snapshots/*-sprint-* 2>/dev/null | sed -n 2p)"
[[ -n "$prev" ]] && diff <(jq -S . "$prev/meta_app.json") <(jq -S . "$OUT/meta_app.json") || echo "no prev snapshot"
```

**secret scrub ルール**: snapshot json には raw secret を **絶対に書かない**。Reviewer は merge 前に各 snapshot.sh の scrub ロジックを目視確認。

| Scrub 形式 | 使い分け |
|------------|----------|
| `sha256:<8byte>` prefix | secret value 自体が必要だが raw を残せない時（例: token / API key の指紋として比較したい場合）。`echo -n "$VALUE" \| sha256sum \| head -c 8` で生成 |
| `*_present: true/false` | secret value の比較すら不要、存在の有無だけ重要な場合（例: subscriber token が登録されているか） |
| `del(.field)` で削除 | secret value は snapshot にとって完全に不要（例: access_token、refresh_token、private_key） |

最後の砦として `.gitignore` に `external-state-snapshots/*/private/` を追加（snapshot directory は commit 対象だが、`private/` subdirectory に意図せず secret を書いた場合に commit を防止）。

### L4: Manual evidence (`docs/runbooks/external-evidence/{system}/`)

API で見えない surface のスクリーンショット置き場（PNG 等）。Generator が撮ったスクショを保存 + report に file path 明記。Evaluator は EXIF / git timestamp を確認（sprint date 範囲内か）。

各 system × 確認対象（例）:

| System | API 不可で screenshot 必須の surface |
|--------|---------------------------------------|
| Meta | App Review state, Test Users, App Mode toggle |
| Firebase | OAuth provider details, Authorized domains |
| GitHub | Environment protection rules, required reviewers |
| Cloudflare | WAF custom rules, Page Rules |
| Discord | Channel permissions, Bot invite state |
| GCP | Org policy, Quotas |

### L5: Owner ping (`scripts/notify/discord-owner-ping.sh`)

人間 dashboard 操作が必要な action items を `## External system action items` セクションに列挙、Discord 通知:

```bash
# scripts/notify/discord-owner-ping.sh の構造
#!/usr/bin/env bash
set -euo pipefail
BODY="$1"  # markdown 形式の action items
PAYLOAD=$(jq -nc --arg content "$BODY" '{content: $content}')
curl -X POST -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$DISCORD_WEBHOOK_OWNER_PING"
```

### 起動条件（Generator 0.6 + Evaluator 3.7）

- Change kind #11（OAuth / external app ID / Webhook URL）
- Change kind #10（Secret rotation）
- Change kind #5（ENV）when env name matches `META_*` / `FIREBASE_*` / `CLOUDFLARE_*` / `DISCORD_*` / `GCP_*` / `GITHUB_*`
- 週次 cron（毎週日曜 03:00 JST、本 ADR で導入する `external-state-snapshot.yml`）

### 週次 cron (`.github/workflows/external-state-snapshot.yml`)

```yaml
on:
  schedule:
    - cron: '0 18 * * 0'  # 毎週日曜 03:00 JST
  workflow_dispatch: {}
jobs:
  snapshot:
    runs-on: self-hosted   # Hikky-dev-Mac / Shingo-Mac-Temp 2 台体制 (ADR-029)
    steps:
      # 6 system × snapshot.sh を直列実行（VPS 2GB 配慮）
```

snapshot 結果は `external-state-snapshots/{date}/{system}.json` に保存し、drift があれば Discord に通知。

## Why

2026-05-15 朝にしんごさんが見つけた 3 件のバグの 1 つ「meta_page_routing 自動登録なし → webhook 不着」は ADR-024 で構造的に修正されたが、もう一段別の構造的問題が残っている:

**外部システム (Meta dashboard / Firebase Console / GitHub Settings 等) の状態は repo に grep で見えない**ため、Generator が「Meta App Review state を変えた」「Firebase OAuth provider を追加した」等の変更を verify する手段がない。Reviewer が code review しても「Meta dashboard 上の subscription が repo の宣言と一致しているか」は確認できない。

これまでは:
- ADR-025（Meta 運用 hardening）で deploy.yml の env 注入を修正
- ADR-024（Meta 連携構造的修正）で subscribed_apps / 暗号化キーを修正
- 個別事案ごとに後追い

本 ADR は「外部システム drift を**毎スプリント + 週次 cron で機械的に検出**する 5 層防御」を立てる。Generator/Evaluator agent 定義側（Step 3.7 / self-check 0.6）は既に effective なので、本 ADR の merge + 実装で **agent 側の指示を満たすスクリプトが repo に揃う**ことになる。

ADR-039（GAP-B 対策、Bash allow-list 化、MERGED 2026-05-15 14:24 UTC）と組み合わせると Generator が `Bash(bash scripts/smoke/:*)` `Bash(bash scripts/probe/:*)` を実行できるので、本 ADR の `scripts/smoke/external-*.sh` を Generator/Evaluator 両方が実行可能。

## Scope (IN)

backend repo `shingo-ops/salesanchor` に以下 **15 ファイル**を追加:

- `docs/external-state-contract.yml`（L1、6 system）
- `scripts/smoke/external-meta.sh` / `external-firebase.sh` / `external-github.sh` / `external-cloudflare.sh` / `external-discord.sh` / `external-gcp.sh`（L2、6 本、`--dry-run` / `--sandbox` / `--live` 3 mode 対応）
- `scripts/snapshot/meta.sh` / `firebase.sh` / `github.sh` / `cloudflare.sh` / `discord.sh` / `gcp.sh`（L3、6 本、secret scrub 必須）
- `scripts/notify/discord-owner-ping.sh`（L5、新規 webhook `DISCORD_WEBHOOK_OWNER_PING` を使用）
- `.github/workflows/external-state-snapshot.yml`（週次 cron + workflow_dispatch、self-hosted runner で 6 system 直列実行）
- `docs/runbooks/external-evidence/.gitkeep` + 6 サブディレクトリ`{meta,firebase,github,cloudflare,discord,gcp}/.gitkeep`（L4 placeholder）
- `docs/runbooks/external-state-operations.md`（運用手順、drift 検出時の対応、新 system 追加手順）

加えて `.gitignore` に **1 行追加**:

```
external-state-snapshots/*/private/
```

加えて以下の secrets を GitHub に追加が必要（しんごさん側で手動設定、別作業）:

- `DISCORD_WEBHOOK_OWNER_PING`（新規、Owner ping 用 channel webhook URL）
- `CLOUDFLARE_API_TOKEN`（snapshot.sh / smoke.sh で必要、existing なら確認）
- 既存の `META_*` / `FIREBASE_*` / `GCP_*` / `PIPELINE_PAT` / `DISCORD_WEBHOOK_*` は変更なし

L4 manual evidence の PNG ファイルは **Generator が `git add` する義務** がある。`docs/runbooks/external-evidence/{system}/` 配下に保存後、commit に含めること（Evaluator が timestamp 確認するため）。

## Scope (OUT — 明示除外)

- **7 system 目以降の追加**（Stripe / Sendgrid / AWS など）→ 別 ADR で扱う。本 ADR は 6 system の bootstrap に絞る、scope creep 防止
- **Generator/Evaluator agent 定義の更新** → 既に self-check 0.6 + Step 3.7 で effective（本セッション 2 ラウンド目）、本 ADR では agent 定義は触らない
- **アラート機構の自動化**（drift 検出時に GitHub Issue 自動作成 / Slack notification など）→ 別 ADR、本 ADR は Discord webhook 通知のみで最小実装
- **contract drift の自動マージ**（drift 検出 → contract 自動更新）→ 禁止。人間の意図確認なしで状態を「正」とみなすのは ADR-025 の手動 DB INSERT 禁止と同じ理由で危険
- **既存 ADR-024 / ADR-025 の修正範囲** → 本 ADR は新規追加のみ、既存 Meta 連携コードは触らない
- **token rotation 自動化** → 本 ADR は手動 rotation 前提、自動 rotation は別 ADR
- **CLAUDE.md への大規模追記** → 既に §External state verification は本セッションで追記済、本 ADR では追加修正なし
- **Meta sandbox app の正式整備** → 本 ADR Phase 0 では `META_SANDBOX_APP_ID` 等の新規 secret 追加は scope 外。`--sandbox` mode は **dry-run 相当として scaffold**（実 API call せず、設定だけ表示）。本番 `META_APP_ID` を `--sandbox` で使い回す事故を防ぐため、`scripts/smoke/external-meta.sh --sandbox` は実装時に「sandbox app 未整備のため dry-run 動作」と stderr に明示出力。Meta sandbox app の正式整備（`META_SANDBOX_APP_ID` / `META_SANDBOX_PAGE_ID` 追加 + L2 smoke の実 API call 化）は別 ADR で扱う

## Business constraints

- **VPS 2GB**: snapshot 6 本の同時実行は重い → 週次 cron は **直列実行** (concurrent 1) で動かす、各 snapshot 終了後 5s sleep を入れる
- **secret 漏洩リスク**: snapshot json に**絶対に raw secret を書かない**、必ず scrub (`sha256:<8byte>` prefix または `*_present: true/false`)。Reviewer は merge 前に各 snapshot script の scrub ロジックを目視確認
- **API rate limit**: Meta Graph API は app 単位 200 calls/h、6 system × snapshot 1 回で ~30 calls 消費 → 週次 cron は問題なし、手動 workflow_dispatch も問題なし（毎日 100 回叩くと枯渇のため Generator/Evaluator は week 1 回まで）
- **マージ判断は しんごさん review 不要**: External state verification は運用基盤、Meta 申請関連ではないため Reviewer エージェント経路（ADR-039 と同じ判断）
- **`--live` mode の安全性**: 既定で `--sandbox`、`--live` は `PO_LIVE_OK=yes` env 必須、Generator/Evaluator は default で `--sandbox` 走行

## 成功基準

1. 本 ADR merge 後の実装 PR で 15 ファイルが repo に揃う
2. 次回 Generator スプリントで Change kind #11 が触れた時、Generator report に `## External state verification` 表（L1-L5）が記録される（現在は agent 定義あるがスクリプト不在のため記録不可）
3. 週次 cron が初回（本 ADR merge 後の次の日曜 03:00 JST）に走り、Discord に 6 system のスナップショット結果が通知される
4. Reviewer エージェントが Generator report の `## External state verification` 表を独立検証可能（Step 3.7 の Pass/fail thresholds が effective）
5. 過去 2026-05-15 朝の事故「Meta dashboard 上 subscription drift」を意図的に再現したとき、L3 snapshot の diff で検出される（Phase 1 検証スプリントで確認）

## 想定リスク

1. **Secret 漏洩**: snapshot json に raw secret が混入する事故 → 各 snapshot.sh の scrub ロジックを Reviewer が目視確認 + `.gitignore` に `external-state-snapshots/*/private/` 系を追加 (snapshot directory は commit 対象だが、private subdirectory は除外、運用で誤って入れた時の最後の砦)
2. **API token expire**: snapshot.sh 実行時に Meta App token / Firebase admin SDK token / GCP service account 等が expire → cron 失敗 → Discord に通知 → 人間 (PO) が token 更新。token rotation 自動化は別 ADR (Scope OUT)
3. **VPS リソース**: 週次 cron が深夜実行のため通常 1.3GB consumption に加えて snapshot 6 本でも問題ないはず、ただし `mem ≤ 1700MB` SLO を観察、超えるようなら直列 + sleep 5s 挿入で緩和
4. **6 system 中で一部 system の bootstrap が困難**: 例えば GCP IAM の snapshot は service account 設定が複雑 → Phase 0（本 ADR の実装）で全 6 system を bootstrap、Phase 1（実運用）で deltas 検証、不安定な system は `last_verified: deferred` で contract に記録し agent 側で skip
5. **Cloudflare API rate limit**: Cloudflare API は 1200 calls/5min、6 system 中 1 つだけ → 余裕、ただし dashboard 経由しか確認できない rule は L4 manual evidence でカバー
6. **runner host (Hikky-dev-Mac) sleep**: ADR-029 で sleep 抑制せず方針、shutdown 中は runner offline 許容。週次 cron 実行時に runner が offline だった場合は次起動時に手動 `gh workflow run` で復旧（runbook に記載）

## 関連 referent（起案時 reconnaissance 結果）

ADR-039 §Codebase reconnaissance 規約の早期適用として、本 ADR 起案時に grep / read で実体確認した referent を以下に記録（実装 Generator の reconnaissance 負荷を軽減する experimental 試行、ADR template 化判断の素材）:

| Referent | Type | grep cmd | hit count | top file:line | Action | 備考 |
|----------|------|----------|-----------|---------------|--------|------|
| `META_APP_ID` | env | `grep -rn "META_APP_ID" backend/ .env.example` | 9 files | backend/app/routers/webhook.py 等 | Keep | 実在 |
| `META_PAGE_TOKEN` `META_PAGE_ID` `META_APP_SECRET` | env | (同上) | 9 files | (同上) | Keep | 実在 |
| `META_GRAPH_API_VERSION` | env | `grep -rn "META_GRAPH_API_VERSION" backend/app/services/` | 3 lines | backend/app/services/meta_graph.py:134 | Keep | 実在、既定 `v19.0`（snapshot.sh で必須参照） |
| `META_APP_ACCESS_TOKEN`（組み立て） | derived | (env 不在、Meta 公式 app access token 形式) | 0 hit | (none) | **Compose** | `${META_APP_ID}\|${META_APP_SECRET}` 形式で組み立て、env として保存しない |
| `METADATA_FERNET_KEY` | env | `grep -rn "METADATA_FERNET_KEY" backend/` | 9 files | backend/app/services/encryption.py | Keep | 実在 |
| `FIREBASE_API_KEY` `FIREBASE_AUTH_DOMAIN` | env | `grep -rn "FIREBASE_" .env.example` | 4 lines | .env.example:18-19 | Keep | 実在 |
| `GOOGLE_APPLICATION_CREDENTIALS` | env | (同上) | 1 line | .env.example:20 | Keep | 実在、`/app/firebase-credentials.json` |
| `GCP_PROJECT_ID` | env | `grep -rn "GCP_" .env.example` | 1 line | .env.example:17 = `sales-ops-with-claude` | Keep | 実在 |
| `PIPELINE_PAT` | github secret | `grep -rn "PIPELINE_PAT" .github/workflows/` | 1 line | .github/workflows/claude-pipeline.yml:24 | Keep | 実在 |
| `DISCORD_WEBHOOK_PLAN_REVIEW` | github secret | `grep -rn "DISCORD_WEBHOOK" .github/workflows/` | 3 lines | .github/workflows/claude-pipeline.yml | Keep | 実在 |
| `DISCORD_WEBHOOK_PR` | github secret | (同上) | 5 lines | .github/workflows/discord-pr-notify.yml | Keep | 実在 |
| `DISCORD_WEBHOOK_OWNER_PING` | github secret | (同上) | 0 hit | (none) | **Add**（本 ADR で新規追加、しんごさん手動設定） | 新規 |
| `CLOUDFLARE_API_TOKEN` | github secret | `grep -rn "CLOUDFLARE" .github/workflows/ .env.example backend/` | 0 hit | (none) | **Add**（しんごさん手動設定、未登録なら新規） | jarvis-claude.uk + salesanchor.jp ドメイン管理で使用想定 |
| `docs/B-06_cloudflare_setup.md` | doc | `ls docs/B-06_cloudflare_setup.md` | exists | docs/B-06_cloudflare_setup.md | Keep | 既存 Cloudflare 設定 runbook、本 ADR の §関連 から参照可 |
| `scripts/qa/` | dir | `ls scripts/` | exists | scripts/qa/{reset,seed,cleanup}-*.sh | Keep | 実在（ADR-038 で導入） |
| `scripts/smoke/` | dir | `ls scripts/` | 0 hit | (none) | **Add**（本 ADR で新設） | 新規 |
| `scripts/snapshot/` | dir | `ls scripts/` | 0 hit | (none) | **Add**（本 ADR で新設） | 新規 |
| `scripts/notify/` | dir | `ls scripts/` | 0 hit | (none) | **Add**（本 ADR で新設） | 新規 |
| `docs/runbooks/` | dir | `ls docs/runbooks/` | exists | (ADR-038 qa-smoke-operations.md 含む) | Keep | 実在 |
| `docs/runbooks/external-evidence/` | dir | (同上) | 0 hit | (none) | **Add** | 新規 |
| `.github/workflows/external-state-snapshot.yml` | workflow | `ls .github/workflows/` | 0 hit | (none) | **Add** | 新規 |
| `external-state-snapshots/` | dir | `ls .` | 0 hit | (none) | **Add**（snapshot 出力先） | 新規 |

Total referents: 22  /  0-hit replaced: 0（全て新規 Add or Compose）/  Halted: 0

### 起案フェーズ recon の自己反省（Reviewer Round 1 で判明）

PR #379 1 回目 Reviewer で Major 2 件指摘 (`META_APP_TOKEN` 実体不在 / Graph API `v18.0` hard-code → 実体 `v19.0`) が出た。これは本 §関連 referent 表に **Reconnaissance 段階で `META_APP_TOKEN` / `META_GRAPH_API_VERSION` の grep を行わなかった** ことが直接原因。GAP-B (ADR 概念 → 実体マッピング欠落) が ADR 起案者自身で発生した typical 事例。本セクションの存在意義そのもの = template 化推奨の根拠。本修正で両 referent を表に追加済、今後の ADR 起案では「ADR 内で言及した全 env / API endpoint / secret name / file path」を **書く前に grep する** ルールを徹底する（次サイクルで ADR template 化判断材料）。

## 関連メモリ・ドキュメント

- 本セッション設計プラン: ひとし side local の `~/.claude/plans/generic-skipping-fox.md`（GAP-B 版で上書き済、外部システム検証設計は memory に残存）
- Evaluator agent 定義: `~/.claude/agents/evaluator.md` Step 3.7 External state verification (L1-L5)
- Generator agent 定義: `~/.claude/agents/generator.md` self-check item 0.6 External state pre-flight + 報告書テンプレ `## External state verification` + `## External system action items`
- ADR-024（Meta 連携構造的修正、deploy.yml env 注入修正の前段）
- ADR-025（Meta 運用 hardening、deploy.yml `grep -q` 上書きパターン廃止 + 検証スクリプト）
- ADR-026（IG message_id TEXT 化、PR #341/#342 MERGED）
- ADR-029（self-hosted runner 2 台体制、Shingo-Mac-Temp 追加、本 ADR の cron runner で利用）
- ADR-038（QA Smoke Suite、本 ADR と並走する「自己適用第 4 号スプリント」、MERGED）
- ADR-039（Generator codebase reconnaissance、本 ADR の Generator 側で `Bash(bash scripts/smoke/:*)` が機能する allow-list 含む、MERGED 2026-05-15 14:24 UTC）
- 既存 Discord 通知機構: `secrets.DISCORD_WEBHOOK_PLAN_REVIEW`（PR レビュー通知）+ `secrets.DISCORD_WEBHOOK_PR`、本 ADR の Owner ping は別 webhook `DISCORD_WEBHOOK_OWNER_PING` を新規追加

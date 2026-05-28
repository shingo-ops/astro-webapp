# B-13: 管理室VPS ガバナンス継続化チェックリスト

## 目的

管理室VPS（監視スタック + CIランナー）の健全性を継続的に維持するためのチェックリスト。
ADR-080 による分離後、運用が属人化しないよう定期チェックを制度化する。

## 最終更新: 2026-05-28

**設計根拠**: ADR-080（監視スタックの管理室VPS分離）

---

## 月次チェック（毎月1日に実施）

担当: PO（しんごさん）または Agent（Claude Code）

### リソース確認

- [ ] 管理室VPSのメモリ使用率が 80% 以下である
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP "free -h"
  # available が total の 20% 以上あること
  ```

- [ ] 管理室VPSのディスク使用率が 80% 以下である
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP "df -h /"
  # Use% が 80% 以下であること
  ```

- [ ] Docker ボリューム（Prometheus TSDB, Loki データ, Grafana データ）のサイズが異常に肥大化していない
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP "docker system df -v"
  # prometheus_data, loki_data のサイズを確認
  ```

### コンテナ稼働確認

- [ ] 全コンテナが healthy/running である
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP "cd /opt/salesanchor-monitoring && docker compose -f docker-compose.monitoring.yml ps"
  ```

- [ ] Prometheus の全 scrape target が UP である
  ```bash
  curl -s http://MGMT_PUBLIC_IP:9090/api/v1/targets | python3 -c "
  import sys, json
  data = json.load(sys.stdin)
  down = [t for t in data['data']['activeTargets'] if t['health'] != 'up']
  print(f'DOWN targets: {len(down)}')
  for t in down: print(f'  - {t[\"labels\"].get(\"job\",\"?\")}')
  "
  ```

- [ ] Grafana API が正常応答する
  ```bash
  curl -s https://app.salesanchor.jp/grafana/api/health
  # → {"database":"ok"}
  ```

- [ ] Uptime Kuma が監視対象を正常にチェックしている

### GitHub Actions runner 確認

- [ ] `salesanchor-vps` runner が Online である
  ```bash
  gh api /repos/shingo-ops/salesanchor/actions/runners \
    --jq '.runners[] | select(.name=="salesanchor-vps") | {status: .status}'
  # → "online"
  ```

- [ ] 直近1ヶ月の qa-smoke / external-state-snapshot の実行履歴を確認
  ```bash
  gh run list --workflow qa-smoke.yml --repo shingo-ops/salesanchor --limit 5
  ```

### アプリVPS 側 exporter 確認

- [ ] アプリVPSの exporter コンテナが全て稼働している
  ```bash
  ssh <USER>@49.212.137.46 "docker compose ps | grep exporter"
  ```

- [ ] アプリVPSのメモリに余裕がある（分離の効果が維持されている）
  ```bash
  ssh <USER>@49.212.137.46 "free -h"
  ```

---

## 90日ごとの認証情報ローテーション

担当: PO（しんごさん）

> B-11（認証情報管理ルール）のローテーション表と連動する。

### Claude Code 専用 SSH 鍵（ADR-079）

対象: `~/.ssh/salesanchor-claude`（ローカル Mac 上）

- [ ] 新しい ed25519 鍵ペアを生成
  ```bash
  ssh-keygen -t ed25519 -C "claude-monitor-$(date +%Y%m%d)" -f ~/.ssh/salesanchor-claude-new
  ```

- [ ] **アプリVPS** の `claude-monitor` ユーザーの `authorized_keys` を新鍵に更新
  ```bash
  ssh <ADMIN_USER>@49.212.137.46 \
    "sudo su - claude-monitor -c 'cat > ~/.ssh/authorized_keys'" < ~/.ssh/salesanchor-claude-new.pub
  ```

- [ ] **管理室VPS** の `claude-monitor` ユーザーの `authorized_keys` を新鍵に更新
  ```bash
  ssh <ADMIN_USER>@MGMT_PUBLIC_IP \
    "sudo su - claude-monitor -c 'cat > ~/.ssh/authorized_keys'" < ~/.ssh/salesanchor-claude-new.pub
  ```

- [ ] 新鍵で両VPSに接続できることを確認
  ```bash
  ssh -i ~/.ssh/salesanchor-claude-new claude-monitor@49.212.137.46
  ssh -i ~/.ssh/salesanchor-claude-new claude-monitor@MGMT_PUBLIC_IP
  ```

- [ ] 旧鍵を削除し、新鍵をリネーム
  ```bash
  mv ~/.ssh/salesanchor-claude ~/.ssh/salesanchor-claude-old
  mv ~/.ssh/salesanchor-claude-new ~/.ssh/salesanchor-claude
  mv ~/.ssh/salesanchor-claude-new.pub ~/.ssh/salesanchor-claude.pub
  # 確認後に旧鍵を削除
  rm ~/.ssh/salesanchor-claude-old
  ```

- [ ] B-11 のローテーション記録を更新（次回ローテーション日を記入）

### Grafana Service Account Token（ADR-079）

対象: `claude-code-reader` サービスアカウントのトークン

- [ ] Grafana UI にログイン → Administration → Service Accounts → `claude-code-reader`
- [ ] 既存トークンを Revoke
- [ ] 新しいトークンを生成（有効期限: 90日）
- [ ] Claude Code のアクセス設定に新トークンを反映
  - `~/.claude-access.env` またはキーチェーンを更新
- [ ] 新トークンで Grafana API にアクセスできることを確認
  ```bash
  curl -H "Authorization: Bearer <NEW_TOKEN>" \
    https://app.salesanchor.jp/grafana/api/datasources
  # → 200 OK
  ```
- [ ] B-11 のローテーション記録を更新

### Grafana 管理者パスワード

- [ ] 管理室VPSの Grafana でパスワード変更
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP \
    "cd /opt/salesanchor-monitoring && docker compose -f docker-compose.monitoring.yml exec grafana grafana-cli admin reset-admin-password '<NEW_PASSWORD>'"
  ```
- [ ] `.env` の `GRAFANA_PASSWORD` を更新
- [ ] GitHub Secrets の `GRAFANA_PASSWORD` を更新（deploy.yml で使用している場合）
- [ ] B-11 のローテーション記録を更新

---

## 半年ごとのレビュー（6月・12月）

担当: PO（しんごさん）

### インフラ見直し

- [ ] 管理室VPSのプラン（CPU/メモリ/ディスク）が現在のワークロードに適切か
  - 過去6ヶ月のメモリ使用率の推移を Grafana で確認
  - ディスク使用量の増加傾向を確認
  - スケールアップ/ダウンの必要性を判断

- [ ] Prometheus のデータ保持期間（デフォルト30日）が適切か
  - 長期トレンド分析が必要ならリモートストレージ導入を検討

- [ ] Loki のログ保持期間が適切か
  - ディスク消費量と保持期間のバランスを確認

### セキュリティ見直し

- [ ] ファイアウォールルールの棚卸し
  - 不要になったポート許可がないか
  - 送信元IP制限が正しいか

- [ ] VPS 上の OS パッケージが最新か
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP "sudo apt list --upgradable 2>/dev/null | head -20"
  ```

- [ ] Docker イメージのバージョンが最新か（セキュリティパッチ）
  ```bash
  ssh <USER>@MGMT_PUBLIC_IP "cd /opt/salesanchor-monitoring && docker compose -f docker-compose.monitoring.yml images"
  ```

- [ ] `claude-monitor` ユーザーの `ForceCommand` 制限が適切か（不要なコマンドが追加されていないか）

### コスト見直し

- [ ] 管理室VPSの月額コストが予算内か
- [ ] さくらVPSの料金プラン改定がないか確認
- [ ] 他のクラウドサービス（Conoha, AWS Lightsail 等）との比較が必要か

---

## アラート設定確認

### Grafana アラートの生存確認（月次チェックに含める）

- [ ] Prometheus アラートルールが全て読み込まれている
  ```bash
  curl -s http://MGMT_PUBLIC_IP:9090/api/v1/rules | python3 -c "
  import sys, json
  data = json.load(sys.stdin)
  for g in data['data']['groups']:
      for r in g['rules']:
          print(f\"{r['name']:30s} {r['state']}\")
  "
  ```

- [ ] Discord 通知の Contact Point がアクティブである
  - Grafana → Alerting → Contact points → discord-ops → Test → Discord にテスト通知が届く

- [ ] Uptime Kuma の通知設定がアクティブである
  - Uptime Kuma → Settings → Notifications → テスト通知を送信

### 期待されるアラートルール一覧

| ルール名 | ソース | 種別 |
|---------|--------|------|
| HighCpuUsage | Prometheus | リソース |
| HighMemoryUsage | Prometheus | リソース |
| HighDiskUsage | Prometheus | リソース |
| PostgresDown | Prometheus | サービス |
| HighErrorRate | Prometheus | アプリ |
| High502Rate | Prometheus | アプリ |
| ServiceDown | Prometheus | サービス |
| BruteForceAttempt | Loki | セキュリティ |
| BackendErrorSpike | Loki | アプリ |
| DatabaseError | Loki | データベース |

> 上記ルールが全て存在しない場合、Grafana プロビジョニング設定を再確認する。

---

## 緊急時の連絡先・手順

| 事象 | 対処 | 参照 |
|------|------|------|
| 管理室VPSが応答しない | さくらVPSコンソールからリブート | さくらVPS コントロールパネル |
| 監視が全て落ちた | ロールバック手順を実行 | `docs/runbooks/monitoring-vps-migration.md §ロールバック手順` |
| runner が Offline になった | VPS上で systemd サービスを再起動 | `docs/runbooks/vps-runner-setup.md §トラブルシューティング` |
| OOM 発生 | dmesg 確認 → 原因コンテナのメモリ上限調整 | ADR-080 |
| SSH 鍵で接続できない | PO が VPS コンソールから authorized_keys を確認 | ADR-079 |

---

## 参照ドキュメント

- ADR-080: `docs/adr/ADR-080-monitoring-vps-separation.md`
- ADR-079: `docs/adr/ADR-079-claude-code-monitoring-access.md`
- B-10: `docs/B-10_access_review_procedure.md`（月次アクセス棚卸し）
- B-11: `docs/B-11_credential_management_policy.md`（認証情報管理）
- 移行 runbook: `docs/runbooks/monitoring-vps-migration.md`
- VPS runner runbook: `docs/runbooks/vps-runner-setup.md`

# ADR-079: Claude Code 専用 VPS 読み取り専用監視アクセス

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-28 |
| 起案 | しんごさん（PO） |
| 関連 ADR | ADR-075（GitHub Secrets Only Policy）/ ADR-070（Grafana 監視統合）/ ADR-029（self-hosted runner fleet）/ ADR-078（VPS runner 登録） |

## What

Claude Code（AI エージェント）が本番 VPS（49.212.137.46）のリソース状態をオンデマンドで読み取れるよう、以下 2 経路のアクセスを整備する。

| 経路 | 用途 | 権限スコープ |
|------|------|------------|
| SSH（`claude-monitor` 専用ユーザー） | `docker stats`, `free -h`, `df -h` 等の OS/コンテナメトリクス取得 | 特定コマンドのみ実行可（`ForceCommand` で制限）。書き込み・sudo 不可 |
| Grafana Service Account Token | PromQL クエリ・ダッシュボード参照 | Viewer ロール（読み取り専用。ダッシュボード作成・データソース変更不可） |

### 登録情報

| 項目 | 値 |
|------|----|
| SSH 鍵パス（ローカル） | `~/.ssh/salesanchor-claude`（ed25519） |
| SSH ユーザー（VPS） | `claude-monitor` |
| 許可コマンド | `docker stats --no-stream; free -h; df -h; uptime` |
| Grafana Service Account | `claude-code-reader`（Viewer ロール） |
| トークン有効期限 | 90 日（B-11 ローテーション表に登録） |

## Why

1. **監視投資の効果半減解消**: ADR-069/070 で Prometheus + Grafana + Uptime Kuma を整備済みだが、Claude Code からアクセスできないため「今のサーバー状態は？」という問いに即答できない。
2. **障害対応速度の向上**: BT Group 事例では同構成の導入で修復時間 97.6% 削減（2 時間→85 秒）を達成（2022-2025 年実績）。
3. **深夜オンコール負荷軽減**: Microsoft Azure SRE Agent と同じ「Reader 権限のみ付与」ポリシーを採用し、Claude Code が診断を先行実施できる状態にする。

## Scope IN

- `claude-monitor` ユーザー作成（VPS、専用 SSH 鍵、ForceCommand 制限）
- Grafana Service Account（`claude-code-reader`、Viewer ロール）のトークン発行
- SSH 鍵（`~/.ssh/salesanchor-claude`）の生成と authorized_keys 登録
- B-10（月次棚卸し）・B-11（ローテーション表）への記載追加
- promtail に SSH 接続ログ収集を追加（`/var/log/auth.log`）
- セットアップ用スクリプト（`scripts/setup-claude-monitor-user.sh`）
- 運用 runbook（`docs/runbooks/claude-monitor-access.md`）

## Scope OUT（明示除外）

- Claude Code からの書き込み・設定変更（一切禁止）
- Grafana Enterprise の監査ログ（OSS 版のため対象外）
- VPS への CI/CD パイプライン接続（ADR-078 の runner と別管理）
- 他ユーザーへの SSH 鍵追加・権限変更

## セキュリティ設計

### 最小権限原則の実装

```
ForceCommand="docker stats --no-stream; free -h; df -h; uptime"
no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty
```

`claude-monitor` ユーザーには sudo 権限なし。`ForceCommand` により上記 4 コマンドのみ実行可能。SSH 接続してもシェルは取得できない。

### トークン・鍵の保管方針

- **SSH 秘密鍵**: `~/.ssh/salesanchor-claude`（ローカル Mac のみ。リポジトリ・memory ファイルに含めない）
- **Grafana トークン**: macOS キーチェーン または `~/.claude-access.env`（リポジトリ外。600 権限）
- **memory ファイル**: アクセス先情報（ユーザー名・パス・URL）のみ記録。トークン実値は書かない

### ローテーション

| 対象 | 周期 | 担当 |
|------|------|------|
| SSH 鍵（`salesanchor-claude`） | 90 日 | しんごさん（手順: `docs/runbooks/claude-monitor-access.md §ローテーション`） |
| Grafana Service Account Token | 90 日 | しんごさん（Grafana UI から revoke → 再発行） |

## 主なリスクと対策

| リスク | 対策 |
|--------|------|
| SSH 鍵漏洩 | `ForceCommand` で実行コマンドを 4 つに限定。シェル取得不可。90 日ローテーション |
| Grafana Viewer がデータソース全体にクエリ可能 | 現時点では許容（salesanchor データソースは Prometheus のみ）。将来 Enterprise 移行時に制限 |
| 権限の肥大化 | B-10 月次棚卸しで `claude-monitor` 鍵を必須チェック対象に追加 |
| メモリへのトークン実値保存 | Claude Code の memory ファイル全体を gitleaks でスキャン済み（現時点 0 件確認）。保存ルールを Scope IN に明記 |

## 成功基準

1. `ssh -i ~/.ssh/salesanchor-claude claude-monitor@49.212.137.46` で `docker stats --no-stream` の結果が返る
2. `curl -H "Authorization: Bearer <token>" https://app.salesanchor.jp/grafana/api/datasources` が 200 を返す
3. Grafana Explore から `node_memory_MemTotal_bytes` クエリが実行できる
4. `ssh ... 'rm /etc/passwd'` 等の破壊的コマンドが Permission denied で拒否される

## 関連ドキュメント

- セットアップスクリプト: `scripts/setup-claude-monitor-user.sh`
- 運用 runbook: `docs/runbooks/claude-monitor-access.md`
- ADR-075: GitHub Secrets Only Policy
- ADR-070: Grafana 監視統合
- B-10: `docs/B-10_access_review_procedure.md`
- B-11: `docs/B-11_credential_management_policy.md`
- B-12: `docs/B-12_offboarding_procedure.md`

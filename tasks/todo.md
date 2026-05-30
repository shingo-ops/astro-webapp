# Tasks

タスク台帳の正本。セッション開始時に必ず読むこと（`AGENTS.md §引き継ぎルール` 参照）。

---

## 進行中

| タスク | 担当 | 現在地 | 次の一手 | 根拠 | 更新日 |
|------|------|------|---------|-----|------|
| Generator executor フォールバック（ADR-082） | Agent | claude-pipeline.yml 実装済み・ADR-082 作成済み・AGENTS.md 反映済み | PR 作成 → develop マージ | .github/workflows/claude-pipeline.yml ローカル変更済み / ADR-082 作成済み / EV-20260530-001 記録済み | 2026-05-30 |
| Claude Code KPI / Grafana 基盤 | Agent | backend の同時処理中リクエスト数 / SSE 接続数を `/metrics` と Grafana `backend-api-metrics` に追加し、workers=1 判定用の監視線を整備済み | Prometheus alert の warning line を実測値に合わせて微調整し、KPI 正本 `docs/ai-agents/kpi.md` の collector 設計へ反映する | `backend/app/metrics.py` / `backend/app/services/sse_pubsub.py` / `monitoring/grafana/provisioning/dashboards/json/backend-metrics.json` / `monitoring/prometheus/alert_rules.yml` / `docs/INCIDENT_RESPONSE.md` 確認済み | 2026-05-30 |
| 監視VPS移行 M8（ADR-080） | PO待ち | M7完了・M8未着手。ADR-081 で監視VPS 受信経路と backend worker 方針を最終確定済み | PO確認の上、Sakura パケットフィルタ反映 → app VPS から 3000/3001/9090 疎通確認 → 1週間運用確認後にアプリVPSの旧監視Dockerボリューム削除（prometheus_data/grafana_data/loki_data） | docs/runbooks/monitoring-vps-migration.md / docs/adr/ADR-081-monitoring-vps-final-operational-design.md | 2026-05-30 |
| VPS runner登録（ADR-078） | Agent（2026-06-15予定） | 未着手 | 予定日に `docs/runbooks/vps-runner-setup.md` に従い実行 | memory/project_vps_runner_plan.md | 2026-05-29 |
| Meta App Review 申請 | PO待ち | ドキュメント整備済み・動画未撮影 | PO が申請動画を撮影 → Agent がレビュー申請書類を提出 | memory/project_meta_app_review_progress.md | 2026-05-29 |

---

## 完了（直近）

| タスク | 完了日 | PR |
|------|------|---|
| AEON operation guide canonicalization | 2026-05-30 | docs/ai-agents/aeon-operation.md |
| AEON ディスパッチャ smoke validation | 2026-05-30 | /tmp/aeon-delivery-20260530-052601.log |
| リリース develop → main | 2026-05-29 | #1135 |
| 監視VPS移行 M1〜M7（ADR-080） | 2026-05-29 | #1146 #1148 #1150 |
| stale active-work クリーンアップ | 2026-05-29 | #1134 |
| Discord Webhook 分離 | 2026-05-29 | #1132 |
| PR固有 smoke テスト削除 | 2026-05-29 | #1133 |

---

## フォーマットルール

- `担当`: `Agent` / `PO待ち` / `CI待ち` / `Agent+PO` のいずれか
- `現在地`: コマンド・ファイル・PR で確認した事実。「〜のはず」は禁止
- `次の一手`: 具体的なアクション（「進める」は不可）
- `根拠`: ファイルパス / PR番号 / ADR番号 / コマンド結果
- `更新日`: YYYY-MM-DD 形式

完了したタスクは「完了（直近）」テーブルに移動する。30日超過行は削除可。

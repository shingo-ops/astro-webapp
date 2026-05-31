# Tasks

タスク台帳の正本。セッション開始時に必ず読むこと（`AGENTS.md §引き継ぎルール` 参照）。

---

## 進行中

| タスク | 担当 | 現在地 | 次の一手 | 根拠 | 更新日 |
|------|------|------|---------|-----|------|
| 複数エージェント並行開発の標準化（ADR-086） | Agent | ADR-086 作成済み、`docs/PARALLEL_TERMINAL_GUIDE.md` の worktree-first 化完了、`evidence-registry.md` に実行証跡追加済み。Reviewer re-review は no findings | PR を作成して CI / merge SHA を取得し、必要なら main 反映まで進める | `docs/adr/ADR-086-parallel-development-standardization.md` / `docs/PARALLEL_TERMINAL_GUIDE.md` / `docs/ai-agents/evidence-registry.md` / `bash scripts/check-task-state.sh` / `bash scripts/check-active-work-format.sh` 確認済み | 2026-05-31 |
| Generator executor フォールバック（ADR-082） | Agent | claude-pipeline.yml 実装済み・ADR-082 作成済み・AGENTS.md 反映済み | PR 作成 → develop マージ | .github/workflows/claude-pipeline.yml ローカル変更済み / ADR-082 作成済み / EV-20260530-001 記録済み | 2026-05-30 |
| Claude Code KPI / Grafana 基盤 | Agent | backend の同時処理中リクエスト数 / SSE 接続数を `/metrics` と Grafana `backend-api-metrics` に追加し、さらに `monitoring-main` を総合通知 → 部門サマリー → 機能別詳細の階層ポータルへ再設計、色基準（緑=OK / 黄=注意 / 赤=異常）と repo反映 vs 実機反映の区別も明文化済み | Prometheus alert の warning line を実測値に合わせて微調整し、KPI 正本 `docs/ai-agents/kpi.md` の collector 設計へ反映する | `backend/app/metrics.py` / `backend/app/services/sse_pubsub.py` / `monitoring/grafana/provisioning/dashboards/json/backend-metrics.json` / `monitoring/grafana/provisioning/dashboards/json/monitoring-main.json` / `monitoring/prometheus/alert_rules.yml` / `docs/INCIDENT_RESPONSE.md` / `docs/runbooks/monitoring-vps-migration.md` 確認済み | 2026-05-31 |
| 監視VPS移行 M8（ADR-080） | PO待ち | M7完了・M8未着手。ADR-081 で監視VPS 受信経路と backend worker 方針を最終確定済み | PO確認の上、Sakura パケットフィルタ反映 → app VPS から 3000/3001/9090 疎通確認 → 1週間運用確認後にアプリVPSの旧監視Dockerボリューム削除（prometheus_data/grafana_data/loki_data） | docs/runbooks/monitoring-vps-migration.md / docs/adr/ADR-081-monitoring-vps-final-operational-design.md | 2026-05-30 |
| VPS runner登録（ADR-078） | Agent（2026-06-15予定） | 未着手 | 予定日に `docs/runbooks/vps-runner-setup.md` に従い実行 | memory/project_vps_runner_plan.md | 2026-05-29 |
| Meta App Review 申請 | PO待ち | ドキュメント整備済み・動画未撮影 | PO が申請動画を撮影 → Agent がレビュー申請書類を提出 | memory/project_meta_app_review_progress.md | 2026-05-29 |
| discord-gateway live受信の LLM 解析 env 注入（Issue #1154） | PO待ち | gateway は idle(bot token未設定)・DATABASE_URL/GEMINI_API_KEY 未注入を docker inspect で確認。live化した瞬間に DB接続失敗+LLM不発 | PO が live化判断 → compose の discord-gateway に DATABASE_URL/GEMINI_API_KEY 追加 + bot token 設定 + 実機確認 | Issue #1154 / docker-compose.yml | 2026-05-29 |
| 解析レビュー明細テーブルのヘッダー sticky 固定 | Agent | feature/morimoto/parse-review-sticky-header。受信本文を開いて明細行をスクロールしても列見出しが残るよう thead を sticky 化(.data-table の overflow:hidden を本テーブルのみ visible 上書き)。CSS only | Reviewer APPROVE で develop merge | frontend ParseReviewPage.css | 2026-05-30 |
| (follow-up) ParseReviewPage の Phase A 在庫スキップ警告コードの撤去検討 | Agent | Option Z で Discord 承認が在庫を触らなくなり phaseAWarning が発火しない dead code 化。害は無いが整理候補 | 低優先。次の在庫系PRに同梱可 | frontend ParseReviewPage.tsx (phaseWarning) | 2026-05-30 |

---

## 完了（直近）

| タスク | 完了日 | PR |
|------|------|---|
| QAチェックシート GitHub Pages 自動公開 + bootstrap publish（/qa/ 最新化） | 2026-05-30 | #1190 |
| release develop → main（AEON operation guide / ADR index sync / main back-merge 反映） | 2026-05-30 | #1178 |
| 在庫表「追加」(廃番トグル誤表記)ボタン撤去 + 誤archive3商品復元 | 2026-05-30 | #1187 |
| QAチェックシート I-03(AND/OR) を見積検索Fセクションへ移動 + 全URL監査(古いリンク0) | 2026-05-30 | #1188 |
| QAチェックシート更新（在庫新仕様反映: Option Z/18h失効/単位/F11-10,11追加） | 2026-05-30 | #1180 |
| 在庫オファー lifecycle（単位 unit 永続化 migration084 + 18時間自動失効 Celery purge） | 2026-05-30 | #1179 |
| 解析レビュー表 QA修正（メモ来歴削除/単価整数/差分数量列削除/単位列追加/列幅+承認Option Z） | 2026-05-30 | #1177 |
| AEON operation guide canonicalization | 2026-05-30 | docs/ai-agents/aeon-operation.md |
| AEON ディスパッチャ smoke validation | 2026-05-30 | /tmp/aeon-delivery-20260530-052601.log |
| リリース develop → main | 2026-05-29 | #1135 |
| 監視VPS移行 M1〜M7（ADR-080） | 2026-05-29 | #1146 #1148 #1150 |
| Agent pipeline redefinition / runtime sync | 2026-05-29 | #1158 |
| stale active-work クリーンアップ | 2026-05-29 | #1134 |
| Discord Webhook 分離 | 2026-05-29 | #1132 |
| PR固有 smoke テスト削除 | 2026-05-29 | #1133 |
| QA修正バッチ(Discord取込原文化/SM-4解析行/在庫0行濃淡/GEMINI passthrough) | 2026-05-29 | #1152 |
| check:new-tokens を release PR(develop→main)で skip | 2026-05-29 | #1159 |
| QA修正(#1152)の本番反映 (release develop→main → deploy success → backend に GEMINI_API_KEY 到達を docker inspect で確認) | 2026-05-29 | #1135 |

---

## フォーマットルール

- `担当`: `Agent` / `PO待ち` / `CI待ち` / `Agent+PO` のいずれか
- `現在地`: コマンド・ファイル・PR で確認した事実。「〜のはず」は禁止
- `次の一手`: 具体的なアクション（「進める」は不可）
- `根拠`: ファイルパス / PR番号 / ADR番号 / コマンド結果
- `更新日`: YYYY-MM-DD 形式

完了したタスクは「完了（直近）」テーブルに移動する。30日超過行は削除可。

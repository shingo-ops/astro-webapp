# Tasks

タスク台帳の正本。セッション開始時に必ず読むこと（`AGENTS.md §引き継ぎルール` 参照）。

---

## 進行中

| タスク | 担当 | 現在地 | 次の一手 | 根拠 | 更新日 |
|------|------|------|---------|-----|------|
| 監視VPS移行 M8（ADR-080） | PO待ち | M7完了・M8未着手（1週間運用確認後に実施） | PO確認の上、アプリVPSの旧監視Dockerボリューム削除（prometheus_data/grafana_data/loki_data）→ `docs/runbooks/monitoring-vps-migration.md` Sprint M8 参照 | docs/runbooks/monitoring-vps-migration.md | 2026-05-29 |
| VPS runner登録（ADR-078） | Agent（2026-06-15予定） | 未着手 | 予定日に `docs/runbooks/vps-runner-setup.md` に従い実行 | memory/project_vps_runner_plan.md | 2026-05-29 |
| Meta App Review 申請 | PO待ち | ドキュメント整備済み・動画未撮影 | PO が申請動画を撮影 → Agent がレビュー申請書類を提出 | memory/project_meta_app_review_progress.md | 2026-05-29 |
| QA修正(#1152)の本番反映 = release #1135 (develop→main) | PO待ち | #1135 は #1152(GEMINI passthrough/Discord取込/在庫0行)等を含む。design-review-gate(#1137)赤 + main BEHIND(back-merge要)を gh pr checks で確認 | しんごさんが #1135 をマージ(Create a merge commit・squash禁止)→ deploy で本番 backend に GEMINI_API_KEY が反映される | PR #1135 / docker-compose.yml | 2026-05-29 |
| discord-gateway live受信の LLM 解析 env 注入（Issue #1154） | PO待ち | gateway は idle(bot token未設定)・DATABASE_URL/GEMINI_API_KEY 未注入を docker inspect で確認。live化した瞬間に DB接続失敗+LLM不発 | PO が live化判断 → compose の discord-gateway に DATABASE_URL/GEMINI_API_KEY 追加 + bot token 設定 + 実機確認 | Issue #1154 / docker-compose.yml | 2026-05-29 |

---

## 完了（直近）

| タスク | 完了日 | PR |
|------|------|---|
| 監視VPS移行 M1〜M7（ADR-080） | 2026-05-29 | #1146 #1148 #1150 |
| Agent pipeline redefinition / runtime sync | 2026-05-29 | - |
| stale active-work クリーンアップ | 2026-05-29 | #1134 |
| Discord Webhook 分離 | 2026-05-29 | #1132 |
| PR固有 smoke テスト削除 | 2026-05-29 | #1133 |
| QA修正バッチ(Discord取込原文化/SM-4解析行/在庫0行濃淡/GEMINI passthrough) | 2026-05-29 | #1152 |
| check:new-tokens を release PR(develop→main)で skip | 2026-05-29 | #1159 |

---

## フォーマットルール

- `担当`: `Agent` / `PO待ち` / `CI待ち` / `Agent+PO` のいずれか
- `現在地`: コマンド・ファイル・PR で確認した事実。「〜のはず」は禁止
- `次の一手`: 具体的なアクション（「進める」は不可）
- `根拠`: ファイルパス / PR番号 / ADR番号 / コマンド結果
- `更新日`: YYYY-MM-DD 形式

完了したタスクは「完了（直近）」テーブルに移動する。30日超過行は削除可。

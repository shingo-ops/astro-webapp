# CLAUDE.md

このファイルは **チーム共通の真実** のみを書く。個人の好み（口調・通知・キーバインド等）は各自の `~/.claude/CLAUDE.md` に置くこと。Claude Code の初期セットアップは `docs/onboarding/claude-code.md` を参照。

---

## プロジェクト前提

### 登場人物
- **しんごさん（GitHub: `shingo-ops`）** — プロダクトオーナー、運用、本番アクセス権限保持、ADR 起案
- **Hikky-dev** — Claude Code 利用の開発担当（設計・実装・PR 起票）

### 事業ドメイン
- **Jarvis CRM / salesanchor** — B2B SaaS CRM/ERP（HIGH LIFE JPN / Treasure Island JP）
- ターゲット: 日本の越境 EC 事業者
- 本番 URL（正本は `README.md`）:
  - App: https://app.salesanchor.jp/
  - API: https://api.salesanchor.jp/
  - LP: https://salesanchor.jp/
- Legacy ドメイン: https://jarvis-claude.uk/（並行稼働、新ドメイン安定後に廃止予定）
- **旧ドメインの独断削除禁止、必ず PO 確認**

### スタック
- Backend: Python 3.12 / FastAPI / SQLAlchemy 2.0 + asyncpg
- Frontend: React 18 + TypeScript + Vite
- LP: Astro
- DB: PostgreSQL 16（マルチテナント・スキーマ分離設計）
- Infra: Docker Compose / さくらVPS (49.212.137.46 / Ubuntu 24.04) / GitHub Actions

### マルチテナント運用
- 本番テナントは `tenant_code=highlife-jpn`（schema: `tenant_004`）
- 既定値 `test-corp` は空テナントなので、移行 / バッチ実行時は **`TENANT_CODE=highlife-jpn` を明示**
  - `gh workflow run run-*-migration.yml -f tenant_code=highlife-jpn`
  - `docker exec -e TENANT_CODE=highlife-jpn ...`

### VPS コンテナの落とし穴（過去事故あり）
- `/app` 配下は appuser 権限で **書込不可** → スクリプトの出力先は `/tmp` を既定にする
- `/tmp` は tmpfs マウント。`docker compose cp backend:/tmp/...` は **使えない**（`Could not find the file`）
- ホストへの取り出しは `docker compose exec -T backend cat /tmp/xxx > host_file` 一択
- コンテナ再起動で `/tmp` の中身は消える

### 仕様書の正本（2026-04-22 引き継ぎ）

以下 3 冊は **PO 配布の docx ファイル** で、リポジトリには含まれない（個人情報・機密設計を含むため）。新規参画時は **PO（しんごさん）に共有依頼** すること。

1. `jarvis_crm_system_overview.docx` — 全体俯瞰
2. `jarvis_crm_customer_master_migration_design.docx` — 顧客マスタ
3. `jarvis_crm_staff_roles_bots_design.docx` — 担当者・権限・bot

古い設計書（`CRM_引き継ぎレポート.docx`、`Jarvis_CRM_開発仕様書.docx`、進捗確認シート、フェーズ1セキュリティ基盤ガイド等）と齟齬する場合は **最新仕様を優先**、大きな判断は PO 確認。

### 設計判断は ADR 化
- 仕様変更・スキーマ判断・運用ルールは `docs/adr/ADR-NNN-*.md` で起案
- ADR ドリブンの実装は `claude-pipeline.yml` で発火（本ファイル末尾「実装フロー」参照）
- メモリやチャット履歴を「決定の根拠」として使わない

### 不可逆操作は必ず PO 確認
以下は事前に明示確認を取る:
- DROP TABLE / 大量 DELETE
- `rm -rf` / `git reset --hard`
- `git push --force`（特に `main` / `develop`）
- 本番 Docker volume 削除
- secrets / credentials の変更
- Cloudflare / Firebase Console 等の外部 GUI 操作

---

## ブランチ運用ルール

- 新しい機能についての作業を始める前に必ず `develop` から `feature/morimoto/` ブランチを作成すること
- ブランチ名は `feature/morimoto/作業内容を英語で簡潔に` とすること
- 直接 `develop` や `main` にはコミットしないこと
- feature ブランチの作業が完了したら、必要に応じて `gh pr create` でPRを作成し、レビュー後に `develop` へマージする

### develop → main も PR 経由（必須）

- **develop → main も必ず PR 経由でマージ**する（直 push 禁止）
- 私（Claude）の作業: `gh pr create --base main --head develop` で PR を作成、しんごさんがマージ
- main の Branch Protection (Ruleset) で物理的に強制（`docs/BRANCH_PROTECTION_SETUP.md` 参照）
- 緊急時は admin (しんごさん) のみ bypass 可、bypass 使用は同 doc の §4 に記録すること

## Git運用ルール

### 作業開始時
- 必ず `git status` で現在の状態を確認してから作業を始める
- 作業前のブランチが正しいか確認する

### コミットの基本方針
- コミットメッセージは日本語でOK
- 1機能1コミットを意識すること
- 動かない状態でもコミットしてよい（WIPコミット）
- 完璧を待たず、とにかくこまめに保存する
- 目安：**30分に1回以上、または意味のある変化があるたび**

### 自動コミットすべきタイミング（必ず守ること）
- ファイルを新規作成したとき
- 1つの関数・コンポーネントの実装が完了したとき
- テストが通ったとき
- 大きなリファクタリングの前（変更前の状態を保存）
- 「次の作業に移る」と判断したとき

### WIPコミットの書き方
```
git add -A && git commit -m "WIP: 〇〇の実装途中"
git add -A && git commit -m "WIP: △△まで完了、□□が未着手"
```

### 作業終了・中断時（必須）
作業を止めるときは必ず以下を実行：
```
git add -A && git commit -m "WIP: 中断時点のスナップショット"
git push origin HEAD
```
pushまで完了して初めて作業終了とすること。

---

## ワークフロー設計

### 1. Planモードを基本とする
- 3ステップ以上 or アーキテクチャに関わるタスクは必ずPlanモードで開始する
- 途中でうまくいかなくなったら、無理に進めずすぐに立ち止まって再計画する
- 構築だけでなく、検証ステップにもPlanモードを使う
- 曖昧さを減らすため、実装前に詳細な仕様を書く

### 2. サブエージェント戦略
- メインのコンテキストウィンドウをクリーンに保つためにサブエージェントを積極的に活用する
- リサーチ・調査・並列分析はサブエージェントに任せる
- 複雑な問題には、サブエージェントを使ってより多くの計算リソースを投入する
- 集中して実行するために、サブエージェント1つにつき1タスクを割り当てる

### 3. 自己改善ループ
- ユーザーから修正を受けたら必ず `tasks/lessons.md` にそのパターンを記録する
- 同じミスを繰り返さないように、自分へのルールを書く
- ミス率が下がるまで、ルールを徹底的に改善し続ける
- セッション開始時に、そのプロジェクトに関連するlessonsをレビューする

### 4. 完了前に必ず検証する
- 動作を証明できるまで、タスクを完了とマークしない
- 必要に応じてmainブランチと自分の変更の差分を確認する
- 「スタッフエンジニアはこれを承認するか？」と自問する
- テストを実行し、ログを確認し、正しく動作することを示す

### 5. エレガントさを追求する（バランスよく）
- 重要な変更をする前に「もっとエレガントな方法はないか？」と一度立ち止まる
- ハック的な修正に感じたら「今知っていることをすべて踏まえて、エレガントな解決策を実装する」
- シンプルで明白な修正にはこのプロセスをスキップする（過剰設計しない）
- 提示する前に自分の作業に自問自答する

### 6. 自律的なバグ修正
- バグレポートを受けたら、手取り足取り教えてもらわずにそのまま修正する
- ログ・エラー・失敗しているテストを見て、自分で解決する
- ユーザーのコンテキスト切り替えをゼロにする
- 言われなくても、失敗しているCIテストを修正しに行く

---

## タスク管理

1. **まず計画を立てる**：チェック可能な項目として `tasks/todo.md` に計画を書く
2. **計画を確認する**：実装を開始する前に確認する
3. **進捗を記録する**：完了した項目を随時マークしていく
4. **変更を説明する**：各ステップで高レベルのサマリーを提供する
5. **結果をドキュメント化する**：`tasks/todo.md` にレビューセクションを追加する
6. **学びを記録する**：修正を受けた後に `tasks/lessons.md` を更新する

---

## ドキュメント作成ルール

- 素人でもわかるように、具体例やたとえ話を必ず交えて説明する
- 構成図・フロー図・テーブル図などの図解を積極的に使う
- 専門用語を使う場合は、初出時に必ず平易な言葉で補足する
- 「何をするか」だけでなく「なぜ必要か」「やらないとどうなるか」を明記する

---

## コア原則

- **シンプル第一**：すべての変更をできる限りシンプルにする。影響するコードを最小限にする。
- **手を抜かない**：根本原因を見つける。一時的な修正は避ける。シニアエンジニアの水準を保つ。
- **影響を最小化する**：変更は必要な箇所のみにとどめる。バグを新たに引き込まない。

---

## データ手動 DB INSERT の原則禁止（ADR-025）

外部 SaaS / OAuth 等の連携機能において、**正規フロー（OAuth コールバック・API 経由の作成エンドポイント等）を経由しない手動 DB INSERT は原則禁止**する。

### 背景

ADR-024 で発覚した Meta 連携の不整合は、`tenant_meta_config` レコードを **OAuth フロー外で直接 INSERT した**ことが直接原因だった。結果として「DB 上は接続済み・Meta 側は subscribed_apps に未登録」という静かな不整合が発生し、Meta App Review 撮影直前まで気付けなかった。

### 禁止対象

以下を **正規フロー外で** 手動投入することを禁止する：

- `tenant_meta_config` / `tenant_*_config` 系（連携プラットフォーム設定）
- `*_token_encrypted` / 暗号化済シークレットを含む全カラム
- `subscribed_*` / OAuth scope / Webhook subscription を表すカラム
- 外部システムとの一意ID紐付け（`external_id`, `meta_page_id` 等）
- 監査必須レコード（`audit_logs`, `data_deletion_logs` 等）

### 例外条件（すべてを満たすときのみ許可）

1. 障害復旧・本番調査など、正規フローを経由できない明確な理由がある
2. PO（しんごさん）に書面（GitHub Issue / PR 本文 / ADR）で事前承認を得ている
3. 投入と同時に `audit_logs` へ `manual_db_insert` action を記録し、actor・理由・影響範囲を残す
4. **検証スクリプト**（または同等の手段）で DB 状態と外部システム状態の整合性をチェックし、不整合があれば即時是正する
5. PR / 実行ログで投入クエリ・件数・対象テナントが第三者から再現可能

### How to apply

- 新機能を実装するときに「テスト用に DB に直接入れて済ませる」誘惑が出たら、まず正規フローを実装する
- 既存の手動投入レコードを見つけたら、`audit_logs` の `meta_page_connected` 等のフローイベント有無を必ず確認する
- 連携系の不整合報告（"接続済みなのに動かない"）を受けた場合、最初に DB 直 INSERT の痕跡を疑う

---

## Phase / Sprint 完了判定基準（ADR-025）

外部 API 連携・OAuth・Webhook 等を含む Phase / Sprint は、以下 3 点が **すべて満たされた状態** をもって完了と判定する。コード実装と CI 緑だけでは完了としない。

### 1. 実機 E2E テスト（必須）

- 本番に近い環境（最低でも本番テナント `tenant_004 / highlife-jpn` を使ったステージング相当）で、ユーザー操作を実機に近い形で再現する
- Meta / Discord / 決済等の外部 API が絡む場合は、**実 API 呼び出しで往復が成立する**ことを確認する（モックのみの単体テスト緑だけでは不可）
- 「Meta Business Suite には届くが Sales Anchor Inbox には届かない」（ADR-024）のような **片側で完結する成功** を完了と誤認しない

### 2. 検証スクリプトの並行実装

- 「正常な状態」を機械的に確認できるスクリプト（`verify_*` 等）を機能本体と **同一 Sprint 内** で実装する
- Cron / Celery beat / GitHub Actions schedule に組み込み、状態 drift を自動検知できる構造にする
- 検証失敗時の出力（audit_log の専用 action や、CLI 終了コード）を明示する

### 3. 監視・アラート機構の整備

- 現状は Sentry / Slack 通知の本格運用が未整備のため、最低限 `audit_logs` の専用 action（例: `meta_subscription_drift_detected`）を発行し、運用者が `psql` 一発で検知できる状態にする
- Phase 2 で Sentry / Slack / Discord 通知を本格化する際は、ここに既に存在する audit action を hook できる設計にしておく

### How to apply

- Sprint 着手時に「3 点セットのうちどれが既存・どれが新規実装か」をチェックリスト化し、PR の説明文に明記する
- 「機能本体だけ動けば Sprint 完了」と判断しそうになったら立ち止まる
- ADR / Sprint Spec に検証・監視項目が書かれていなくても、**自律的に Scope に含める**（"ADR に書いてないから実装しない" は ADR-025 で明確に禁止された判断パターン）

---

## 新機能実装時の 3 点セット要件（ADR-025）

外部システムと状態を共有する新機能（OAuth 連携 / Webhook / Cron による外部 API 呼び出し等）を実装する際は、以下 3 点を **1 つのセット** として実装する。

| # | 要素 | 目的 | 実装場所の例 |
|---|---|---|---|
| 1 | **機能本体** | ユーザー価値の提供 | `backend/app/routers/*`, `frontend/src/pages/*` |
| 2 | **状態検証スクリプト** | DB 状態と外部システム状態の整合性チェック | `backend/app/tasks/verify_*.py`, `scripts/verify_*.py` |
| 3 | **監視・通知** | 異常の早期発見 | `audit_logs` への専用 action 追加 + 将来の Sentry / Slack 通知の hook ポイント |

### 適用条件

- 「外部システムの状態」を DB に保存または参照する全機能（Meta / Discord / 決済 API / メール送信 SaaS / 認証基盤など）
- 単純な内部 CRUD（顧客テーブルへの直接保存等）は対象外
- 判断に迷ったら「外部連携の片側で更新が起きたら気付けるか？」を自問する。気付けないなら 3 点セット要件の対象

### Why

- 機能本体だけでは「DB 上は成功・外部システム側は失敗」という不整合が検出されない（ADR-024 の root cause）
- 検証スクリプトだけでは異常が記録されても通知が届かない
- 監視だけでは何を見ればよいか分からない
- 3 点が揃って初めて「機能が動いていることを継続的に証明できる」状態になる

### How to apply

- ADR に明記されていなくても、外部連携を伴う実装では **自律的に 3 点セットを Scope に含める**
- Sprint Spec / PR 本文に 3 点それぞれの実装場所をリンクで示す
- 「Phase 2 に持ち越し」が許されるのは **PO が書面で明示的に承認した場合のみ**

> 詳細な背景は `docs/adr/ADR-025_meta_integration_operational_hardening.md` を参照。

---
## 実装フロー（ADR-012: What/How 役割分担モデル）

> ADR-012 により正式採択。旧 PROPOSAL-001 暫定運用セクションを置き換える。

### 役割分担

| 担当 | 役割 |
|------|------|
| **Shingo（PO）** | What の定義。「何を実現したいか」「なぜ必要か」「ユーザー価値」「事業判断」「優先順位」 |
| **Web Claude（claude.ai）** | 壁打ち相手。アイディアを技術的に明確な要求（ADR）に翻訳する。事業上の見落とし・ユーザー観点を指摘 |
| **パートナー Claude Code（Hikky-dev / GitHub Actions）** | How の判断と実装。技術選択・セキュリティ・テスト・既存コードとの統合をすべて自律的に決定 |

### ADR の記述ルール

ADR に**書く**もの: What（何を実現したいか）、Why（事業価値）、Scope 外（明示的除外）、事業上の制約

ADR に**書かない**もの: 詳細な実装手順（How）、Invariants 網羅リスト、細かい技術仕様

### ワークフロー（claude-pipeline.yml 起動時）

1. Shingo がチャットで「○○を実現したい」と話す
2. Web Claude が ADR（What/Why/Scope）に落とす
3. Shingo が ADR を develop に push（Terminal Claude Code 経由）
4. パートナー Claude Code が claude-pipeline.yml により自動起動し、実装 + PR 作成
5. CI 緑なら Shingo が PR 本文とスコープを確認してマージ

### マージ判断の基準（Shingo 向け）

- PR タイトルと本文を読んで「これは頼んだことか？」を確認
- CI が緑か確認
- 技術的な正しさは CI とパートナーの判断に委ねる（Shingo が技術仕様の細部を確認しなくてよい）

> 詳細は `docs/adr/ADR-012-what-how-separation.md` を参照。

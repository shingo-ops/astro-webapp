# CLAUDE.md

このファイルは **チーム共通の真実** のみを書く。個人の好み（口調・通知・キーバインド等）は各自の `~/.claude/CLAUDE.md` に置くこと。Claude Code の初期セットアップは `docs/onboarding/claude-code.md` を参照。

---

## プロジェクト前提

### 登場人物
- **しんごさん（GitHub: `shingo-ops`）** — プロダクトオーナー、運用、本番アクセス権限保持、ADR 起案
- **Hikky-dev** — Claude Code 利用の開発担当（設計・実装・PR 起票）

### 事業ドメイン
- **Jarvis CRM** — B2B SaaS CRM/ERP（HIGH LIFE JPN / Treasure Island JP）
- ターゲット: 日本の越境 EC 事業者
- 本番 URL: https://jarvis-claude.uk
- 旧ドメインの扱いは `docs/DOMAIN_POLICY.md`（独断削除禁止）

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
1. `jarvis_crm_system_overview.docx` — 全体俯瞰
2. `jarvis_crm_customer_master_migration_design.docx` — 顧客マスタ
3. `jarvis_crm_staff_roles_bots_design.docx` — 担当者・権限・bot

古い設計書と齟齬する場合は **最新仕様を優先**、大きな判断は PO 確認。

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
## 実装フロー（PROPOSAL-001暫定運用、2026-05-06〜）

claude-pipeline.yml が起動された場合、本Claude Codeは以下の手順で実装する：

1. ADR本文を読み取り、Acceptance Criteria（AC-XXX）を抽出する
2. 既存コードベースとの整合性を確認する
3. feature/shingo/adr-NNN-impl ブランチで実装する（pipeline側で自動作成）
4. すべてのACを満たすことを確認する
5. PRを作成（auto-mergeしない）
6. ADR外の変更（リファクタリング等）はスコープに含めない
7. 設計意図が不明な場合は questions/QXX.md で停止して相談する

このフローはPROPOSAL-001合意後にADR-012として正式化される予定。
それまでは暫定運用として、Hikky-devへ朝イチで報告。

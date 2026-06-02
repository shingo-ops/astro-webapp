# ADR-092: deploy.yml 多重実行防止（concurrency 制御 + コンテナ pre-cleanup）

## Status
Accepted

しんごさん（PO）が Reviewer(APPROVE) + Governance(BLOCK→実装で解除) エージェントの事実ベース検証を経て確定（2026-06-02）。

## Date

2026-06-02（起案: Hikky-dev）

## Context（背景）

`develop → main` リリース PR が短時間に連続マージされると、GitHub Actions が
`deploy.yml` を**並行実行**する。`deploy.yml` には `concurrency:` キーが無かったため
（893 行中 0 件）、複数の deploy ジョブが同時に `docker compose up` を実行し、
先行ジョブがコンテナを停止中のタイミングで後続ジョブが同名コンテナを作成しようとして
`Conflict. The container name "/astro-webapp-backend-1" is already in use`
（+ `Error while Stopping`）エラーが発生。backend が "Created"（未起動）のまま停止し、
nginx が **502 Bad Gateway** を返した。

実際に **2026-06-02 10:53〜11:04 JST**、リリース PR **#1390 / #1395 / #1396** の
9 分間連続マージで発生（失敗ログは `gh run view 26793850666` で確認可能）。
応急対応として作成済みコンテナを起動し直し（`docker compose start` / `up -d --force-recreate`）
本番を復旧した。

## Decision（決定）

### 1. GitHub Actions `concurrency` による直列化（本 ADR の主目的）

```yaml
concurrency:
  group: deploy-production
  cancel-in-progress: false
```

- 連続リリース時も deploy ジョブを **同一グループで直列化**し、並行実行による
  コンテナ名衝突を構造的に防ぐ。
- `cancel-in-progress: false` を選択した理由: `true` にすると migration 実行中に
  後続ジョブが先行ジョブをキャンセルし、DB が中途半端な状態になる危険がある。
  `false` で後続をキュー待ちにする（通常数分以内に順次実行）。

### 2. `docker compose up` 前のコンテナ pre-cleanup

`docker compose up` の前に、graceful stop に失敗した / ハッシュ付きプロジェクト名の
残留コンテナ（前回デプロイの失敗残骸）を `docker rm -f` で明示的に削除する。
`docker compose up --remove-orphans` ではプロジェクト名が異なる残留コンテナを
削除できないため直接対処する。postgres / redis / nginx / certbot は
filter 名が一致しないため削除対象外。

**実装状況**: この pre-cleanup は **PR #1402（develop merged 済）で既に実装済み**で、
しんごさん当初案の backend + frontend を上回り、**全 app 系
（backend / frontend / celery-worker / celery-beat / discord-gateway）**に拡張し、
かつ `docker compose build` 完了後・`up -d` 直前に配置してダウンタイムを最小化している。
discord-gateway を含めることで、デプロイ時の gateway 重複起動による Discord 再接続storm
（→ Bot Token 自動リセット、別途 #1402 で対処）も防ぐ。本 ADR の PR では
重複・先祖返りを避けるため pre-cleanup には手を加えず、**1 の concurrency 追加のみ**を行う。

## Consequences（影響）

- 連続リリース時は後続デプロイがキュー待ちになる（通常数分以内）。
- DB 不整合・コンテナ名衝突による 502 が**構造的に防止**される。
- 2026-05-30 障害対策「build 先行によるダウンタイム最小化」は維持される（`down` を使わない）。

## 参照

- 失敗ログ: `gh run view 26793850666`
- PR #1402（pre-cleanup を全 app 系に拡張 + discord-gateway 致命時クールダウン）
- ADR-082（フロントのみデプロイ時の migration skip）
- 2026-06-02 障害記録: discord-gateway Bot Token リセット（短時間 >1000 接続検知による Discord 側自動リセット）

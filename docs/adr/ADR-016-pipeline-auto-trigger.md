# ADR-016: ADR push による実装パイプライン自動起動

## ステータス
Proposed — 2026-05-07

## What

`docs/adr/` 配下に `.md` ファイルが push されたとき、
`claude-pipeline.yml` が自動的に起動して実装を開始する仕組みを構築したい。

現在は `workflow_dispatch` (手動起動) のみ対応しており、
Shingo が ADR を push した後にパートナーが手動でパイプラインを起動する必要がある。

**実現したいフロー:**

```
Shingo が docs/adr/ADR-XXX.md を develop に push
   ↓ 自動で
claude-pipeline.yml が起動
   ↓
パートナー Claude Code が ADR を読んで実装
   ↓
PR が自動で作成される
```

## Why

- Shingo はパイプラインの手動起動という操作を知らなかった
- ADR を push すれば自動で実装が始まるという認識でいたが、
  実際は手動トリガーが必要だった
- この齟齬を解消して、Shingo が ADR を push するだけで
  実装が始まる状態にしたい
- 認知負荷を下げることで、設計に集中できる

## Scope 外

- 実装の詳細 (paths トリガーの設定方法・concurrency の設計・
  push 時の ADR ファイル自動検出方法) は
  パートナー Claude Code が判断する
- 自動起動後の実装フロー自体は変更しない
- PR の作成・CI の実行フローは変更しない

## 事業上の制約

- ADR-010 (ブランチ保護) との整合性は維持すること
- develop ブランチへの push をトリガーにする
  (main への直 push は ADR-010 で禁止されているため)
- 既存の `workflow_dispatch` による手動起動も
  引き続き使えるようにしておく (並行運用)

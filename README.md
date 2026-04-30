# Sales Anchor

Multi-Channel Customer Relationship Management (CRM) SaaS Platform for B2B Trading Card Game Exporters

## Overview

Sales Anchor は、TCG（Trading Card Game）輸出業者向けの統合 CRM SaaS。Messenger / Instagram / WhatsApp / LINE / Discord / Telegram / メール 等の複数チャネルを 1 画面で受信・返信し、TCG 商品マスタ（カード番号・拡張・レアリティ・言語・JAN）の構造化、見積→請求→配送の自動化、AI 分析を提供。

**運営**: HIGH LIFE JPN（代表 Shingo Tanizawa）

## Tech Stack

- **Frontend**: React 19 + TypeScript + Vite
- **Backend**: FastAPI + Python 3.12 + Celery + Redis
- **Database**: PostgreSQL 16 (Row Level Security でマルチテナント分離)
- **LP / Static**: Astro 4 + Tailwind 3
- **Infrastructure**: Docker Compose + Nginx + Let's Encrypt SSL
- **Deployment**: GitHub Actions (Auto Deploy on `main` push)
- **Encryption**: Fernet (Page Access Token 等の機密情報)

## Domains

- **App**: https://app.salesanchor.jp/
- **API**: https://api.salesanchor.jp/
- **LP**: https://salesanchor.jp/
- **Legacy** (並行稼働、新ドメイン安定後に廃止予定): https://jarvis-claude.uk/

## Branch Strategy

- `main`: Production (auto-deploy via GitHub Actions)
- `develop`: Development integration
- `feature/morimoto/<topic>`: 機能開発ブランチ（必ず develop から派生）

## Phase 進捗（2026-04-30 時点）

- ✅ Phase 1-A: マルチテナント基盤（migration 003〜011、tenant 別 schema、permissions）
- ✅ Phase 1-B: 顧客マスタ刷新（companies + contacts 階層、connect channels 細粒度化）
- ✅ Phase 1-C: 商品マスタ MVP（TCG 11 列、削除 409 + アーカイブ）
- ✅ Phase 1-D: Meta Inbox UI（OAuth + Channels + Inbox 表示・送信 + Instagram + 撮影台本）
- 🔄 Phase 1-E: high 優先 follow-up（lifespan テスト / Human Agent Tag UI / PostgreSQL CI / 60 日 token リフレッシュ / Playwright E2E）
- ⏳ Phase 2: メッセージング送受信のリアルタイム化、添付ファイル、絵文字、テンプレート
- ⏳ Phase 3: Discord Gateway, Telegram, WhatsApp 統合
- ⏳ Phase 4-5: AI 分析（Claude / GPT-5）、本番運用準備

## Key Documents

- `docs/PHASE_1D_META_INBOX_OVERVIEW.md` — Phase 1-D 全体像、アーキテクチャ図、エンドポイント一覧
- `docs/PHASE_1D_RELEASE_NOTES.md` — Sprint 1-7 のリリースノート
- `docs/PHASE_1E_FOLLOW_UP_BACKLOG.md` — Phase 1-E follow-up 25 項目
- `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md` — Meta App Review 提出用撮影台本
- `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` — 撮影前チェックリスト
- `docs/USE_CASE_DESCRIPTIONS_v1.1_DRAFT.md` — Meta App Review 申請文書 v1.1 ドラフト
- `docs/ENVIRONMENT_VARIABLES.md` — 全環境変数の用途・取得方法
- `docs/data_deletion_callback_design.md` — Data Deletion Callback 設計書
- `docs/ADR-009_discord_gateway.md` — Discord Gateway ADR (Phase 3)

## Local Development

```bash
# 依存インストール
cd backend && pip install -r requirements.txt
cd ../frontend && npm install
cd ../lp && npm install

# 環境変数（backend/.env を作成、ENVIRONMENT_VARIABLES.md 参照）
cp .env.example .env
# METADATA_FERNET_KEY 等を設定

# Docker Compose で全部起動
docker compose up -d

# 個別開発
cd frontend && npm run dev    # http://localhost:5173
cd lp && npm run dev          # http://localhost:4321
cd backend && uvicorn app.main:app --reload --port 8000
```

## Tests

```bash
# Backend (pytest, SQLite default、PostgreSQL RLS は env で切替)
cd backend && pytest -q

# Frontend type check + build
cd frontend && npx tsc --noEmit && npx vite build

# E2E (Playwright、Phase 1-E F2-S3 で導入予定)
cd frontend && npm run test:e2e
```

## Deployment

`main` への push で GitHub Actions が自動デプロイ：
1. LP build (Astro) → rsync to VPS `/var/www/salesanchor/`
2. VPS 上で `git pull` + `docker compose up -d --build`
3. Migration 適用（idempotent）
4. Health check + コンテナ起動確認

詳細は `.github/workflows/deploy.yml` を参照。

## License & Contact

- **Operated by**: HIGH LIFE JPN
- **Representative**: Shingo Tanizawa
- **Contact**: support@salesanchor.jp
- **Privacy Policy**: https://salesanchor.jp/privacy
- **Terms of Service**: https://salesanchor.jp/terms
- **Data Deletion**: https://salesanchor.jp/data-deletion

---

© 2026 HIGH LIFE JPN — Sales Anchor

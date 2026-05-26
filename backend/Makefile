# backend/Makefile
# フロントエンドの npm run check:all に相当するバックエンド統合チェックコマンド。
# 初回セットアップ: pip install -r requirements-dev.txt

.PHONY: check lint lint-ci test

## CI 相当の全チェック（lint-ci + pytest）
check: lint-ci test

## 厳格 lint — 違反で非ゼロ終了（ローカル確認用）
lint:
	ruff check app/
	bandit -r app/ -lll
	mypy app/ --no-error-summary

## CI 相当 lint — --exit-zero で警告表示のみ（段階導入中）
## Phase 2 で ruff から順に --exit-zero を外してブロック化予定
lint-ci:
	ruff check app/ --exit-zero
	bandit -r app/ -lll --exit-zero
	mypy app/ --no-error-summary --exit-zero

## pytest（DB サービス必須: docker compose up -d postgres redis）
test:
	pytest -q --tb=short

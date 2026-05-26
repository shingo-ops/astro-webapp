# backend/Makefile
# フロントエンドの npm run check:all に相当するバックエンド統合チェックコマンド。
# 初回セットアップ: pip install -r requirements-dev.txt

.PHONY: check lint lint-ci fix-lint test

## CI 相当の全チェック（lint-ci + pytest）
check: lint-ci test

## 厳格 lint — 違反で非ゼロ終了（ローカル確認用）
lint:
	ruff check app/
	bandit -r app/ -lll
	mypy app/ --no-error-summary

## CI 相当 lint（bandit はブロック、ruff/mypy は段階導入中）
lint-ci:
	ruff check app/ --exit-zero
	bandit -r app/ -lll
	mypy app/ --no-error-summary || true

## ruff auto-fix — 既存 708 件の自動修正可能な違反を一括修正
## 実行後 git diff で変更確認 → git add -p でレビューしてコミット
## 完了後 lint-ci の ruff --exit-zero を削除してブロック化する
fix-lint:
	ruff check app/ --fix
	ruff check app/

## pytest（DB サービス必須: docker compose up -d postgres redis）
test:
	pytest -q --tb=short

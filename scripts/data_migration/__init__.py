"""Phase 1 再設計のデータ移行スクリプト群。

実行方法（VPS側、Docker コンテナ内）:
    docker compose exec backend python /app/scripts/data_migration/migrate_staff_from_sheet.py
    docker compose exec backend python /app/scripts/data_migration/migrate_customers_from_sheet.py

順序:
    1. scripts/migrate_phase1_redesign.py で migration 014〜022 を適用
    2. migrate_staff_from_sheet.py（staff テーブルが customers.sales_rep_id に先行）
    3. migrate_customers_from_sheet.py
    4. verify_*.py でデータ検証
"""

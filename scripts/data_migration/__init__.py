"""Phase 1 再設計のデータ移行スクリプト群。

実行方法（VPS側、Docker コンテナ内）:
    docker compose exec backend python /app/scripts/data_migration/migrate_staff_from_sheet.py

残存スクリプト (Step 5d 以降も使う可能性あり):
    - migrate_staff_from_sheet.py / verify_staff_migration.py
    - data_cleansing.py / analyze_company_names.py / export_dedup_review.py

archive 化（scripts/_archive/data_migration/、Phase 1-B-2 Step 5d / PR γ）:
    - migrate_customers_from_sheet.py / verify_customers_migration.py
    - migrate_companies_contacts_from_customers.py / verify_companies_contacts_migration.py
    - verify_downstream_fk_migration.py

archive されたスクリプトは customer_id 列・_customer_migration_map テーブルに依存しており、
migration 035/036 適用済みの本番では実行できません。過去の audit / 再現性確認用に保管。
"""

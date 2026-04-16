"""
app.services.tenant 内のヘルパー関数の単体テスト。

特に _split_sql_preserving_do_blocks は DO $$ ... END $$ 内の
セミコロンを保持する必要があり、ロジックを保証する。

変更履歴:
  2026-04-16: 初版作成（Phase 1レビュー指摘対応 L2）
"""

from app.services.tenant import _split_sql_preserving_do_blocks


class TestSplitSqlPreservingDoBlocks:
    def test_simple_statements(self):
        """通常のSQLはセミコロンで分割される"""
        sql = "CREATE TABLE foo (id INT); CREATE TABLE bar (id INT);"
        result = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
        assert len(result) == 2
        assert "foo" in result[0]
        assert "bar" in result[1]

    def test_single_statement_no_trailing_semicolon(self):
        """末尾セミコロンが無くても1文として扱える"""
        sql = "CREATE TABLE foo (id INT)"
        result = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
        assert len(result) == 1

    def test_do_block_preserves_internal_semicolons(self):
        """DO $$ ... END $$ 内部のセミコロンは分割されない"""
        sql = """
        DO $$
        BEGIN
            CREATE TABLE a (id INT);
            CREATE TABLE b (id INT);
        END $$;
        """
        result = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
        assert len(result) == 1, f"Expected 1 block, got {len(result)}: {result}"
        assert "CREATE TABLE a" in result[0]
        assert "CREATE TABLE b" in result[0]

    def test_mixed_do_block_and_regular(self):
        """通常文とDOブロックが混在しても正しく分割"""
        sql = """
        CREATE SEQUENCE seq1 START 1;
        DO $$
        BEGIN
            PERFORM 1;
            PERFORM 2;
        END $$;
        CREATE TABLE foo (id INT);
        """
        result = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
        assert len(result) == 3
        assert "SEQUENCE seq1" in result[0]
        assert "DO" in result[1] and "END" in result[1]
        assert "TABLE foo" in result[2]

    def test_empty_input(self):
        """空文字列は空リスト（strip後）"""
        result = [s.strip() for s in _split_sql_preserving_do_blocks("") if s.strip()]
        assert result == []

    def test_nested_do_blocks_not_supported_but_no_crash(self):
        """ネストDO（PostgreSQLでは無効だが）は最初のペアで閉じる"""
        # $$ が偶数回出現すれば分割は機能する
        sql = "DO $$ SELECT 1; $$; SELECT 2;"
        result = [s.strip() for s in _split_sql_preserving_do_blocks(sql) if s.strip()]
        assert len(result) == 2

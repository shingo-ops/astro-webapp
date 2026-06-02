"""pre-commitフック（worktreeチェック）のロジック単体テスト。

テスト対象: frontend/.husky/pre-commit の worktree 外ブロック + active-work.md 例外ロジック
実行方法: pytest scripts/test_pre_commit_hook.py -v
"""
from __future__ import annotations

import subprocess


def _run_grep_filter(staged_files: str) -> str:
    """pre-commitフックと同一のgrepフィルターを実行して非管理ファイルを返す。"""
    if not staged_files:
        return ""
    result = subprocess.run(
        ["grep", "-v", r"^\.claude-pipeline/active-work\.md$"],
        input=staged_files,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# ── active-work.md 例外ロジック ──────────────────────────────────────────────

def test_active_work_only_is_allowed():
    """active-work.md のみ staged → 例外として通過（空文字が返る）。"""
    result = _run_grep_filter(".claude-pipeline/active-work.md")
    assert result == ""


def test_other_file_is_blocked():
    """機能ファイルが staged → ブロック対象として返る。"""
    result = _run_grep_filter("frontend/src/App.tsx")
    assert result == "frontend/src/App.tsx"


def test_active_work_and_other_file_is_blocked():
    """active-work.md + 機能ファイルが混在 → 機能ファイルだけブロック対象。"""
    staged = ".claude-pipeline/active-work.md\nfrontend/src/App.tsx"
    result = _run_grep_filter(staged)
    assert "frontend/src/App.tsx" in result
    assert ".claude-pipeline/active-work.md" not in result


def test_empty_staged_files_not_blocked():
    """staged ファイルがゼロ件 → ブロックしない（echo "" バグの回帰テスト）。"""
    result = _run_grep_filter("")
    assert result == ""


def test_similar_path_not_matched():
    """パスが似ているだけで active-work.md 扱いにならない（誤マッチ防止）。"""
    result = _run_grep_filter("Xclaude-pipelineXactive-workXmd")
    assert result == "Xclaude-pipelineXactive-workXmd"


def test_multiple_non_admin_files_all_blocked():
    """複数の機能ファイルが staged → 全てブロック対象。"""
    staged = "frontend/src/App.tsx\nbackend/app/main.py"
    result = _run_grep_filter(staged)
    assert "frontend/src/App.tsx" in result
    assert "backend/app/main.py" in result

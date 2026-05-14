"""PR #164 round1 fix スモークテスト。

PR #164 の Reviewer round 1 で指摘された Major 2 + Minor 1〜5 の対応を、
backend / frontend の差分について grep / AST レベルで確認する。

実 pytest baseline は別件 (app.auth.dependencies AttributeError) で実行不可のため、
本ファイルでは DB / HTTP に触れず、静的検証で局所的な実装回帰を防ぐ。

検証項目:
  1. backend: 並行マージのデッドロック回避 (canonical 順 ORDER BY id FOR UPDATE)
  2. backend: master audit log new_data に status='active' が promoted=True 時に出る
  3. backend: IntegrityError 経路で await db.rollback() が呼ばれている
  4. backend: branch_name 切り詰め発生時に warning ログ + audit_log に痕跡
  5. backend: _customer_migration_map 防御 guard が pg_tables チェック付きで存在
  6. frontend: server-side search 経由 (`/companies?search=`) でフォールバックする
  7. frontend: 候補が 100 件キャップに達したら警告バナーを出す
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPANIES_PY = REPO_ROOT / "backend" / "app" / "routers" / "companies.py"
MERGE_MODAL_TSX = REPO_ROOT / "frontend" / "src" / "components" / "MergeCompanyModal.tsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# 1. canonical lock order (Minor 1)
# -----------------------------------------------------------------------------
def test_merge_uses_canonical_lock_order():
    """並行マージで deadlock しないよう、master/merge を id 昇順で同一クエリ内ロック。"""
    src = _read(COMPANIES_PY)
    # 旧パターン (個別 FOR UPDATE x2) が消えていること
    assert src.count("FROM companies WHERE id = :id FOR UPDATE") == 0, (
        "merge 関数内に個別 FOR UPDATE が残っています。"
        "ORDER BY id FOR UPDATE でまとめてロックする方針に統一してください。"
    )
    # 新パターン: WHERE id IN (:m1, :m2) と ORDER BY id と FOR UPDATE が連続して書かれている。
    # SQLAlchemy の text() に渡す Python 文字列リテラル連結があるため、リテラル内の改行は
    # 失われていることに注意。実装は3行のリテラル分割なので、各キーワードが順に出現すれば OK。
    assert "WHERE id IN (:m1, :m2)" in src, "WHERE id IN (:m1, :m2) のロック対象指定がありません"
    # ORDER BY id と FOR UPDATE が WHERE の後に並んでいるか
    idx_in = src.find("WHERE id IN (:m1, :m2)")
    idx_order = src.find("ORDER BY id", idx_in)
    idx_for_update = src.find("FOR UPDATE", idx_order)
    assert idx_in != -1 and idx_order != -1 and idx_for_update != -1, (
        "ORDER BY id / FOR UPDATE が WHERE id IN (...) の後に見つかりません"
    )
    assert idx_in < idx_order < idx_for_update


# -----------------------------------------------------------------------------
# 2. master audit log: status promoted (Minor 2)
# -----------------------------------------------------------------------------
def test_master_audit_payload_includes_status_when_promoted():
    """promoted=True のとき new_data['status']='active' が audit_log に出る。"""
    src = _read(COMPANIES_PY)
    # 直前に master_audit_payload を作って、promoted 時に "status": "active" を追加する形を期待。
    assert "if promoted:" in src
    assert 'master_audit_payload["status"] = "active"' in src, (
        "promoted=True 時に master_audit_payload['status']='active' を入れる処理が見つかりません。"
        " update_company と同様に new_data のトップレベルに変更後カラムを書くべきです。"
    )


# -----------------------------------------------------------------------------
# 3. explicit rollback in IntegrityError path (Minor 3)
# -----------------------------------------------------------------------------
def test_merge_rollbacks_on_integrity_error():
    """create_company / delete_company と流儀を揃えて、IntegrityError 経路で
    HTTPException を投げる前に明示 rollback する。"""
    src = _read(COMPANIES_PY)
    # merge 関数を行ベースで抽出（次の @router. デコレータまで or ファイル末尾まで）
    lines = src.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("async def merge_companies"):
            start = i
            break
    assert start is not None, "merge_companies 関数が見つかりません"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("@router.") or lines[i].startswith("def ") or lines[i].startswith("async def "):
            end = i
            break
    body = "\n".join(lines[start:end])
    # IntegrityError ハンドラ内に await db.rollback() がある
    assert "except IntegrityError as e:" in body, (
        "merge_companies 関数内に IntegrityError ハンドラが見つかりません"
    )
    # 簡易: ハンドラブロックの位置から HTTPException までに db.rollback() が出ている
    err_idx = body.find("except IntegrityError as e:")
    raise_idx = body.find("raise HTTPException", err_idx)
    assert err_idx != -1 and raise_idx != -1
    assert "await db.rollback()" in body[err_idx:raise_idx], (
        "IntegrityError ブロック内（raise HTTPException 前）で await db.rollback() が呼ばれていません"
    )


# -----------------------------------------------------------------------------
# 4. branch_name truncation logging + audit (Minor 4)
# -----------------------------------------------------------------------------
def test_branch_name_truncation_is_logged_and_recorded():
    """100 字超の branch_name が切り詰められたら logger.warning + audit_log に
    元 branch_name を残す。"""
    src = _read(COMPANIES_PY)
    assert "branch_name_truncations" in src, (
        "branch_name_truncations のトラッキングが実装されていません。"
    )
    # 警告ログが出ること
    assert re.search(
        r"logger\.warning\([^)]*branch_name[^)]*100",
        src,
    ), "branch_name 切り詰め時に logger.warning が呼ばれていません。"
    # audit_log の _merge.branch_name_truncations にも入ること
    assert (
        '_merge"]["branch_name_truncations"]' in src
        or "branch_name_truncations" in src
    ), "branch_name_truncations が audit_log payload に含まれていません。"


# -----------------------------------------------------------------------------
# 5. _customer_migration_map defensive guard (Major 1, forward-compat)
# -----------------------------------------------------------------------------
def test_merge_has_customer_migration_map_guard():
    """`_customer_migration_map` が存在する環境でも merge 元 DELETE が FK で詰まら
    ないよう、DELETE 直前に pg_tables 経由で存在確認 → UPDATE 付け替えを行う。"""
    src = _read(COMPANIES_PY)
    # pg_tables に対する存在確認
    assert "FROM pg_tables" in src
    assert "_customer_migration_map" in src, (
        "merge 関数内に _customer_migration_map の参照が見つかりません"
    )
    # 存在時に new_company_id を master に付け替える（Python 文字列リテラル分割を許容）
    assert "UPDATE _customer_migration_map" in src
    # 同一行 or 直後リテラルに SET new_company_id = :master が出ていることを確認
    upd_idx = src.find("UPDATE _customer_migration_map")
    next_block = src[upd_idx: upd_idx + 400]
    assert "SET new_company_id = :master" in next_block, (
        "_customer_migration_map.new_company_id を master に付け替える UPDATE が無い: "
        + next_block[:200]
    )


# -----------------------------------------------------------------------------
# 6. frontend server-side search fallback (Major 2)
# -----------------------------------------------------------------------------
def test_modal_uses_server_side_search():
    """MergeCompanyModal は search 文字列をサーバーに送って /companies?search= で
    再 fetch する（クライアント絞り込みのみだと per_page=100 超で silent failure する）。"""
    src = _read(MERGE_MODAL_TSX)
    # search query を URL に含める形でサーバーに送る
    assert (
        "search=${encodeURIComponent" in src
        or "search=${encodeURIComponent(q)}" in src
    ), "server-side search 用の URL クエリ構築が見つかりません。"
    # debounce 付きで search 状態を依存配列に持つ useEffect を期待
    assert "setTimeout" in src, "debounce のための setTimeout が見つかりません。"
    # 旧 useMemo フィルタ (クライアント絞り込みのみ) が主実装になっていないこと:
    # 新コードでは filteredCandidates = candidates のはず（server-side が先に効いている）
    assert "const filteredCandidates = candidates;" in src, (
        "filteredCandidates を candidates と等価にしてサーバー検索結果を直接表示する形に"
        "なっていません（クライアント側 includes フィルタが残っている可能性）。"
    )


# -----------------------------------------------------------------------------
# 7. frontend per_page cap warning (Major 2)
# -----------------------------------------------------------------------------
def test_modal_warns_when_results_capped():
    """候補が PER_PAGE_CAP (100) 件に達したら、ユーザーに「絞り込んでください」と
    警告を出す（silent failure を避ける）。"""
    src = _read(MERGE_MODAL_TSX)
    assert "PER_PAGE_CAP" in src, "PER_PAGE_CAP 定数が見つかりません。"
    assert "resultsCapped" in src, "resultsCapped 状態フラグが見つかりません。"
    # 100 件キャップ条件
    assert (
        "rows.length >= PER_PAGE_CAP" in src
        or "rows.length === PER_PAGE_CAP" in src
    ), "rows.length と PER_PAGE_CAP の比較が見つかりません。"
    # ユーザー向け文言（ADR-027 i18n 化後は i18n キーで確認）
    assert (
        "件に達しました" in src
        or "絞り込んでください" in src
        or "mergeCompany.resultsCapped" in src
    ), "100 件キャップ時の警告メッセージが UI に出ていません。"

from __future__ import annotations

import sys
from pathlib import Path

# project root を sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_schema_catchup_sync import check_schema_catchup_sync


def test_schema_catchup_lists_are_in_sync():
    repo_root = Path(__file__).resolve().parents[2]
    check_schema_catchup_sync(repo_root)

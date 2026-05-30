"""
PokeAPI (https://pokeapi.co) からポケモン図鑑の最新データを取得するサービス (ADR-084)。

用途: /super-admin/dex/pokemon/import/preview から呼ばれ、PokeAPI の全国図鑑と
      public.pokemon_dex を突合し「DB に無い新規 dex_number」を日英名・世代つきで返す。

安全策:
  - 手動トリガのみ (super-admin が取込ボタンを押した時だけ呼ぶ)。
  - 外部 URL は固定 (SSRF 防止。ユーザー入力 URL は受けない)。
  - タイムアウト (接続/読込) + 並列度制限 (Semaphore) + 取得件数上限 (max_fetch)。
  - 一覧取得は 1 リクエスト。詳細取得は「DB に無い新規番号」のみに絞るため、
    既に最新 (新規 0 件) なら一覧 1 リクエストで完了し外部負荷は最小。
  - PokeAPI Fair Use: 既存と差分のある分だけ取得し、全件スキャンはしない。

トレーナー図鑑は PokeAPI に存在しないため対象外 (ポケモンのみ)。
"""
from __future__ import annotations

import asyncio

import httpx

_POKEAPI_BASE = "https://pokeapi.co/api/v2"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_CONCURRENCY = 5
_USER_AGENT = "salesanchor-dex-import/1.0 (+https://app.salesanchor.jp)"

# "generation-ix" 等のローマ数字 → 整数
_GEN_ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
}


def _dex_number_from_url(url: str) -> int | None:
    """species url 末尾の id を全国図鑑番号として取り出す。"""
    parts = url.rstrip("/").split("/")
    if not parts:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


async def _fetch_species_list(client: httpx.AsyncClient) -> tuple[int, list[int]]:
    resp = await client.get(
        f"{_POKEAPI_BASE}/pokemon-species", params={"limit": 20000}
    )
    resp.raise_for_status()
    data = resp.json()
    numbers: list[int] = []
    for item in data.get("results", []):
        n = _dex_number_from_url(item.get("url", ""))
        if n is not None:
            numbers.append(n)
    return int(data.get("count") or len(numbers)), numbers


async def _fetch_species_detail(
    client: httpx.AsyncClient, dex_number: int, sem: asyncio.Semaphore
) -> dict | None:
    async with sem:
        resp = await client.get(f"{_POKEAPI_BASE}/pokemon-species/{dex_number}")
        resp.raise_for_status()
        d = resp.json()

    name_ja: str | None = None
    name_en: str | None = None
    for nm in d.get("names", []):
        lang = ((nm.get("language") or {}).get("name")) or ""
        value = nm.get("name") or ""
        if lang in ("ja-Hrkt", "ja") and not name_ja:
            name_ja = value
        elif lang == "en" and not name_en:
            name_en = value

    generation: int | None = None
    gen_name = ((d.get("generation") or {}).get("name")) or ""
    if gen_name.startswith("generation-"):
        generation = _GEN_ROMAN.get(gen_name.split("-", 1)[1])

    if not name_ja or not name_en:
        # 日本語名・英語名のどちらかが取れないものは取り込まない。
        # public.pokemon_dex は name_ja / name_en とも NOT NULL のため、欠落分を
        # 混ぜると apply の一括 INSERT が NotNullViolation で丸ごと失敗する。
        return None
    return {
        "dex_number": dex_number,
        "name_ja": name_ja,
        "name_en": name_en,
        "generation": generation,
    }


async def fetch_new_species(
    existing_numbers: set[int], *, max_fetch: int = 500
) -> dict:
    """
    PokeAPI の全国図鑑と既存 dex_number を突合し、DB に無い新規分を日英名つきで返す。

    返り値: {
        "source_count": PokeAPI の総数,
        "added": [{dex_number, name_ja, name_en, generation}, ...],
        "added_count": len(added),
        "truncated": 新規が max_fetch を超えて打ち切ったか,
    }
    """
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
    ) as client:
        source_count, numbers = await _fetch_species_list(client)
        new_numbers = sorted(n for n in numbers if n not in existing_numbers)
        truncated = len(new_numbers) > max_fetch
        target = new_numbers[:max_fetch]

        sem = asyncio.Semaphore(_CONCURRENCY)
        results = await asyncio.gather(
            *(_fetch_species_detail(client, n, sem) for n in target),
            return_exceptions=True,
        )

    added = [r for r in results if isinstance(r, dict)]
    added.sort(key=lambda r: r["dex_number"])
    return {
        "source_count": source_count,
        "added": added,
        "added_count": len(added),
        "truncated": truncated,
    }

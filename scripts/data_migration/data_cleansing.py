"""
Phase 1 再設計 / データ移行共通クレンジング関数。

スプレッドシート原本の表記揺れ・絵文字・typo を吸収する。
設計書 第8章 8-2 の「データクレンジングが必要な箇所」一覧を実装。
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

import phonenumbers
import pycountry

logger = logging.getLogger(__name__)

# --- bool変換用の「真」を示す値 ---
_TRUE_TOKENS = frozenset({
    "⭕️", "⭕", "○", "◯", "✅", "✓", "TRUE", "True", "true",
    "YES", "Yes", "yes", "1", "はい", "あり",
})

# --- 連絡ツール表記揺れ → enum ---
# 設計書 §8-2「連絡ツール表記ゆれ：WA / Whats App / IG / FB / ID / 紹介 が混在」
_CONTACT_CHANNEL_MAP = {
    "wa": "whatsapp",
    "whatsapp": "whatsapp",
    "whats app": "whatsapp",
    "whatspp": "whatsapp",
    "ig": "instagram",
    "instagram": "instagram",
    "fb": "facebook_messenger",
    "facebook": "facebook_messenger",
    "messenger": "facebook_messenger",
    "id": "line_id",
    "line": "line_id",
    "line id": "line_id",
    "紹介": "referral",
    "referral": "referral",
    "discord": "discord",
    "telegram": "telegram",
    "email": "email",
    "メール": "email",
    "電話": "phone",
    "phone": "phone",
}

# --- 国名表記揺れの個別補正（pycountry のfuzzy検索でカバーできないケース） ---
_COUNTRY_OVERRIDES = {
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "us": "US",
    "united states of america": "US",
    "united states": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "britain": "GB",
    "great britain": "GB",
    "jp": "JP",
    "japan": "JP",
    "日本": "JP",
    "china": "CN",
    "中国": "CN",
    "taiwan": "TW",
    "台湾": "TW",
    "hong kong": "HK",
    "香港": "HK",
    "korea": "KR",
    "south korea": "KR",
    "韓国": "KR",
}


def parse_bool_loose(value: str | None) -> bool:
    """
    スプレッドシートの絵文字・空欄を bool に変換する。
    真: ⭕️ / ✅ / ○ / TRUE / はい 等
    偽: 上記以外（空欄 / ✗ / FALSE 等）
    """
    if value is None:
        return False
    return value.strip() in _TRUE_TOKENS


def parse_amount(value: str | None) -> Decimal | None:
    """
    '400,000' や '¥400,000' のような金額文字列を Decimal に変換する。
    カンマ除去・通貨記号除去。空欄・変換不能は None。
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    # 通貨記号・全角記号を除去
    cleaned = re.sub(r"[¥$€£,，\s]", "", stripped)
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        logger.warning("parse_amount: 変換不能 %r → None", value)
        return None


def parse_integer(value: str | None) -> int | None:
    """小さな整数列（月間頻度・信頼度 等）を int に変換する。"""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        logger.warning("parse_integer: 変換不能 %r → None", value)
        return None


def parse_phone_e164(value: str | None, default_region: str = "JP") -> str | None:
    """
    phonenumbers で E.164 形式に変換する。
    `#ERROR!` やハイフン混在、国番号なし等を吸収。
    変換不能なら None + warn ログ。
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        # 国番号付き（+1... +81...）ならそのまま、無ければ default_region を推測
        parsed = phonenumbers.parse(stripped, default_region if not stripped.startswith("+") else None)
        if not phonenumbers.is_valid_number(parsed):
            logger.warning("parse_phone_e164: 無効な電話番号 %r → None", value)
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        logger.warning("parse_phone_e164: parse 失敗 %r → None", value)
        return None


def parse_country_code(value: str | None) -> str | None:
    """
    国名表記（'United States' 等）を ISO 3166-1 alpha-2 コード（'US' 等）に変換する。
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    # 既に2文字コードの場合
    if len(stripped) == 2 and stripped.isalpha():
        try:
            pycountry.countries.lookup(stripped.upper())
            return stripped.upper()
        except LookupError:
            pass
    # 個別オーバーライド（小文字一致）
    lowered = stripped.lower()
    if lowered in _COUNTRY_OVERRIDES:
        return _COUNTRY_OVERRIDES[lowered]
    # pycountry fuzzy search
    try:
        matches = pycountry.countries.search_fuzzy(stripped)
        if matches:
            return matches[0].alpha_2
    except LookupError:
        pass
    logger.warning("parse_country_code: 国名解決不能 %r → None", value)
    return None


def parse_contact_channel(value: str | None) -> str | None:
    """連絡ツールの表記揺れを enum 値に正規化する。"""
    if value is None:
        return None
    stripped = value.strip().lower()
    if not stripped:
        return None
    # 完全一致優先
    if stripped in _CONTACT_CHANNEL_MAP:
        return _CONTACT_CHANNEL_MAP[stripped]
    # 部分一致（whatsapp / ig 等の短縮を救う）
    for key, val in _CONTACT_CHANNEL_MAP.items():
        if key in stripped:
            return val
    logger.warning("parse_contact_channel: 解決不能 %r → None", value)
    return None


def split_sales_channels(value: str | None) -> list[str]:
    """販売先のカンマ区切り文字列を行分割する。重複・空白を除去。"""
    if value is None:
        return []
    items = [ch.strip() for ch in re.split(r"[,、，]", value)]
    # 空白除去・重複排除・順序保持
    seen: set[str] = set()
    result: list[str] = []
    for ch in items:
        if ch and ch not in seen:
            seen.add(ch)
            result.append(ch)
    return result


def normalize_status(value: str | None) -> str:
    """
    担当者マスタの status 列（'有効' / '無効' / '保留'）を
    DB の CHECK 制約値（'active' / 'inactive' / 'pending'）に変換する。
    """
    if value is None:
        return "active"
    mapping = {
        "有効": "active",
        "active": "active",
        "無効": "inactive",
        "inactive": "inactive",
        "保留": "pending",
        "pending": "pending",
    }
    return mapping.get(value.strip().lower() if value.strip().isascii() else value.strip(), "active")


def is_test_user_name(surname: str | None, given_name: str | None) -> bool:
    """
    設計書 §5-1 「EMP-00002『営業 太郎』はテストデータなので投入しない」判定。
    氏名から判定する（'太郎' 等が含まれていればテストとみなす）。
    """
    if not surname and not given_name:
        return True  # 全空はテスト扱い
    full_name = f"{(surname or '').strip()} {(given_name or '').strip()}".strip()
    test_patterns = [
        "営業 太郎",
        "テスト",
        "test",
        "太郎",
    ]
    return any(pattern in full_name for pattern in test_patterns)

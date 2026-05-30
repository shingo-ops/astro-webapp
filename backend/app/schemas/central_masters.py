"""
中央 admin（マーケットプレイス Jarvis 運用 admin）マスタ用 Pydantic スキーマ。

spec.md v1.1 F2 (Sprint 2):
  - public.knowledge_rules
  - public.supplier_aliases
  - public.tcg_series_master
  - public.pokemon_dex, public.trainer_dex
  - public.suppliers (拡張)
  - public.supplier_discord_routing

すべて require_super_admin 経由で書込される public schema のマスタ。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================================
# knowledge_rules
# ============================================================================

_VALID_PATTERN_TYPES = {"regex", "exact", "prefix", "suffix", "contains"}


class KnowledgeRuleBase(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    pattern_type: str = Field(min_length=1, max_length=20)
    pattern: str = Field(min_length=1, max_length=500)
    normalized_to: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=100, ge=0, le=10000)
    language: str = Field(default="ja", min_length=2, max_length=2)
    is_active: bool = True

    @field_validator("pattern_type")
    @classmethod
    def _validate_pattern_type(cls, v: str) -> str:
        if v not in _VALID_PATTERN_TYPES:
            raise ValueError(
                f"pattern_type must be one of {sorted(_VALID_PATTERN_TYPES)}"
            )
        return v


class KnowledgeRuleCreate(KnowledgeRuleBase):
    pass


class KnowledgeRuleUpdate(BaseModel):
    category: Optional[str] = Field(default=None, max_length=50)
    pattern_type: Optional[str] = Field(default=None, max_length=20)
    pattern: Optional[str] = Field(default=None, max_length=500)
    normalized_to: Optional[str] = Field(default=None, max_length=500)
    priority: Optional[int] = Field(default=None, ge=0, le=10000)
    language: Optional[str] = Field(default=None, max_length=2)
    is_active: Optional[bool] = None


class KnowledgeRuleResponse(KnowledgeRuleBase):
    id: int
    created_by: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# supplier_aliases
# ============================================================================


class SupplierAliasBase(BaseModel):
    supplier_id: int
    alias_text: str = Field(min_length=1, max_length=500)
    language: str = Field(default="ja", min_length=2, max_length=2)
    product_id: Optional[int] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source: Optional[str] = Field(default=None, max_length=50)


class SupplierAliasCreate(SupplierAliasBase):
    pass


class SupplierAliasUpdate(BaseModel):
    supplier_id: Optional[int] = None
    alias_text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    language: Optional[str] = Field(default=None, max_length=2)
    product_id: Optional[int] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source: Optional[str] = Field(default=None, max_length=50)


class SupplierAliasResponse(SupplierAliasBase):
    id: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# tcg_series_master
# ============================================================================

# ADR-083: TCG 種別は public.tcg_type_master で管理（固定リスト廃止）。
# tcg_type の値検証は DB 側（tcg_type_master）に委ねる。code は安定キーのため不変。


class TcgTypeBase(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name_ja: str = Field(min_length=1, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)
    sort_order: int = Field(default=100, ge=0)
    is_active: bool = True


class TcgTypeCreate(TcgTypeBase):
    pass


class TcgTypeUpdate(BaseModel):
    # code は不変（既存シリーズが参照するため）。名称・並び順・有効フラグのみ更新可。
    name_ja: Optional[str] = Field(default=None, min_length=1, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)
    sort_order: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class TcgTypeResponse(TcgTypeBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class TcgSeriesBase(BaseModel):
    tcg_type: str = Field(min_length=1, max_length=50)
    series_code: str = Field(min_length=1, max_length=50)
    name_ja: str = Field(min_length=1, max_length=255)
    name_en: Optional[str] = Field(default=None, max_length=255)
    release_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=50)


class TcgSeriesCreate(TcgSeriesBase):
    pass


class TcgSeriesUpdate(BaseModel):
    tcg_type: Optional[str] = None
    series_code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name_ja: Optional[str] = Field(default=None, min_length=1, max_length=255)
    name_en: Optional[str] = Field(default=None, max_length=255)
    release_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=50)


class TcgSeriesResponse(TcgSeriesBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# pokemon_dex / trainer_dex
# ============================================================================


class DexEntryBase(BaseModel):
    dex_number: int = Field(ge=1)
    name_ja: str = Field(min_length=1, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)


class PokemonDexCreate(DexEntryBase):
    generation: Optional[int] = Field(default=None, ge=1, le=20)
    region: Optional[str] = Field(default=None, max_length=50)


class PokemonDexUpdate(BaseModel):
    dex_number: Optional[int] = Field(default=None, ge=1)
    name_ja: Optional[str] = Field(default=None, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)
    generation: Optional[int] = Field(default=None, ge=1, le=20)
    region: Optional[str] = Field(default=None, max_length=50)


class PokemonDexResponse(PokemonDexCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class TrainerDexCreate(DexEntryBase):
    era: Optional[str] = Field(default=None, max_length=50)


class TrainerDexUpdate(BaseModel):
    dex_number: Optional[int] = Field(default=None, ge=1)
    name_ja: Optional[str] = Field(default=None, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)
    era: Optional[str] = Field(default=None, max_length=50)


class TrainerDexResponse(TrainerDexCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# PokeAPI 取込 (ADR-084) — ポケモン図鑑のみ
# ============================================================================


class DexImportEntry(BaseModel):
    dex_number: int = Field(ge=1)
    name_ja: str = Field(min_length=1, max_length=100)
    name_en: Optional[str] = Field(default=None, max_length=100)
    generation: Optional[int] = Field(default=None, ge=1, le=20)


class DexImportPreviewResponse(BaseModel):
    source: str = "pokeapi"
    source_count: int  # PokeAPI 側の総数
    db_count: int  # 既存 pokemon_dex 件数
    added: list[DexImportEntry]  # DB に無い新規分
    added_count: int
    truncated: bool = False  # 新規が上限を超えて打ち切ったか


class DexImportApplyRequest(BaseModel):
    entries: list[DexImportEntry] = Field(default_factory=list)


class DexImportApplyResponse(BaseModel):
    inserted_count: int


# ============================================================================
# public.suppliers (拡張: supplier_type / default_language)
# ============================================================================

_VALID_SUPPLIER_TYPES = {"individual", "corporate"}
_VALID_DEFAULT_LANGUAGES = {"ja", "en", "ko", "zh"}


class CentralSupplierBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    supplier_type: str = Field(default="corporate")
    default_language: str = Field(default="ja", min_length=2, max_length=2)
    contact_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=5000)
    notes: Optional[str] = Field(default=None, max_length=5000)
    is_active: bool = True

    @field_validator("supplier_type")
    @classmethod
    def _validate_supplier_type(cls, v: str) -> str:
        if v not in _VALID_SUPPLIER_TYPES:
            raise ValueError(
                f"supplier_type must be one of {sorted(_VALID_SUPPLIER_TYPES)}"
            )
        return v

    @field_validator("default_language")
    @classmethod
    def _validate_default_language(cls, v: str) -> str:
        if v not in _VALID_DEFAULT_LANGUAGES:
            raise ValueError(
                f"default_language must be one of {sorted(_VALID_DEFAULT_LANGUAGES)}"
            )
        return v


class CentralSupplierCreate(CentralSupplierBase):
    pass


class CentralSupplierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    supplier_type: Optional[str] = None
    default_language: Optional[str] = Field(default=None, max_length=2)
    contact_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=5000)
    notes: Optional[str] = Field(default=None, max_length=5000)
    is_active: Optional[bool] = None


class CentralSupplierResponse(CentralSupplierBase):
    id: int
    supplier_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# supplier_discord_routing
# ============================================================================


class SupplierDiscordRoutingBase(BaseModel):
    supplier_id: int
    discord_guild_id: str = Field(min_length=1, max_length=64)
    discord_channel_id: str = Field(min_length=1, max_length=64)
    is_active: bool = True


class SupplierDiscordRoutingCreate(SupplierDiscordRoutingBase):
    pass


class SupplierDiscordRoutingUpdate(BaseModel):
    supplier_id: Optional[int] = None
    discord_guild_id: Optional[str] = Field(default=None, max_length=64)
    discord_channel_id: Optional[str] = Field(default=None, max_length=64)
    is_active: Optional[bool] = None


class SupplierDiscordRoutingResponse(SupplierDiscordRoutingBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# tenant_admin: inventory.visibility.* マトリクス UI
# ============================================================================


class RoleVisibilityPermission(BaseModel):
    """1 ロール × inventory.visibility.* 1 キーの割当状態。"""

    role_id: int
    role_name: str
    permission_key: str
    is_granted: bool


class RoleVisibilityMatrixResponse(BaseModel):
    """テナント admin の在庫表示権限マトリクス全体。"""

    visibility_keys: list[str]
    rows: list[RoleVisibilityPermission]


class RoleVisibilityAssign(BaseModel):
    """1 ロールに対する inventory.visibility.* キー集合の上書き。"""

    role_id: int
    visibility_keys: list[str]

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantBotConfig:
    tenant_id: int
    tenant_code: str
    bot_token: str


def load_tenant_bot_configs() -> list[TenantBotConfig]:
    """環境変数から per-tenant Bot トークンをロードする (ADR-009 5-3)。

    形式: DISCORD_BOT_TOKEN_<TENANT_ID>=<token>
    例:   DISCORD_BOT_TOKEN_4=MTAxxxxxx...

    オプションで DISCORD_TENANT_CODE_<TENANT_ID> でテナントコードも指定可。
    未指定時は "tenant_<id>" にフォールバックする。
    """
    configs: list[TenantBotConfig] = []
    prefix = "DISCORD_BOT_TOKEN_"

    for key, value in os.environ.items():
        if not key.startswith(prefix) or not value:
            continue
        suffix = key[len(prefix):]
        if not suffix.isdigit():
            continue

        tenant_id = int(suffix)
        tenant_code = os.environ.get(
            f"DISCORD_TENANT_CODE_{tenant_id}",
            f"tenant_{tenant_id}",
        )
        configs.append(
            TenantBotConfig(
                tenant_id=tenant_id,
                tenant_code=tenant_code,
                bot_token=value,
            )
        )

    return configs


def get_log_level() -> str:
    return os.environ.get("DISCORD_GATEWAY_LOG_LEVEL", "INFO").upper()
